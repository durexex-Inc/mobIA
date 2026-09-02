import logging
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text as sql

from mobia.domain.agente.classificador import RespostaInvalida
from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Extracao, Intencao, Urgencia
from mobia.domain.agente.turno import KIND_DA_RESPOSTA, SUBAGENTE_DESAMBIGUADOR, executar_turno
from mobia.domain.context.montagem import ContextoIrreducivel
from mobia.domain.context.repositorio import ler_estado
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRecusado, EnvioRetentavel
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def test_turno_classifica_entrega_e_grava(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == ["Ola! Em qual regiao voce procura?"]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.INVESTIMENTO
    assert gravada.confianca == Decimal("0.91")

    total = await session.scalar(sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 1, "a fala do agente entra na linha do tempo"


async def test_a_fala_e_gravada_depois_da_entrega(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Se a entrega falha, nao pode sobrar fala fantasma no historico.

    Texto que o lead nunca viu entraria no contexto do proximo turno e depois
    seria dobrado permanentemente no resumo da TEC-127: o agente passaria a
    acreditar que disse algo que nao disse.
    """
    outbound = outbound_fake(EnvioRetentavel("timeout"))

    with pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session, classificador_fake(), outbound, resumidor_fake(), contador_fake()
        )

    total = await session.scalar(sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 0, "nada entregue, nada gravado"


async def test_fora_da_janela_termina_o_turno_sem_erro(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """Expirar nao e falhar: retentar nunca vai entregar."""
    outbound = outbound_fake(EnvioForaDaJanela("131047"))

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session, classificador_fake(), outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "expirado"
    assert "outbound.fora_da_janela" in caplog.text


async def test_contexto_irreducivel_nao_derruba_o_worker(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    rodar_turno,
    monkeypatch,
    caplog,
) -> None:
    """Mensagem grande demais faz o lead ser ignorado -- em silencio para ele,
    mas nunca em silencio no log."""
    from mobia.domain.agente import turno as turno_mod

    async def _estoura(*_args: Any, **_kwargs: Any) -> Any:
        raise ContextoIrreducivel("tokens=99999, teto=11600")

    monkeypatch.setattr(turno_mod, "montar_contexto", _estoura)
    classificador = classificador_fake()

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
        )

    assert resultado == "sem_resposta"
    assert classificador.chamadas == 0, "nem chega a pagar a chamada ao modelo"
    assert "turno.contexto_irreducivel" in caplog.text


async def test_a_intencao_e_gravada_mesmo_se_a_entrega_falhar(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A classificacao aconteceu de verdade -- registra-la e honesto.

    Ela e sobre a mensagem do lead, nao sobre a resposta que nao saiu.
    """
    outbound = outbound_fake(EnvioRetentavel("timeout"))

    with pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session,
            classificador_fake(Intencao.ALUGUEL),
            outbound,
            resumidor_fake(),
            contador_fake(),
        )

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.ALUGUEL


async def test_reentrega_suprimida_nao_grava_fala_fantasma(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, caplog
) -> None:
    """`send()` devolve False, sem levantar, quando a guarda (Task 3) suprime
    uma reentrega -- ja existe reserva em outbound_dispatches para este
    (message_id, kind) de uma tentativa anterior. O texto desta chamada nova
    ao classificador pode nao ser o que o lead recebeu (ou nada pode ter saido
    ainda). Gravar aqui e a mesma fala fantasma que a ordem grava-depois-de-
    entregar existe para evitar, so que entrando pela porta do retorno em vez
    de uma excecao.
    """
    from conftest import ModeradorFake, _entrada_do_lead

    linha = await _entrada_do_lead(session)
    # Simula a reserva que uma tentativa anterior ja commitou: a UNIQUE
    # (message_id, kind) faz a proxima reserva colidir sem tocar em `_deliver`.
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=linha.id, kind=KIND_DA_RESPOSTA))
    await session.commit()

    outbound = outbound_fake()

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(),
        )

    assert resultado == "reentrega_suprimida"
    assert outbound.entregues == [], "a guarda nunca chega a chamar _deliver"

    total = await session.scalar(sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 0, "sem confirmacao do que foi entregue, nao ha texto confiavel pra gravar"

    # Nivel `error`, nao `warning`: a linha fecha em PROCESSED -- terminal, o
    # sweeper nunca reenfileira -- e o lead pode nao ter recebido nada em
    # nenhuma tentativa. A visibilidade deste desfecho vem so do nivel do log,
    # como no 4xx, e e `error` que o alerta observa.
    eventos = [
        registro
        for registro in caplog.records
        if "turno.reentrega_suprimida" in registro.getMessage()
    ]
    assert eventos, "o desfecho tem de aparecer no log"
    assert all(registro.levelno == logging.ERROR for registro in eventos)


BAIXA = Decimal("0.45")


async def test_confianca_baixa_entrega_a_pergunta_no_lugar_da_resposta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 1: abaixo do limiar o lead recebe pergunta, nao suposicao.

    A resposta da primeira chamada foi escrita assumindo COMPRA -- e ela que
    nao pode chegar ao lead.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=BAIXA)
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert classificador.desambiguacoes == 1
    assert outbound.entregues == [classificador.pergunta]
    assert "Em qual regiao" not in outbound.entregues[0], "a resposta que assumia COMPRA nao sai"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is not None, "a entrega confirmou -- o marcador tem de existir"


async def test_confianca_no_limiar_exato_responde_sem_perguntar(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 2: 0,6 nao desambigua, e nem chega a pagar a segunda chamada."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.60"))
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 0
    assert outbound.entregues == ["Ola! Em qual regiao voce procura?"]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_o_palpite_cru_e_gravado_e_a_efetiva_e_indefinida(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A tabela nao edita o classificador; quem roteia le pela `efetiva`."""
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA
    assert gravada.confianca == BAIXA
    assert gravada.efetiva is Intencao.INDEFINIDA


async def test_ambiguidade_persistente_nao_repete_a_pergunta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 4: a resposta do lead continuou vaga, e o agente nao insiste.

    O segundo turno entrega a resposta normal da primeira chamada -- que e a
    "qualificacao generica" possivel hoje, ja que trilha nenhuma existe antes
    da TEC-137. Ver a secao de escopo do spec.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=BAIXA)
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1, "uma pergunta por episodio, nao por turno"
    assert outbound.entregues[1] == "Ola! Em qual regiao voce procura?"


async def test_classificacao_confiante_abre_um_episodio_novo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Uma conversa longa que fica clara e volta a ficar vaga pode perguntar de novo.

    E o "por episodio" da regra: a classificacao confiante no meio e a
    evidencia de que a ambiguidade anterior foi resolvida.
    """
    vago = classificador_fake(Intencao.COMPRA, confianca=BAIXA)
    claro = classificador_fake(Intencao.ALUGUEL, confianca=Decimal("0.91"))
    outbound = outbound_fake()

    await rodar_turno(session, vago, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, claro, outbound, resumidor_fake(), contador_fake())

    # A classificacao confiante do turno 2 tem de ter limpado o marcador --
    # provado pela coluna, nao so pela contagem de chamadas do dublê abaixo,
    # que provaria o mesmo efeito por consequencia em vez de pela causa.
    async with get_sessionmaker()() as outra:
        entre_turnos = await ler_intencao(outra, CANAL, CONVERSA)
    assert entre_turnos is not None
    assert entre_turnos.desambiguado_em is None

    await rodar_turno(session, vago, outbound, resumidor_fake(), contador_fake())

    assert vago.desambiguacoes == 2
    assert claro.desambiguacoes == 0


async def test_entrega_expirada_nao_queima_a_pergunta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """O marcador afirma "eu ja perguntei" -- e nada chegou ao lead.

    Marca-lo aqui deixaria a conversa em INDEFINIDA para sempre sem ninguem
    ter perguntado nada.
    """
    outbound = outbound_fake(EnvioForaDaJanela("131047"))

    resultado = await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        outbound,
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado == "expirado"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_entrega_recusada_nao_queima_a_pergunta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """O terceiro desfecho sem entrega confirmada: 4xx permanente da Meta.

    Mesmo raciocinio de `test_entrega_expirada_nao_queima_a_pergunta` -- o
    marcador afirma "eu ja perguntei", e um `EnvioRecusado` significa que nada
    chegou ao lead. O spec promete o marcador ausente nos tres desfechos sem
    entrega confirmada (expirado, recusado, reentrega_suprimida); so os dois
    primeiros tinham teste.
    """
    outbound = outbound_fake(EnvioRecusado("400"))

    resultado = await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        outbound,
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado == "sem_resposta"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_reentrega_suprimida_nao_marca_o_episodio(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """`send()` devolveu False: `_deliver` nunca foi chamado nesta passada.

    Mesmo criterio da fala fantasma -- sem confirmacao de entrega, nada que
    afirme "ja perguntei" pode ser gravado.
    """
    from conftest import ModeradorFake, _entrada_do_lead

    linha = await _entrada_do_lead(session)
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=linha.id, kind=KIND_DA_RESPOSTA))
    await session.commit()

    resultado = await executar_turno(
        get_sessionmaker(),
        message=linha,
        classificador=classificador_fake(Intencao.COMPRA, confianca=BAIXA),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=ModeradorFake(),
    )

    assert resultado == "reentrega_suprimida"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.desambiguado_em is None


async def test_a_fala_gravada_e_a_pergunta_com_a_telemetria_da_segunda_chamada(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """O que o lead recebeu foi a pergunta -- e e ela que entra na linha do tempo.

    Os tokens sao os da chamada 2. Os da chamada 1, cuja resposta foi
    descartada, ficam so no log `agente.turno_gerado`: o custo do turno
    ambiguo esta inteiro nos logs, repartido em duas linhas, e so uma delas
    vira linha no banco. Ver a secao de telemetria do spec.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=BAIXA)

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    linha = (
        await session.execute(
            sql(
                "SELECT m.id, t.subagent, t.tokens_out FROM messages m"
                " JOIN message_telemetry t ON t.message_id = m.id"
                " WHERE m.direction = 'OUTBOUND'"
            )
        )
    ).one()
    assert linha.subagent == SUBAGENTE_DESAMBIGUADOR
    assert linha.tokens_out == 40, "telemetria da chamada 2, nao da 1"


async def test_falha_da_segunda_chamada_derruba_o_turno(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Nenhuma politica nova: propaga, o job marca FAILED, o sweeper retenta.

    E como o marcador so e escrito depois da entrega, a retentativa desambigua
    de verdade em vez de encontrar o marcador e desistir.
    """
    classificador = classificador_fake(
        Intencao.COMPRA,
        confianca=BAIXA,
        erro_da_desambiguacao=RespostaInvalida("stop_reason='max_tokens'"),
    )
    outbound = outbound_fake()

    with pytest.raises(RespostaInvalida):
        await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert outbound.entregues == [], "nada foi entregue"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA, "a classificacao aconteceu e fica registrada"
    assert gravada.desambiguado_em is None, "a proxima passada ainda pode perguntar"


async def test_marca_de_perguntou_nao_e_gravada_quando_desambigua(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A resposta da chamada 1 e descartada -- paga e nao entregue (TEC-236).

    O que ela declarou ter "perguntado" nunca chegou ao lead: quem chega e a
    pergunta do desambiguador. Fix round 1 da Task 4 (TEC-257): a versao
    anterior gravava `perguntou` no mesmo commit da intencao/extracao, antes de
    saber se a resposta ia ser entregue -- e como a uniao no SQL nunca remove,
    isso marcava o campo como ja perguntado para sempre, sem nunca ter sido.
    """
    classificador = classificador_fake(
        Intencao.COMPRA,
        confianca=BAIXA,
        extracao=Extracao(quartos=2),
        perguntou=("regiao",),
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert classificador.desambiguacoes == 1, "o turno de fato desambiguou"

    async with get_sessionmaker()() as outra:
        estado = await ler_estado(outra, CANAL, CONVERSA)
    assert estado is not None
    assert estado.perguntados_sem_resposta == [], (
        "vazio, nao nulo (Task 4 sempre escreve a coluna) e sem 'regiao': "
        "a chamada que perguntou isso foi descartada"
    )


async def test_marca_de_perguntou_e_gravada_no_caminho_normal(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Sem desambiguacao e sem bloqueio, `gerada` e de fato o texto entregue."""
    classificador = classificador_fake(
        Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=("regiao",),
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert classificador.desambiguacoes == 0

    async with get_sessionmaker()() as outra:
        estado = await ler_estado(outra, CANAL, CONVERSA)
    assert estado is not None
    assert estado.perguntados_sem_resposta == ["regiao"]


async def test_marca_de_perguntou_nao_e_gravada_com_saida_bloqueada(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O lead recebeu `TEXTO_NEUTRO_DE_SAIDA`, que nao pergunta nada."""
    classificador = classificador_fake(
        Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=("regiao",),
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador=moderador_fake(bloqueia_saida=True),
    )

    assert resultado == "respondido"

    async with get_sessionmaker()() as outra:
        estado = await ler_estado(outra, CANAL, CONVERSA)
    assert estado is not None
    assert estado.perguntados_sem_resposta == []


async def test_marca_de_perguntou_pos_entrega_nao_reescreve_valor_concorrente(
    session, classificador_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A escrita pos-entrega toca so a marca -- nunca intencao/extracao.

    Fix da revisao do fechamento da TEC-257: a versao anterior deste commit
    reusava `gravar_estado` inteiro no ponto pos-entrega, regravando os
    mesmos `intencao`/`extracao` de `gerada`. Isso e idempotente so contra si
    mesmo -- contra um turno concorrente da MESMA conversa que grave um valor
    mais novo PARA O MESMO CAMPO entre o commit pre-entrega e esta escrita,
    aquele reuso sobrescreveria o valor mais novo com o mais velho,
    invertendo "mais novo vence" em silencio. `marcar_perguntados` fecha isso
    tocando so a coluna da marca -- nao ha coluna de valor no `SET` para
    inverter.

    O teste simula a corrida usando o unico ponto de sincronizacao real do
    turno: o outbound. `_deliver` -- chamado depois do commit pre-entrega
    (que grava `quartos=2`) e antes da marcacao pos-entrega -- grava
    `quartos=5` como se fosse um turno concorrente mais novo da mesma
    conversa. Com o bug, a marcacao pos-entrega regravaria `quartos=2` por
    cima; com o fix, `quartos` fica intocado.
    """
    from conftest import OutboundFake

    class OutboundQueEscreveNoMeio(OutboundFake):
        async def _deliver(self, message_id, kind, payload) -> None:
            async with get_sessionmaker()() as concorrente:
                await concorrente.execute(
                    sql(
                        "UPDATE lead_qualification SET quartos = 5 "
                        "WHERE channel = :canal AND conversation_key = :conversa"
                    ),
                    {"canal": CANAL, "conversa": CONVERSA},
                )
                await concorrente.commit()
            await super()._deliver(message_id, kind, payload)

    classificador = classificador_fake(
        Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=("regiao",),
    )
    outbound = OutboundQueEscreveNoMeio(get_sessionmaker())

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"

    async with get_sessionmaker()() as outra:
        estado = await ler_estado(outra, CANAL, CONVERSA)
    assert estado is not None
    assert estado.quartos == 5, (
        "o valor concorrente (mais novo) foi sobrescrito pela marcacao "
        "pos-entrega -- ela regravou extracao=2, invertendo 'mais novo vence'"
    )
    assert estado.perguntados_sem_resposta == ["regiao"], (
        "a marca ainda tem de ser gravada -- so os valores nao podem ser tocados"
    )


# Extracao com os tres campos que faltam para completar a RN-05.3, dado que a
# intencao qualificavel vem por fora, do classificador -- ver CAMPOS_OBRIGATORIOS.
_EXTRACAO_QUE_QUALIFICA = Extracao(
    faixa_preco_max_centavos=50_000_000,
    regiao="pinheiros",
    urgencia=Urgencia.ATE_3_MESES,
)


async def test_a_travessia_para_qualificado_e_registrada(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """O evento que a RN-17.1 (taxa de qualificacao) vai precisar contar. Sem
    ele esta card entrega uma funcao que ninguem chama."""
    # Turno que completa o quarto campo obrigatorio.
    classificador = classificador_fake(Intencao.COMPRA, extracao=_EXTRACAO_QUE_QUALIFICA)
    outbound = outbound_fake()

    with caplog.at_level(logging.INFO):
        resultado = await rodar_turno(
            session, classificador, outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "respondido"
    registros = caplog.records
    assert any("lead.qualificado" in registro.getMessage() for registro in registros)


async def test_a_travessia_nao_se_repete_nos_turnos_seguintes(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """Dispara na borda, nao no estado. Um lead ja qualificado que continua
    conversando nao gera o evento de novo -- senao a taxa de qualificacao
    contaria conversas, nao leads."""
    outbound = outbound_fake()

    # Primeiro turno completa a qualificacao.
    with caplog.at_level(logging.INFO):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA, extracao=_EXTRACAO_QUE_QUALIFICA),
            outbound,
            resumidor_fake(),
            contador_fake(),
        )

    caplog.clear()

    # Segundo turno acrescenta `vagas` -- ja qualificado, so segue conversando.
    with caplog.at_level(logging.INFO):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA, extracao=Extracao(vagas=2)),
            outbound,
            resumidor_fake(),
            contador_fake(),
        )

    registros_do_segundo_turno = caplog.records
    assert sum(1 for r in registros_do_segundo_turno if "lead.qualificado" in r.getMessage()) == 0


async def test_turno_que_nao_grava_estado_nao_avalia_transicao(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """FORA_DE_ESCOPO: `gravar_estado` devolve None, e nao ha depois."""
    classificador = classificador_fake(Intencao.FORA_DE_ESCOPO, extracao=_EXTRACAO_QUE_QUALIFICA)
    outbound = outbound_fake()

    with caplog.at_level(logging.INFO):
        await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert not any("lead.qualificado" in registro.getMessage() for registro in caplog.records)

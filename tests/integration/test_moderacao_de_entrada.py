import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import CANAL_AGENTE, CONVERSA_AGENTE, OutboundFake  # type: ignore[import-not-found]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_rajada import gravar  # type: ignore[import-not-found]
from test_turno_optout import _OutboundQueOptaNoMeio  # type: ignore[import-not-found]

from mobia.app.config import MODELO_SEM_CHAMADA
from mobia.domain.agente.turno import SUBAGENTE_MODERACAO
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.status import MessageStatus
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import (
    KIND_DA_RECUSA_DE_ENTRADA,
    TEXTO_DA_RECUSA_DE_ENTRADA,
    Direcao,
    ModeracaoIndisponivel,
)
from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRetentavel
from mobia.domain.outbound.repositorio import kinds_reservados
from mobia.infra.db import get_sessionmaker


def _espionar_montagem(monkeypatch: object) -> list:
    """Substitui `montar_contexto` no modulo do turno por um espiao que delega.

    Delega no original em vez de substituir de verdade: quem usa o espiao no
    caminho liberado continua exercitando a montagem de contexto real, e nao
    so registrando que ela "deveria" ter rodado.

    Devolve uma lista de 1 item (mutavel por referencia) em vez de um bool
    solto porque o espiao fecha sobre ela de dentro de uma corrotina --
    `nonlocal` exigiria a variavel na mesma funcao, e aqui a variavel precisa
    sair para o corpo do teste.
    """
    from mobia.domain.agente import turno as modulo_do_turno

    chamadas: list = []
    original = modulo_do_turno.montar_contexto

    async def espiao(*args: object, **kwargs: object) -> object:
        chamadas.append(True)
        return await original(*args, **kwargs)

    monkeypatch.setattr(modulo_do_turno, "montar_contexto", espiao)
    return chamadas


async def test_entrada_bloqueada_entrega_recusa_e_nao_chama_o_modelo(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    monkeypatch: object,
) -> None:
    """Bloquear antes de montar contexto economiza o turno inteiro.

    `montar_contexto` nao e barato: ele dispara `resumidor` a cada ~40
    mensagens e `contador` quando a estimativa chega perto do teto, e as duas
    sao chamadas pagas. Um refactor que mova a moderacao para depois passa a
    pagar resumo em mensagem bloqueada, em silencio.

    O espiao existe porque asserir por efeito colateral nao pega isso: com uma
    mensagem semeada, `montar_contexto` nao custa nada observavel, e o teste
    passava com o bloco movido para depois dele.
    """
    chamadas_de_montagem = _espionar_montagem(monkeypatch)
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake(bloqueia_entrada=True)

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), moderador
    )

    assert resultado == "respondido"
    assert chamadas_de_montagem == []
    assert classificador.chamadas == 0
    # `in` e nao `==` desde a TEC-139: em conversa nova a entrega carrega o
    # prefixo de identificacao antes deste texto -- este teste so precisa
    # saber que a recusa saiu, nao que ela veio sozinha.
    assert TEXTO_DA_RECUSA_DE_ENTRADA in outbound.entregues[-1]


async def test_entrada_liberada_segue_o_turno(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    monkeypatch: object,
) -> None:
    """O espiao aqui e o contraponto do teste acima.

    Sem ele, um mutante que parasse de montar contexto sempre (nao so no
    caminho bloqueado) so seria pego indiretamente -- via NameError em
    `contexto` na chamada ao classificador, que e um acidente de escopo, nao
    uma assercao sobre a regra. Este teste torna "o caminho liberado monta
    contexto de verdade" uma garantia explicita.
    """
    chamadas_de_montagem = _espionar_montagem(monkeypatch)
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), moderador
    )

    assert resultado == "respondido"
    assert chamadas_de_montagem == [True]
    assert classificador.chamadas == 1
    assert moderador.entradas == 1


async def test_moderador_indisponivel_na_entrada_deixa_o_turno_seguir(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Falha aberta na entrada, e a assimetria e deliberada.

    A fala do lead ja esta cifrada no banco -- a ingestao a gravou antes de o
    worker existir. Negar atendimento a lead legitimo porque um servico caiu
    pune o inocente por um problema alheio a conversa dele.
    """
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake(erro_na_entrada=ModeracaoIndisponivel("TimeoutError"))

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), moderador
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 1


async def test_a_entrada_e_moderada_na_direcao_certa(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Moderar a fala do lead com o criterio da saida bloquearia reclamacao
    legitima, que e o falso positivo mais caro deste sistema.
    """
    classificador = classificador_fake()
    moderador = moderador_fake()

    await rodar_turno(
        session, classificador, outbound_fake(), resumidor_fake(), contador_fake(), moderador
    )

    assert Direcao.ENTRADA in moderador.direcoes


async def test_recusa_fora_da_janela_expira_e_nao_vira_recusa_permanente(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """A mesma excecao tem de significar a mesma coisa nos dois caminhos.

    No caminho principal `EnvioForaDaJanela` vira `outbound.fora_da_janela` em
    `warning` e desfecho `"expirado"`; aqui ela caia junto com `EnvioRecusado`,
    virava `error` e desfecho `"sem_resposta"`. Janela de 24h fechada nao e
    recusa permanente -- e o `Literal` de `ResultadoDoTurno` existe justamente
    para essa distincao nao se perder. Classificada errado, ela acorda o alerta
    de `error` por uma janela que so fechou, e "expirado" some das contagens
    exatamente nas mensagens bloqueadas.
    """
    outbound = outbound_fake(EnvioForaDaJanela("131047"))
    moderador = moderador_fake(bloqueia_entrada=True)

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session,
            classificador_fake(),
            outbound,
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert resultado == "expirado"
    assert "outbound.fora_da_janela" in caplog.text
    assert "moderacao.texto_fixo_nao_entregue" not in caplog.text


async def test_a_entrega_da_recusa_nao_finge_lacuna_de_preco(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """Entrada bloqueada nao chama modelo nenhum, e a telemetria tem de dizer isso.

    Com `model=""` o custo saia None e o recorder emitia
    `telemetry.unknown_model`, cujo proposito documentado e "None aparece como
    lacuna e alguem conserta". Toda entrada bloqueada abriria um chamado para
    uma lacuna que nao existe -- e o alarme falso que se repete e o que ensina
    a ignorar o alarme. `MODELO_SEM_CHAMADA` esta na tabela de precos a custo
    zero, que aqui e o custo exato: nao houve chamada.
    """
    moderador = moderador_fake(bloqueia_entrada=True)

    with caplog.at_level(logging.WARNING):
        await rodar_turno(
            session,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert "telemetry.unknown_model" not in caplog.text
    linha = (
        await session.execute(
            select(MessageTelemetry).where(MessageTelemetry.subagent == SUBAGENTE_MODERACAO)
        )
    ).scalar_one()
    assert linha.model == MODELO_SEM_CHAMADA
    assert linha.cost_usd == Decimal("0")


async def test_a_fala_bloqueada_recebe_marca_na_linha(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Criterio de aceite da TEC-236: distinguivel sem reinterpretar texto.

    Antes desta card o bloqueio nao deixava rastro nenhum na linha -- ela
    fechava em PROCESSED como qualquer outra, e nada em `messages` dizia que a
    moderacao a tinha recusado.
    """
    from mobia.domain.messages.models import Message

    moderador = moderador_fake(bloqueia_entrada=True)

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
    )

    assert resultado == "respondido"
    linha = (
        await session.scalars(
            select(Message).where(Message.direction == "INBOUND").order_by(Message.created_at)
        )
    ).all()[-1]
    await session.refresh(linha)
    assert linha.bloqueada_em is not None
    # E o `status` nao se mexeu. Quem o escreve e `process_message`, pelo
    # desfecho do turno -- `executar_turno` nunca toca nele. As duas colunas
    # respondem perguntas diferentes e sao escritas por camadas diferentes, que
    # e exatamente o argumento para a marca ser paralela e nao um
    # `MessageStatus` novo (ver o comentario de `bloqueada_em` em
    # `messages/models.py`).
    assert linha.status == MessageStatus.PROCESSING


async def test_a_marca_e_gravada_mesmo_quando_a_recusa_nao_e_entregue(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """A ordem entre marcar e entregar, provada pelo caso que a expoe.

    `_entregar_texto_fixo` tem tres saidas que nao entregam nada, e duas delas
    fecham a linha em PROCESSED -- terminal, ninguem volta nela. Marcar depois
    da entrega deixaria a fala bloqueada sem marca exatamente nesses casos, e
    ela entraria no contexto do turno seguinte.
    """
    from mobia.domain.messages.models import Message

    outbound = outbound_fake(EnvioForaDaJanela("131047"))
    moderador = moderador_fake(bloqueia_entrada=True)

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session,
            classificador_fake(),
            outbound,
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert resultado == "expirado"
    linha = (
        await session.scalars(
            select(Message).where(Message.direction == "INBOUND").order_by(Message.created_at)
        )
    ).all()[-1]
    await session.refresh(linha)
    assert linha.bloqueada_em is not None, "a recusa nao saiu, mas a fala foi bloqueada do mesmo"


async def test_a_recusa_de_entrada_vira_linha_de_auditoria(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O terceiro criterio de aceite da TEC-142: timestamp, conversa e
    categoria. O log nao servia -- rotaciona, nao traz a conversa, e o motivo
    binario nao distingue discriminacao de ameaca.
    """
    from mobia.domain.moderacao.models import ModerationEvent

    await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True, categoria_de_entrada="DISCRIMINACAO"),
    )

    evento = await session.scalar(select(ModerationEvent))
    assert evento is not None
    assert evento.direcao == "ENTRADA"
    assert evento.categoria == "DISCRIMINACAO"
    assert evento.conversation_key
    assert evento.created_at is not None


async def test_a_auditoria_nao_carrega_o_texto_julgado(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
    caplog,
) -> None:
    """O quarto criterio de aceite: o conteudo ofensivo nao aparece em claro.

    Checa as duas superficies de uma vez -- a linha de auditoria e o log --
    porque a regra vale para as duas e so uma delas tem teste hoje.
    """
    from mobia.domain.moderacao.models import ModerationEvent

    ofensivo = "queria um predio sem aquele tipo de gente que vem do norte"

    with caplog.at_level(logging.ERROR):
        await rodar_turno(
            session,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
            moderador_fake(bloqueia_entrada=True),
            texto=ofensivo,
        )

    evento = await session.scalar(select(ModerationEvent))
    assert evento is not None
    for valor in (evento.categoria, evento.direcao, evento.conversation_key):
        assert "tipo de gente" not in valor
    assert "tipo de gente" not in caplog.text


async def test_recusa_de_entrada_nao_encerra_o_atendimento(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Segundo criterio de aceite da TEC-142: a recusa nao encerra o atendimento.

    Dada uma recusa ja emitida na conversa, quando o lead informa um criterio
    legitimo (numero de quartos), o turno seguinte tem de seguir normalmente --
    classificador chamado, resposta entregue. A propriedade sai de graca do
    codigo hoje: nada em `executar_turno` olha para uma recusa passada da
    mesma conversa antes de decidir se roda o turno. Mas nenhum teste ate esta
    card exercitava dois turnos de verdade sobre a mesma conversa, e o
    caminho vizinho mais proximo (`test_fala_bloqueada_nao_entra_na_janela`,
    em `test_montagem.py`) prova so a metade dificil -- que a fala bloqueada
    nao envenena o contexto. Este teste existe para que a outra metade, a que
    ja sai de graca, nao deixe de sair em silencio se um refactor futuro
    passar a tratar recusa como fim de conversa.
    """
    outbound = outbound_fake()

    primeiro = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
    )

    assert primeiro == "respondido"
    # `in` e nao `==` pelo mesmo motivo do teste acima: e a primeira
    # mensagem da conversa, e desde a TEC-139 ela carrega o prefixo de
    # identificacao junto da recusa.
    assert TEXTO_DA_RECUSA_DE_ENTRADA in outbound.entregues[-1]

    classificador = classificador_fake()
    segundo = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
        texto="preciso de 3 quartos",
    )

    assert segundo == "respondido"
    assert classificador.chamadas == 1
    assert outbound.entregues[-1] != TEXTO_DA_RECUSA_DE_ENTRADA


async def test_bloqueada_com_pergunta_pendente_recusa_e_responde(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """TEC-295, D4. O xingamento e recusado; a pergunta anterior e respondida.

    Antes da TEC-128 o lead recebia as duas coisas, porque cada mensagem tinha
    o proprio turno. O debounce juntou os dois casos num turno so, e este teste
    e o que impede a pergunta legitima de morrer junto com a recusa.
    """
    # Irma mais antiga da rajada: nao bloqueada, sem resposta do agente ainda
    # -- e exatamente o que `ha_fala_pendente_antes` procura.
    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )

    outbound = outbound_fake()
    classificador = classificador_fake()
    moderador = moderador_fake(bloqueia_entrada=True)

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador,
        texto="xingamento qualquer",
    )

    assert resultado == "respondido"
    # O turno continuou: chamou o classificador e entregou uma SEGUNDA
    # mensagem, distinta da recusa -- nao so um "respondido" que na verdade
    # so carrega a recusa.
    assert classificador.chamadas == 1
    assert len(outbound.entregues) == 2
    assert TEXTO_DA_RECUSA_DE_ENTRADA in outbound.entregues[0]
    assert TEXTO_DA_RECUSA_DE_ENTRADA not in outbound.entregues[1]

    # Ruling R6: as duas entregas tem de reservar sob kinds DIFERENTES em
    # `outbound_dispatches`. Com o mesmo kind a segunda seria suprimida como
    # reentrega da primeira -- em silencio, sem essa asserta ninguem veria a
    # colisao voltar.
    carregadora = (
        await session.scalars(
            select(Message).where(Message.direction == "INBOUND").order_by(Message.created_at)
        )
    ).all()[-1]
    reservados = await kinds_reservados(get_sessionmaker(), message_id=carregadora.id)
    assert reservados == {KIND_DA_RECUSA_DE_ENTRADA, KIND_DA_RESPOSTA}


class _OutboundQueFalhaDepoisDaRecusa(OutboundFake):
    """Entrega a recusa e falha na resposta -- a janela exata da TEC-298.

    `EnvioRetentavel` e nao uma excecao qualquer: e a que `GuardedOutbound.send`
    intercepta para liberar as reservas do GRUPO. O kind da recusa nao esta em
    `_GRUPOS`, entao a reserva dela sobrevive -- que e justamente o estado que
    a retentativa vai encontrar.
    """

    async def _deliver(self, message_id, kind, payload) -> None:
        if kind == KIND_DA_RECUSA_DE_ENTRADA:
            await super()._deliver(message_id, kind, payload)
            return
        raise EnvioRetentavel("a resposta nao saiu")


async def test_retentativa_apos_recusa_entregue_responde_a_pendente(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, D1 e D3. A rota de recuperacao da TEC-295 sobrevive ao reprocessamento.

    Nao usa `rodar_turno` porque ele semeia uma entrada NOVA a cada chamada, e
    aqui as duas passadas tem de rodar sobre a MESMA linha -- e o que o sweeper
    faz.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    # Primeira passada: a recusa sai, a resposta falha.
    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=falha,
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )
    assert falha.entregues == [TEXTO_DA_RECUSA_DE_ENTRADA]

    # Segunda passada: mesma linha, outbound sao. E o que o sweeper faz.
    segundo_outbound = OutboundFake(get_sessionmaker())
    classificador = classificador_fake()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=segundo_outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )

    assert resultado == "respondido"
    # O turno continuou: chamou o classificador e entregou a resposta.
    assert classificador.chamadas == 1
    # A recusa NAO sai de novo -- a reserva dela sobreviveu e a suprime.
    assert TEXTO_DA_RECUSA_DE_ENTRADA not in segundo_outbound.entregues
    assert len(segundo_outbound.entregues) == 1
    # Os dois kinds reservados: a recusa da primeira passada, a resposta desta.
    reservados = await kinds_reservados(get_sessionmaker(), message_id=carregadora.id)
    assert reservados == {KIND_DA_RECUSA_DE_ENTRADA, KIND_DA_RESPOSTA}


async def test_retentativa_sem_pendencia_continua_so_recusando(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, D1+D7. Sem pendencia, o teto novo nao inventa pendencia onde nao ha.

    Este teste NAO prova a D3 (a continuacao apos `"reentrega_suprimida"`):
    no cenario sem pendencia, `if desfecho_da_recusa not in (...)` cai direto
    em `if not tem_pendencia`, que devolve o mesmo `"reentrega_suprimida"` que
    o guard antigo (`!= "respondido"`) devolveria sozinho -- por construcao,
    nenhum teste distingue os dois guards aqui. Quem trava a D3 e
    `test_retentativa_apos_recusa_entregue_responde_a_pendente`. O que este
    teste trava e outra coisa: que `ha_fala_pendente_antes` com o
    `teto_do_agente` novo continua dizendo False quando nao ha pergunta
    pendente, e que a garantia da TEC-233 (nao responder ao historico sem
    pendencia) vale tambem numa retentativa.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    # Sem pendencia a primeira passada ja retorna na recusa, sem chegar na
    # entrega da resposta -- entao nao ha excecao a capturar aqui.
    primeiro = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=falha,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )
    assert primeiro == "respondido"

    segundo_outbound = OutboundFake(get_sessionmaker())
    classificador = classificador_fake()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=segundo_outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )

    assert resultado == "reentrega_suprimida"
    assert classificador.chamadas == 0, "sem pendencia, o modelo nao e chamado"
    assert segundo_outbound.entregues == []


async def test_bloqueada_sem_nada_pendente_so_recusa(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """A condicao da D4. Sem ela, um turno bloqueado isolado responderia ao
    historico anterior -- o engajamento que a TEC-233 recusou de proposito."""
    outbound = outbound_fake()

    # Primeiro turno: pergunta legitima, respondida normalmente -- fica
    # historico na conversa, mas NADA pendente (a ultima fala do agente e
    # depois dela).
    primeiro = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
        texto="tem apartamento de 2 quartos?",
    )
    assert primeiro == "respondido"

    # Segundo turno: bloqueado pela moderacao, sem nenhuma fala pendente.
    classificador = classificador_fake()
    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
        texto="xingamento qualquer",
    )

    assert resultado == "respondido"
    # O turno NAO continuou: sem pendencia, continuar responderia ao
    # historico antigo -- o engajamento indevido que a D4 existe para barrar.
    assert classificador.chamadas == 0
    assert len(outbound.entregues) == 2
    assert TEXTO_DA_RECUSA_DE_ENTRADA not in outbound.entregues[0]
    assert TEXTO_DA_RECUSA_DE_ENTRADA in outbound.entregues[-1]


async def test_recusa_barrada_por_optout_concorrente_nao_responde(
    session: AsyncSession,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """A primeira ressalva da D4: se a recusa nao chegou ao lead, a resposta
    tambem nao vai -- mesmo com pergunta pendente.

    A pergunta pendente e semeada de proposito (`gravar`, como em
    `test_bloqueada_com_pergunta_pendente_recusa_e_responde`). Sem ela,
    `tem_pendencia` da False e o SEGUNDO guard (`if not tem_pendencia:
    return`) ja barraria a continuacao sozinho -- este teste passaria mesmo
    que o guard desta ressalva (`if desfecho_da_recusa != "respondido":
    return`) fosse apagado, e nao provaria nada sobre ele. Com a pendencia,
    so o guard desta ressalva impede a continuacao de tentar responder a
    quem acabou de pedir para sair.
    """
    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )

    outbound = _OutboundQueOptaNoMeio(
        get_sessionmaker(), channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE
    )

    resultado = await rodar_turno(
        session,
        None,  # classificador: o guard barra antes de qualquer chamada
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
        texto="xingamento qualquer",
    )

    assert resultado == "bloqueado_por_optout"
    assert resultado != "reentrega_suprimida"
    assert outbound.entregues == [], "a guarda nunca chega a chamar _deliver"


async def test_recusa_ja_reservada_nao_alarma_como_dado_sumido(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
    caplog,
) -> None:
    """TEC-298, D4. A supressao da recusa nao e perda, e o log para de dizer que e.

    `error` e o nivel que o alerta observa -- o "alarme de dado sumido". Dispara-lo
    sobre uma recusa que a passada anterior entregou acorda alguem a toa, e ainda
    por cima no meio de um caso em que o que se perdeu foi OUTRA coisa.

    `warning` e nao `info` de proposito: a reserva sobrevivente e evidencia forte
    de entrega, nao prova. Ela tambem sobrevive se o worker morreu entre o commit
    da reserva e o `_deliver`, ou se o proprio `_liberar` falhou.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=falha,
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )

    with caplog.at_level(logging.INFO):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=OutboundFake(get_sessionmaker()),
            moderador=moderador_fake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )

    erros = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not [r for r in erros if "turno.reentrega_suprimida" in r.getMessage()], (
        "a recusa suprimida nao pode acordar o alarme de dado sumido"
    )
    avisos = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "turno.recusa_ja_reservada" in r.getMessage()
    ]
    assert len(avisos) == 1


async def test_retentativa_nao_repaga_a_moderacao_nem_duplica_a_auditoria(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, D5. `bloqueada_em` ja e o veredito persistido do caso bloqueado.

    A retentativa nao pode pagar de novo por uma fala que ja foi julgada, nem
    gravar uma segunda linha de auditoria para a mesma recusa -- ver a Emenda
    E-04 da RN-04.5.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    moderador = moderador_fake(bloqueia_entrada=True)
    falha = _OutboundQueFalhaDepoisDaRecusa(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=carregadora,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=falha,
            moderador=moderador,
            agendador=AgendadorNoop(),
        )
    assert moderador.entradas == 1

    segundo_moderador = moderador_fake(bloqueia_entrada=True)
    await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=OutboundFake(get_sessionmaker()),
        moderador=segundo_moderador,
        agendador=AgendadorNoop(),
    )

    assert segundo_moderador.entradas == 0, "a fala ja estava carimbada; nao se paga de novo"
    await session.commit()
    eventos = await session.scalar(
        select(func.count())
        .select_from(ModerationEvent)
        .where(ModerationEvent.message_id == carregadora.id)
    )
    assert eventos == 1, "uma fala recusada, uma linha -- Emenda E-04 da RN-04.5"


async def test_retentativa_apos_resposta_entregue_nao_reabre_pendencia(
    session: AsyncSession,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_entrada,
) -> None:
    """TEC-298, revisao final. A composicao D1+D3 reabre o alarme pelo kind da RESPOSTA.

    Cenario: numa passada anterior a recusa E a resposta a pendencia ja foram
    entregues (o caminho que `test_bloqueada_com_pergunta_pendente_recusa_e_responde`
    prova para uma passada isolada), e o turno morre DEPOIS disso -- crash,
    job_timeout, UPDATE ... PROCESSED caindo. Numa retentativa sobre a MESMA
    linha, `veredito_ja_registrado` curto-circuita a moderacao (correto), mas
    `teto_da_recusa` e o `created_at` da RESERVA da recusa -- que e anterior a
    resposta, gravada DEPOIS dela. Com esse teto, `ha_fala_pendente_antes`
    enxerga a fronteira de ANTES da recusa e ignora que a resposta ja saiu, e
    `tem_pendencia` volta a `True` sobre uma pergunta que ja foi respondida.

    Sem a guarda que consulta `kinds_reservados` por `KIND_DA_RESPOSTA`
    aconteceriam duas coisas: (a) a continuacao pagaria o modelo de novo para
    responder ao que ja foi respondido, e o `send` seria suprimido pela
    reserva existente -- reabrindo, pelo kind da RESPOSTA, o mesmo alarme
    falso que a D4 fechou pelo kind da RECUSA; e (b) pior que o alarme, se a
    geracao nova quebrasse em duas mensagens onde a anterior coube numa,
    `reply` seria suprimido e `reply_2` sairia sozinho -- a metade orfa que
    `domain/outbound/kinds.py` descreve como corrupcao silenciosa. Este teste
    trava que a guarda nova impede as duas: o classificador nao e chamado e
    nada novo e entregue.
    """
    from mobia.domain.agente.turno import executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop

    await gravar(
        session,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        texto="tem apartamento de 2 quartos?",
    )
    carregadora = await semear_entrada(session, texto="xingamento qualquer")

    # Passada 1: a pendencia ja existe quando o turno comeca, entao recusa e
    # resposta saem na MESMA passada -- o outbound e o `OutboundFake` normal,
    # sem falha nenhuma.
    primeiro_outbound = OutboundFake(get_sessionmaker())
    primeiro = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=primeiro_outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )
    assert primeiro == "respondido"
    assert len(primeiro_outbound.entregues) == 2

    # Passada 2: mesma linha, como se o turno tivesse morrido depois da
    # entrega acima. A recusa ja esta reservada (reentrega suprimida) e a
    # resposta tambem -- a guarda nova tem de reconhecer isso e nao tentar
    # responder de novo.
    classificador = classificador_fake()
    segundo_outbound = OutboundFake(get_sessionmaker())
    segundo = await executar_turno(
        get_sessionmaker(),
        message=carregadora,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=segundo_outbound,
        moderador=moderador_fake(bloqueia_entrada=True),
        agendador=AgendadorNoop(),
    )

    assert segundo == "reentrega_suprimida"
    assert classificador.chamadas == 0, (
        "a resposta ja foi entregue; nao ha pendencia para responder"
    )
    assert segundo_outbound.entregues == []

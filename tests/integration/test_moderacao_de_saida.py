from decimal import Decimal

import pytest
from conftest import CANAL_AGENTE, CONVERSA_AGENTE, RESPOSTA_DO_CLASSIFICADOR_FAKE
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.moderacao.port import TEXTO_NEUTRO_DE_SAIDA, Direcao, ModeracaoIndisponivel
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker


async def _conversa_ja_existe(session: AsyncSession) -> None:
    """Semeia uma entrada anterior para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Mesmo padrao de `_conversa_ja_existe` em `test_apresentacao_no_turno.py`,
    copiado e nao importado -- os arquivos de integracao deste repo sao
    autocontidos. Os testes que chamam isto provam a moderacao de saida, nao
    identificacao (que tem arquivo proprio, `test_identificacao_no_turno.py`).
    Sem isto, `banco_limpo` (autouse) deixa cada teste comecar em silencio
    total, `e_conversa_nova` devolveria True e o prefixo de identificacao
    quebraria a igualdade exata contra `TEXTO_NEUTRO_DE_SAIDA` que estes
    testes provam.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def test_saida_bloqueada_entrega_o_texto_neutro(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    await _conversa_ja_existe(session)
    outbound = outbound_fake()
    moderador = moderador_fake(bloqueia_saida=True)

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador,
    )

    assert resultado == "respondido"
    assert outbound.entregues[-1] == TEXTO_NEUTRO_DE_SAIDA


async def test_o_recorder_grava_o_texto_entregue_e_nao_o_barrado(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Este teste e a razao de a moderacao viver no turno e nao num decorador
    do outbound.

    `record_agent_message` grava o texto entregue. Um decorador que
    substituisse por dentro faria o recorder gravar o texto **barrado**: o
    historico do lead passaria a conter uma fala que ele nunca viu, que entra
    no contexto do turno seguinte e depois e dobrada permanentemente no resumo.
    Sem este teste, alguem move a moderacao para um wrapper e reintroduz a fala
    fantasma.
    """
    await _conversa_ja_existe(session)
    moderador = moderador_fake(bloqueia_saida=True)

    await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
    )

    linhas = (
        (await session.execute(select(Message).where(Message.role == MessageRole.AGENTE)))
        .scalars()
        .all()
    )
    textos = [decrypt(linha.text_body, aad_de(linha.id, "text_body")) for linha in linhas]
    assert TEXTO_NEUTRO_DE_SAIDA in textos
    assert RESPOSTA_DO_CLASSIFICADOR_FAKE not in textos


async def test_moderador_indisponivel_na_saida_nao_entrega(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Falha fechada na saida, oposta a da entrada.

    Entregar texto nao moderado e exatamente o risco que este subsistema
    existe para fechar, e o custo recai sobre a reputacao da imobiliaria, em
    publico. A excecao propaga: a linha vira FAILED com `attempts` e o sweeper
    retenta.
    """
    outbound = outbound_fake()
    moderador = moderador_fake(erro_na_saida=ModeracaoIndisponivel("TimeoutError"))

    with pytest.raises(ModeracaoIndisponivel):
        await rodar_turno(
            session,
            classificador_fake(),
            outbound,
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert outbound.entregues == []


async def test_a_saida_e_moderada_uma_vez_por_turno(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """So um texto sai por turno, entao so um e julgado. No caminho ambiguo a
    resposta da chamada 1 e descartada e so a pergunta e entregue.
    """
    moderador = moderador_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador,
    )

    assert moderador.saidas == 1
    assert Direcao.SAIDA in moderador.direcoes


async def test_saida_bloqueada_no_caminho_ambiguo_nao_marca_a_desambiguacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Bloquear a pergunta e, para o marcador, o mesmo que um 5xx da Meta.

    `marcar_desambiguacao` afirma "eu ja perguntei", e a docstring dela diz por
    que isso so pode ser gravado depois de a pergunta chegar: escrito antes, um
    5xx queimaria a unica chance do episodio e o lead ficaria em INDEFINIDA sem
    ninguem ter perguntado nada. A saida bloqueada e indistinguivel disso no
    unico aspecto que importa -- a pergunta nao chegou; o que chegou foi
    `TEXTO_NEUTRO_DE_SAIDA`, que nao pergunta nada. Marcar aqui gastaria a
    pergunta do episodio inteiro numa entrega que nunca a fez.

    Este e tambem o unico teste que exercita moderacao no caminho ambiguo: com
    a confianca padrao do duble (0,91) nada aqui passava por `desambiguar`, e
    era esse ponto cego que mantinha o defeito vivo. Por isso a contagem de
    `saidas` tambem e afirmada -- so a pergunta e julgada, nao as duas.
    """
    await _conversa_ja_existe(session)
    classificador = classificador_fake(confianca=Decimal("0.5"))
    outbound = outbound_fake()
    moderador = moderador_fake(bloqueia_saida=True)

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador,
    )

    assert resultado == "respondido"
    assert classificador.desambiguacoes == 1, "o caminho ambiguo tem de ter sido exercitado"
    assert outbound.entregues[-1] == TEXTO_NEUTRO_DE_SAIDA
    assert moderador.saidas == 1, "so o texto que sai e julgado, nao os dois candidatos"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL_AGENTE, CONVERSA_AGENTE)
    assert gravada is not None
    assert gravada.desambiguado_em is None, (
        "a pergunta nao chegou ao lead -- o episodio ainda tem direito a ela"
    )


async def test_entrega_parcial_nao_marca_a_desambiguacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """TEC-273, D5. A marca so entra quando a pergunta chegou inteira.

    Irmao de `test_saida_bloqueada_no_caminho_ambiguo_nao_marca_a_desambiguacao`,
    pelo quarto ramo da mesma guarda. `entrega_parcial` nao diz ONDE dentro do
    texto a quebra caiu: a pergunta do desambiguador pode ter saido inteira,
    pela metade, ou nem ter existido na parte que o lead recebeu. Marcar aqui
    gastaria a unica pergunta do episodio numa entrega que talvez nunca a
    tenha feito, e o lead ficaria em INDEFINIDA sem ninguem ter perguntado --
    o MESMO dano que `saida_bloqueada` e `citacao_bloqueada` ja evitam.

    E o argumento que a TEC-140 escreveu para `marcar_perguntados`, que tem as
    quatro condicoes. Esta guarda tinha tres ate a TEC-273.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA
    from mobia.domain.outbound.port import EnvioRecusado

    await _conversa_ja_existe(session)

    # `confianca=0.5` e o que leva o turno ao caminho ambiguo -- com o padrao
    # do duble (0,91) nada passa por `desambiguar`, e era esse ponto cego que
    # mantinha o defeito irmao vivo (ver o docstring do teste ao lado).
    # A pergunta longa e o que a faz quebrar em duas partes.
    classificador = classificador_fake(
        confianca=Decimal("0.5"),
        pergunta="Me conta: " + "x" * 400 + " ou " + "y" * 400 + "?",
    )

    class _RecusaAParte2(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id, kind, payload) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRecusado("http 400")
            await super()._deliver(message_id, kind, payload)

    resultado = await rodar_turno(
        session,
        classificador,
        _RecusaAParte2(get_sessionmaker()),
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert classificador.desambiguacoes == 1, "o caminho ambiguo tem de ter sido exercitado"
    # "respondido" e o resultado CERTO aqui, nao um sintoma do defeito: uma
    # `EnvioRecusado` na segunda parte apos a primeira ja ter saido e o mesmo
    # caso que `test_segunda_parte_recusada_nao_apaga_a_primeira_ja_entregue`
    # (test_formato_no_turno.py) trava como "respondido" por desenho -- a
    # primeira parte chegou, entao nao e turno mudo. O que este teste prova
    # nao e o valor de `resultado`, e sim que a marca abaixo fica de fora.
    assert resultado == "respondido"

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL_AGENTE, CONVERSA_AGENTE)
    assert gravada is not None
    assert gravada.desambiguado_em is None, (
        "a pergunta pode ter ficado na parte que nao saiu -- o episodio ainda tem direito a ela"
    )


async def test_moderador_fora_do_ar_nas_duas_pontas_paga_o_turno_e_nao_entrega(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O cenario operacional real: o provedor cai, e cai para as duas pontas.

    Ha teste de erro so na entrada e teste de erro so na saida; nenhum roda os
    dois, que e a unica forma como a indisponibilidade de fato acontece. O
    comportamento composto e a soma das duas escolhas assimetricas, e o custo
    dele precisa estar escrito em algum lugar:

    a entrada falha **aberta**, entao o turno segue -- monta contexto (que
    pode disparar `resumidor` e `contador`) e paga `classificar`; a saida falha
    **fechada**, entao a excecao propaga e nada e entregue. O turno paga a
    conta inteira e o lead nao recebe nada. Pior: a linha vira FAILED, o
    sweeper reenfileira, e cada retentativa paga tudo de novo ate
    `sweep_max_attempts` -- cinco turnos pagos por mensagem, terminando em
    silencio se o moderador nao voltar. E consequencia defensavel de "a saida
    fecha", nao acidente, mas e o preco da indisponibilidade prolongada e esta
    declarado como lacuna no README.
    """
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake(
        erro_na_entrada=ModeracaoIndisponivel("TimeoutError"),
        erro_na_saida=ModeracaoIndisponivel("TimeoutError"),
    )

    with pytest.raises(ModeracaoIndisponivel):
        await rodar_turno(
            session,
            classificador,
            outbound,
            resumidor_fake(),
            contador_fake(),
            moderador,
        )

    assert moderador.entradas == 1, "a entrada foi tentada, e a falha dela nao parou o turno"
    assert classificador.chamadas == 1, "falha aberta na entrada custa a chamada paga"
    assert moderador.saidas == 1
    assert outbound.entregues == [], "falha fechada na saida: nada sai sem ter sido moderado"


async def test_o_bloqueio_de_saida_vira_linha_de_auditoria(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """A card fala da recusa de entrada; o registro cobre as duas pontas
    porque o que distingue e a coluna `categoria`, nao a existencia da linha.
    Um bloqueio de saida e o risco reputacional da RN-B04 tendo acontecido.
    """
    from mobia.domain.moderacao.models import ModerationEvent

    await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_saida=True, categoria_de_saida="NEGOCIACAO"),
    )

    evento = await session.scalar(select(ModerationEvent))
    assert evento is not None
    assert evento.direcao == "SAIDA"
    assert evento.categoria == "NEGOCIACAO"

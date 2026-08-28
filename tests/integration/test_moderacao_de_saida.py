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


async def test_saida_bloqueada_entrega_o_texto_neutro(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
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

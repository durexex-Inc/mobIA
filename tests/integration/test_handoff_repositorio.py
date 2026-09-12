"""A deduplicacao do handoff: o que so o Postgres prova."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _linhas(session: AsyncSession) -> list[dict]:
    resultado = await session.execute(
        text(
            "SELECT gatilho, etiqueta, prioridade, status, gatilhos_adicionais "
            "FROM handoffs ORDER BY criado_em"
        )
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_o_gatilho_quente_cria_com_etiqueta_e_prioridade(session: AsyncSession) -> None:
    criou = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    assert criou is True
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "lead-quente"
    assert linhas[0]["prioridade"] == "NORMAL"
    assert linhas[0]["status"] == "PENDENTE"


async def test_gatilho_repetido_nao_duplica_e_acumula(session: AsyncSession) -> None:
    """Cenario 2 do Gherkin."""
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    criou = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.VENDA_IMOVEL
    )
    await session.commit()
    assert criou is False
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilhos_adicionais"] == ["VENDA_IMOVEL"]
    # A etiqueta e do gatilho que criou, e nao muda.
    assert linhas[0]["etiqueta"] == "lead-quente"


async def test_pedido_de_humano_escala_a_prioridade_de_um_aberto(session: AsyncSession) -> None:
    """Emenda E-01 da RN-16.1, e o caso que a RN-04.6 exige."""
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.PEDIDO_DE_HUMANO
    )
    await session.commit()
    linhas = await _linhas(session)
    assert linhas[0]["prioridade"] == "ALTA"


async def test_a_prioridade_nunca_desce(session: AsyncSession) -> None:
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.PEDIDO_DE_HUMANO
    )
    await session.commit()
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    linhas = await _linhas(session)
    assert linhas[0]["prioridade"] == "ALTA"


async def test_conversas_diferentes_tem_handoffs_diferentes(session: AsyncSession) -> None:
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await registrar_handoff(
        session, channel=CANAL, conversation_key="5511900000000", gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    assert len(await _linhas(session)) == 2


async def test_duas_escritas_concorrentes_produzem_uma_linha(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """A corrida e prevista: `lead.esquentou` reemite para o mesmo lead.

    Duas sessoes de verdade, e nao duas chamadas em sequencia -- o que se quer
    provar e que quem arbitra e o indice parcial, nao a ordem do codigo.
    """

    async def escrever(gatilho: Gatilho) -> None:
        async with session_factory() as propria:
            await registrar_handoff(
                propria, channel=CANAL, conversation_key=CONVERSA, gatilho=gatilho
            )
            await propria.commit()

    await asyncio.gather(
        escrever(Gatilho.LEAD_QUENTE),
        escrever(Gatilho.VENDA_IMOVEL),
        return_exceptions=True,
    )
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 1

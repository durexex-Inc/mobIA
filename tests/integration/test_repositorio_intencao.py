from decimal import Decimal

from sqlalchemy import text as sql

from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao
from mobia.domain.agente.schemas import Intencao

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def gravar(session, intencao: Intencao, confianca: str) -> None:
    await gravar_intencao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=intencao,
        confianca=Decimal(confianca),
        modelo="claude-opus-5",
    )
    await session.commit()


async def test_intencao_faz_roundtrip(session) -> None:
    await gravar(session, Intencao.COMPRA, "0.91")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.COMPRA
    assert lida.confianca == Decimal("0.91")
    assert lida.modelo == "claude-opus-5"


async def test_gravar_de_novo_atualiza_em_vez_de_duplicar(session) -> None:
    """Uma conversa tem uma intencao corrente, nao um historico delas."""
    await gravar(session, Intencao.INDEFINIDA, "0.40")
    await gravar(session, Intencao.INVESTIMENTO, "0.88")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.INVESTIMENTO

    total = await session.scalar(sql("SELECT count(*) FROM conversation_intent"))
    assert total == 1


async def test_regravar_a_mesma_intencao_move_o_updated_at(session) -> None:
    """A classificacao acontece a cada turno, mesmo quando nada muda.

    Uma linha que nao e reescrita nao distingue "continua COMPRA" de "nao foi
    classificado neste turno".
    """
    await gravar(session, Intencao.COMPRA, "0.91")
    primeiro = await session.scalar(
        sql("SELECT updated_at FROM conversation_intent WHERE conversation_key = :k"),
        {"k": CONVERSA},
    )

    await gravar(session, Intencao.COMPRA, "0.93")
    segundo = await session.scalar(
        sql("SELECT updated_at FROM conversation_intent WHERE conversation_key = :k"),
        {"k": CONVERSA},
    )

    assert segundo > primeiro


async def test_conversa_sem_intencao_devolve_none(session) -> None:
    assert await ler_intencao(session, CANAL, "nunca-falou") is None

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.optout.models import EVENTO_OPT_OUT, EVENTO_REATIVACAO, OptoutEvent


async def test_evento_de_optout_grava_sem_autor_e_sem_motivo(session: AsyncSession) -> None:
    """O opt-out e ato do lead: nao ha autor humano nem justificativa.

    Inventar um autor sintetico mentiria sobre quem agiu.
    """
    message_id = uuid.uuid4()
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel="wa",
            conversation_key="5548999998888",
            evento=EVENTO_OPT_OUT,
            message_id=message_id,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    session.expire_all()

    gravado = (await session.execute(select(OptoutEvent))).scalar_one()

    assert (gravado.evento, gravado.message_id) == (EVENTO_OPT_OUT, message_id)
    assert gravado.autor is None
    assert gravado.motivo is None


async def test_reativacao_grava_autor_e_motivo_sem_mensagem(session: AsyncSession) -> None:
    """A reativacao e ato humano: tem autor e justificativa, e nao tem mensagem."""
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel="wa",
            conversation_key="5548999998888",
            evento=EVENTO_REATIVACAO,
            autor="Paulo M.",
            motivo="lead pediu por telefone para voltar a receber",
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    session.expire_all()

    gravado = (await session.execute(select(OptoutEvent))).scalar_one()

    assert (gravado.evento, gravado.autor) == (EVENTO_REATIVACAO, "Paulo M.")
    assert gravado.message_id is None

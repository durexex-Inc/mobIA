import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus

log = structlog.get_logger(__name__)

ACK_KIND = "ack"


async def claim_message(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """Reivindica a mensagem para processamento.

    PROCESSING esta entre os estados reivindicaveis de proposito: e o estado que
    um worker morto no meio do job deixa para tras, e e o que permite a retomada.
    Quem perde a corrida recebe rowcount 0 e sai como no-op.
    """
    resultado = await session.execute(
        update(Message)
        .where(Message.id == message_id, Message.status.in_(CLAIMABLE_STATUSES))
        .values(status=MessageStatus.PROCESSING)
    )
    return resultado.rowcount == 1


async def process_message(ctx: dict[str, Any], message_id: str) -> str:
    session_factory = ctx["session_factory"]
    outbound = ctx["outbound"]
    identifier = uuid.UUID(message_id)

    async with session_factory() as session:
        if not await claim_message(session, identifier):
            await session.rollback()
            log.info("message.skipped", message_id=message_id, reason="not_claimable")
            return "skipped"
        await session.commit()

    try:
        await outbound.send(identifier, ACK_KIND, {})

        fault = ctx.get("fault")
        if fault is not None:
            raise fault

        async with session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == identifier)
                .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
            )
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == identifier)
                .values(
                    status=MessageStatus.FAILED,
                    attempts=Message.attempts + 1,
                    last_error=f"{type(exc).__name__}: {exc}",
                )
            )
            await session.commit()
        log.warning("message.failed", message_id=message_id, error=str(exc))
        raise

    log.info("message.processed", message_id=message_id)
    return "processed"

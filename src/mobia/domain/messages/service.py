import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.status import MessageStatus
from mobia.infra.queue import enqueue_process_message

log = structlog.get_logger(__name__)


class IngestionService:
    """Persiste a mensagem recebida e so entao a enfileira.

    A ordem importa: a linha commitada no Postgres e a garantia de nao-perda.
    O enqueue e otimista e sua falha nao propaga -- a mensagem fica em RECEIVED
    e o sweeper (workers/jobs/sweep_stalled.py) a recupera.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: Any | None,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue

    async def ingest(
        self, parsed: list[ParsedMessage], channel: str = "whatsapp"
    ) -> list[uuid.UUID]:
        if not parsed:
            return []

        message_ids = await self._persist(parsed, channel)
        for message_id in message_ids:
            await self._try_enqueue(message_id)
        return message_ids

    async def _persist(self, parsed: list[ParsedMessage], channel: str) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            messages = [
                Message(
                    id=uuid.uuid4(),
                    channel=channel,
                    provider_message_id=item.provider_message_id,
                    sender_external_id=item.sender_external_id,
                    recipient_external_id=item.recipient_external_id,
                    content_type=item.content_type,
                    text_body=item.text_body,
                    raw_payload=item.raw_payload,
                    status=MessageStatus.RECEIVED,
                )
                for item in parsed
            ]
            session.add_all(messages)
            await session.commit()

        message_ids = [message.id for message in messages]
        log.info("message.received", message_ids=[str(i) for i in message_ids], channel=channel)
        return message_ids

    async def _try_enqueue(self, message_id: uuid.UUID) -> None:
        if self._queue is None:
            log.warning("enqueue.failed", message_id=str(message_id), reason="no_queue")
            return
        try:
            await enqueue_process_message(self._queue, message_id)
        except Exception as exc:
            log.warning(
                "enqueue.failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        async with self._session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == message_id)
                .values(status=MessageStatus.QUEUED, queued_at=datetime.now(UTC))
            )
            await session.commit()
        log.info("message.queued", message_id=str(message_id))

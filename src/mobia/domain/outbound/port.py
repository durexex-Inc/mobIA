import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.outbound.models import OutboundDispatch

log = structlog.get_logger(__name__)


class OutboundPort(Protocol):
    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool: ...


class GuardedOutbound:
    """Reserva antes de entregar.

    A linha em outbound_dispatches e commitada antes do efeito externo. Queda
    entre a reserva e a entrega perde aquele envio; queda depois nunca duplica.
    O criterio de aceite exige "nenhuma resposta duplicada" -- a troca e essa.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        async with self._session_factory() as session:
            session.add(OutboundDispatch(id=uuid.uuid4(), message_id=message_id, kind=kind))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                log.info(
                    "outbound.duplicate_suppressed",
                    message_id=str(message_id),
                    kind=kind,
                )
                return False

        await self._deliver(message_id, kind, payload)
        log.info("outbound.delivered", message_id=str(message_id), kind=kind)
        return True

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

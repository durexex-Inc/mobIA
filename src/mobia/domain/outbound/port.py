import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.outbound.models import OutboundDispatch

log = structlog.get_logger(__name__)


class OutboundPort(Protocol):
    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool: ...


class EnvioRetentavel(Exception):
    """Falha de envio que uma nova tentativa pode resolver -- rede, 5xx."""


class EnvioRecusado(Exception):
    """Falha de envio permanente -- 4xx. Retentar nao muda nada."""


class GuardedOutbound:
    """Reserva antes de entregar.

    A linha em outbound_dispatches e commitada antes do efeito externo. Queda
    entre a reserva e a entrega so perde aquele envio quando a falha e
    permanente (EnvioRecusado); queda depois nunca duplica. Falha retentavel
    (EnvioRetentavel) libera a reserva para a proxima tentativa poder entregar.
    O criterio de aceite exige "nenhuma resposta duplicada" -- a troca e essa,
    e continua valendo no caminho de sucesso e na falha permanente.
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

        try:
            await self._deliver(message_id, kind, payload)
        except EnvioRetentavel:
            # A reserva foi desenhada na TEC-122 para um ACK, e ali perder o
            # envio nao custava nada. Agora o que se perde e a resposta ao
            # lead: a reserva commitada faz o sweeper reenfileirar, o worker
            # reivindicar e a guarda responder "ja entreguei isso" -- e o lead
            # nunca recebe nada sobre aquele turno. Liberar inverte a troca
            # para uma duplicata possivel, que e visivel e recuperavel.
            await self._liberar(message_id, kind)
            raise

        log.info("outbound.delivered", message_id=str(message_id), kind=kind)
        return True

    async def _liberar(self, message_id: uuid.UUID, kind: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(OutboundDispatch).where(
                    OutboundDispatch.message_id == message_id,
                    OutboundDispatch.kind == kind,
                )
            )
            await session.commit()
        log.warning("outbound.reserva_liberada", message_id=str(message_id), kind=kind)

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

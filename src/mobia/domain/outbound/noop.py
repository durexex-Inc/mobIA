import uuid
from typing import Any

import structlog

from mobia.domain.outbound.port import GuardedOutbound

log = structlog.get_logger(__name__)


class NoopOutbound(GuardedOutbound):
    """Nao envia nada ao lead -- resposta so existe a partir de TEC-134.

    A reserva ja acontece porque e a infraestrutura que o criterio
    "nenhuma resposta duplicada" de TEC-122 exige.
    """

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        log.info("outbound.noop", message_id=str(message_id), kind=kind)

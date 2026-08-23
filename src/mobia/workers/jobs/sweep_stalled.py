import uuid
from typing import Any

import structlog
from sqlalchemy import text

from mobia.app.config import Settings, get_settings
from mobia.infra.queue import enqueue_process_message

log = structlog.get_logger(__name__)

_SELECIONAR_PARADAS = text(
    """
    UPDATE messages
       SET attempts = attempts + 1
     WHERE id IN (
        SELECT id
          FROM messages
         WHERE attempts < :max_attempts
           AND (
                (status = 'RECEIVED'
                 AND received_at < now() - make_interval(secs => :received_after))
             OR (status IN ('QUEUED', 'PROCESSING', 'FAILED')
                 AND COALESCE(queued_at, received_at)
                     < now() - make_interval(secs => :inflight_after))
           )
         ORDER BY received_at
         LIMIT :limite
           FOR UPDATE SKIP LOCKED
     )
 RETURNING id
    """
)


async def sweep_stalled(ctx: dict[str, Any], limite: int = 100) -> int:
    """Reenfileira mensagens que ficaram para tras.

    Tres janelas de perda: RECEIVED velho (o processo morreu entre o commit e o
    enqueue), QUEUED/PROCESSING velho (o worker morreu durante o job) e FAILED
    velho.

    FAILED entra na varredura porque o ARQ **nao** re-tenta excecao comum: em
    `arq/worker.py` so `Retry`, `RetryJob` e `CancelledError` reagendam; uma
    `Exception` qualquer marca `finish = True` e o `finish_job` apaga o job da
    fila. Sem o sweeper, uma falha transitoria perderia a mensagem para sempre.
    O teto `attempts < sweep_max_attempts` e o que limita o loop.

    O SKIP LOCKED permite varias instancias varrendo em paralelo sem colidir.
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    settings: Settings = ctx.get("settings") or get_settings()

    async with session_factory() as session:
        resultado = await session.execute(
            _SELECIONAR_PARADAS,
            {
                "max_attempts": settings.sweep_max_attempts,
                "received_after": settings.sweep_received_after_seconds,
                "inflight_after": settings.sweep_inflight_after_seconds,
                "limite": limite,
            },
        )
        ids: list[uuid.UUID] = [linha[0] for linha in resultado.fetchall()]
        await session.commit()

    for message_id in ids:
        await enqueue_process_message(redis, message_id)

    if ids:
        log.info("sweep.requeued", count=len(ids), message_ids=[str(i) for i in ids])
    return len(ids)

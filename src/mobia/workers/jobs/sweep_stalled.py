import uuid
from typing import Any

import structlog
from sqlalchemy import text, update

from mobia.app.config import Settings, get_settings
from mobia.domain.messages.models import Message
from mobia.infra.queue import enqueue_process_message

log = structlog.get_logger(__name__)

_SELECIONAR_PARADAS = text(
    """
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

    `attempts` so e incrementado para os ids que de fato entraram na fila, e
    cada enqueue e isolado num try/except. Contar tentativa sem ter enfileirado
    torna uma queda do Redis fatal: a varredura roda a cada 30s, o teto e 5, e
    em ~2,5 min de outage todas as mensagens em voo passariam do teto e seriam
    abandonadas -- justamente a janela que o sweeper existe para cobrir.

    A selecao, os enqueues e o incremento vivem na mesma transacao: os locks do
    `FOR UPDATE SKIP LOCKED` sao o que impede duas instancias de varrerem a
    mesma linha, e solta-los antes do incremento perderia essa exclusao.
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

        enfileiradas: list[uuid.UUID] = []
        for message_id in ids:
            try:
                novo = await enqueue_process_message(redis, message_id)
            except Exception as exc:
                log.warning(
                    "sweep.enqueue_failed",
                    message_id=str(message_id),
                    reason=type(exc).__name__,
                    detail=str(exc),
                )
                continue
            if not novo:
                log.info(
                    "sweep.enqueue_skipped",
                    message_id=str(message_id),
                    reason="job_ja_pendente",
                )
                continue
            enfileiradas.append(message_id)

        if enfileiradas:
            await session.execute(
                update(Message)
                .where(Message.id.in_(enfileiradas))
                .values(attempts=Message.attempts + 1)
            )
        await session.commit()

    if enfileiradas:
        log.info(
            "sweep.requeued",
            count=len(enfileiradas),
            message_ids=[str(i) for i in enfileiradas],
        )
    return len(enfileiradas)

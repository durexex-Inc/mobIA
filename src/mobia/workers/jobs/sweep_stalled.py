import uuid
from typing import Any

import structlog
from sqlalchemy import text

from mobia.app.config import Settings, get_settings
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
    O teto `attempts < sweep_max_attempts` e o que limita o loop: o re-sweep de
    FAILED e ancorado em `COALESCE(queued_at, received_at)` -- hora de enfileirar,
    nao de falhar -- entao uma mensagem que falha sempre volta a cada varredura,
    sem backoff. Com `attempts` contando so falha real de processamento, o
    orcamento sao 5 falhas de verdade e o laco fica limitado de forma sana.
    Backoff proprio (coluna `failed_at`) e TEC-209.

    O sweeper **nao** mexe em `attempts`. A coluna significa o que o nome diz --
    tentativa de processamento -- e quem a incrementa e o worker, no `except` do
    `process_message`, quando o processamento de fato falhou. Contar varredura
    como tentativa custava duas coisas. Uma: o UPDATE em lote rodava depois de
    os jobs ja estarem visiveis no Redis, travava as linhas em ordem de scan e
    bloqueava na primeira que um worker ja segurava, segurando as demais; o
    `claim_message`, que usa SKIP LOCKED, entao devolvia False para linhas
    perfeitamente reivindicaveis e o job saia como no-op -- consumido e perdido,
    e ja cobrado. Duas: com worker e sweeper contando, o orcamento anunciado de
    `sweep_max_attempts` valia na pratica metade.

    O que se perde e o sinal "o sweeper enfileirou algo que nunca chegou a um
    worker" -- que era exatamente o caso que o bug criava. Se ele voltar a fazer
    falta, o jeito honesto e uma coluna `sweep_enqueues` propria.

    Os locks da selecao sao soltos antes de qualquer I/O de rede: segurar lock de
    linha no Postgres enquanto se fala com o Redis e ruim por si so, e aqui teria
    um efeito concreto -- o `claim_message` do worker usa SKIP LOCKED, entao um
    job que chegasse durante a janela sairia como no-op em vez de processar. A
    exclusao entre sweepers concorrentes nao depende disso: quem perde a corrida
    do enqueue recebe False do ARQ e sai sem fazer nada.
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
        log.info(
            "sweep.requeued",
            count=len(enfileiradas),
            message_ids=[str(i) for i in enfileiradas],
        )
    return len(enfileiradas)

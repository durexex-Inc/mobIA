"""O job que redige o resumo do handoff e enfileira a notificacao do corretor. TEC-175, TEC-177."""

import uuid
from typing import Any

import structlog

from mobia.domain.handoff.geracao import gerar_resumo as _gerar
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.notificar import NOTIFICAR_JOB

log = structlog.get_logger(__name__)


async def gerar_resumo(ctx: dict[str, Any], handoff_id: str) -> str:
    """Gera o resumo de um handoff e enfileira a notificacao do corretor.

    O redator vem do `ctx` e nao e construido aqui, pelo mesmo motivo que o
    `classificador` e o `resumidor` do `process_message` vem de la: e o
    `startup` do worker que decide qual implementacao roda, e o teste troca a
    decisao sem tocar no job.

    **A notificacao e enfileirada INDEPENDENTE de `gravou`.** A D2 do desenho
    de TEC-177 manda avisar o corretor mesmo quando o resumo nao pode ser
    gerado -- e o handoff sem resumo e justamente o que mais precisa do
    aviso, nao um caso a pular. `notificar_corretor` (Task 4) monta um corpo
    proprio para o caso sem resumo; este job so decide SE enfileira, nunca
    o texto.
    """
    gravou = await _gerar(
        get_sessionmaker(), redator=ctx["redator"], handoff_id=uuid.UUID(handoff_id)
    )

    # Nao propaga: o resumo (ou a ausencia dele) ja esta gravado neste ponto,
    # e uma falha do Redis aqui perderia so a notificacao, nunca o trabalho
    # que `_gerar` ja fez. Mesmo molde do `_agendar_resumo` em
    # `domain/agente/turno.py`. O `_job_id` fixo por handoff evita duplicar a
    # notificacao se uma retentativa do ARQ rodar este job de novo para o
    # mesmo handoff.
    try:
        await ctx["redis"].enqueue_job(NOTIFICAR_JOB, handoff_id, _job_id=f"notificar:{handoff_id}")
    except Exception:
        log.warning("notificacao.nao_agendada", handoff_id=handoff_id, exc_info=True)

    return "gravado" if gravou else "sem_resumo"

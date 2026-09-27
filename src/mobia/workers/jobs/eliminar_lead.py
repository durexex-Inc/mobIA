"""O job que executa a eliminacao pedida pelo titular. TEC-207, D4.

`DELETE /leads/{lead_id}/dados-pessoais` enfileira este job com o
`solicitacao_id` que ela mesma registrou (ou reaproveitou) -- quem decide se
ha o que fazer e `eliminacao.anonimizar`, que e no-op e loga quando a
solicitacao ja nao esta ABERTA ou nao e de ELIMINACAO. Ver o docstring dela.
"""

import uuid
from typing import Any

import structlog
from arq import Retry

from mobia.domain.titular.eliminacao import AnonimizacaoSemLock, anonimizar

log = structlog.get_logger(__name__)

ELIMINAR_LEAD_JOB = "eliminar_lead"

# A espera antes da proxima tentativa quando a anonimizacao desistiu por
# lock. Um minuto e o bastante para a transacao tipica que segura o lock (um
# turno gravando score, outra anonimizacao) terminar, e com as tentativas
# padrao do ARQ a janela inteira fica em minutos -- esgotada, a solicitacao
# continua ABERTA e o sweep de retencao a cumpre antes do prazo.
SEGUNDOS_ATE_RETENTAR_SEM_LOCK = 60


async def eliminar_lead(ctx: dict[str, Any], solicitacao_id: str) -> None:
    """Roda `anonimizar` com o armazem que o `startup` do worker monta.

    `ctx["armazem"]`, e nao um armazem novo montado de `ctx["settings"]`: e o
    mesmo que o sweep de retencao usa, entao as duas portas de eliminacao
    apagam midia pelo mesmo objeto (revisao final, M3).

    `AnonimizacaoSemLock` vira `Retry` do ARQ (revisao final, M1): nada foi
    gravado, e a proxima tentativa tende a achar o bloqueador ja terminado.
    """
    try:
        await anonimizar(
            ctx["session_factory"],
            ctx["armazem"],
            solicitacao_id=uuid.UUID(solicitacao_id),
        )
    except AnonimizacaoSemLock as exc:
        log.info("titular.eliminacao_retentada_sem_lock", solicitacao_id=solicitacao_id)
        raise Retry(defer=SEGUNDOS_ATE_RETENTAR_SEM_LOCK) from exc

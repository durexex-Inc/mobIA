"""Quem pede o aviso de confirmacao, sem que o dominio saiba o que e ARQ.

TEC-170. Mesmo molde de `domain/handoff/agendador.py`: o dominio conhece so o
`Protocol`, e quem decide a implementacao e o `startup` do worker.

Nenhum caminho de producao chama `agendar` ainda -- quem ligar o agendamento a
conversa enfileira o job depois do commit de `confirmar()`.
"""

import uuid
from typing import Protocol

from arq.connections import ArqRedis

# Importada, nao redefinida: `confirmacao.py` (Task 3) e o dono da constante,
# porque e la que o job de verdade mora (`avisar_confirmacao`) -- duas copias
# do mesmo literal e exatamente a deriva que o docstring do job em
# `workers/jobs/avisar_confirmacao.py` avisa que quebra o enfileiramento.
from mobia.domain.agendamento.confirmacao import AVISAR_CONFIRMACAO_JOB as AVISAR_CONFIRMACAO_JOB


class AgendadorDeConfirmacaoPort(Protocol):
    async def agendar(self, agendamento_id: uuid.UUID) -> None: ...


class AgendadorDeConfirmacaoNoop:
    """Nao agenda nada. O default de todo teste que nao e sobre a confirmacao."""

    async def agendar(self, agendamento_id: uuid.UUID) -> None:
        return None


class AgendadorDeConfirmacaoArq:
    """Enfileira o job dos tres avisos.

    `_job_id` fixo por agendamento e o mesmo raciocinio de
    `domain/handoff/agendador.py`: impede que dois enqueues do mesmo
    agendamento mantenham dois jobs vivos ao mesmo tempo, nao protecao contra
    uma corrida que o codigo de hoje produza -- nenhum chamador ainda existe.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def agendar(self, agendamento_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            AVISAR_CONFIRMACAO_JOB,
            str(agendamento_id),
            _job_id=f"confirmacao:{agendamento_id}",
        )

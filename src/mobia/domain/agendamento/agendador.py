"""Quem pede o aviso de confirmacao, sem que o dominio saiba o que e ARQ.

TEC-170. Mesmo molde de `domain/handoff/agendador.py`: o dominio conhece so o
`Protocol`, e quem decide a implementacao e o `startup` do worker.

Desde a TEC-371 quem chama e o turno: `domain/agente/turno.py` enfileira o job
depois do commit de `confirmar()`, nessa ordem -- um job consumido antes do
commit nao encontraria a linha.
"""

import uuid
from typing import Protocol

from arq.connections import ArqRedis

# Importada, nao redefinida. `confirmacao.py` e o dono da constante porque
# guarda a funcao de dominio que o job chama -- o mesmo lugar que
# `NOTIFICAR_JOB` tem em `notificacao/envio.py`. O job fino mora em
# `workers/jobs/avisar_confirmacao.py`, e nenhum modulo de `domain/` importa
# de `workers/`. Duas copias do mesmo literal e exatamente a deriva que o
# docstring do job avisa que quebra o enfileiramento.
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

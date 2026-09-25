"""Quem pede os avisos do agendamento, sem que o dominio saiba o que e ARQ.

TEC-170 e TEC-372. Mesmo molde de `domain/handoff/agendador.py`: o dominio
conhece so o `Protocol`, e quem decide a implementacao e o `startup` do
worker.

Quem chama e o turno, desde a TEC-371: `domain/agente/turno.py` enfileira o
aviso **depois do commit** da transicao, nessa ordem -- um job consumido antes
do commit nao encontraria a linha.

**Uma porta com dois metodos, e nao duas portas.** A TEC-372 acrescentou o
cancelamento, e a alternativa era um segundo parametro em `executar_turno`.
Um parametro por tipo de aviso nao tem fim -- a proxima card do epico traria
o terceiro --, e a assinatura daquela funcao ja e o lugar mais caro do repo
para crescer. O nome mudou junto (`...DeConfirmacao` -> `...DeAvisos`) porque
manter o antigo faria a porta mentir sobre o que ela faz.
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
from mobia.domain.agendamento.cancelamento import (
    AVISAR_CANCELAMENTO_JOB as AVISAR_CANCELAMENTO_JOB,
)
from mobia.domain.agendamento.confirmacao import AVISAR_CONFIRMACAO_JOB as AVISAR_CONFIRMACAO_JOB


class AgendadorDeAvisosPort(Protocol):
    async def confirmacao(self, agendamento_id: uuid.UUID) -> None: ...

    async def cancelamento(self, agendamento_id: uuid.UUID) -> None: ...


class AgendadorDeAvisosNoop:
    """Nao agenda nada. O default de todo teste que nao e sobre os avisos."""

    async def confirmacao(self, agendamento_id: uuid.UUID) -> None:
        return None

    async def cancelamento(self, agendamento_id: uuid.UUID) -> None:
        return None


class AgendadorDeAvisosArq:
    """Enfileira os avisos do agendamento.

    `_job_id` fixo por agendamento e o mesmo raciocinio de
    `domain/handoff/agendador.py`: impede que dois enqueues do mesmo
    agendamento mantenham dois jobs vivos ao mesmo tempo. O turno o dispara
    uma vez por transicao, mas uma reentrega da MESMA mensagem faz o turno
    rodar de novo, e ai ele conta.

    **Prefixos diferentes por aviso** (`confirmacao:` e `cancelamento:`): um
    agendamento confirmado e depois cancelado gera os dois, e um id comum
    faria o segundo enqueue ser engolido pelo primeiro -- o corretor saberia
    da visita e nunca do cancelamento dela.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def confirmacao(self, agendamento_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            AVISAR_CONFIRMACAO_JOB,
            str(agendamento_id),
            _job_id=f"confirmacao:{agendamento_id}",
        )

    async def cancelamento(self, agendamento_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            AVISAR_CANCELAMENTO_JOB,
            str(agendamento_id),
            _job_id=f"cancelamento:{agendamento_id}",
        )

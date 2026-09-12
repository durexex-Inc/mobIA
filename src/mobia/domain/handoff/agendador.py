"""Quem pede a geracao do resumo, sem que o dominio saiba o que e ARQ.

TEC-175, D11. Mesmo padrao dos cinco ports que `executar_turno` ja recebe, e
mesmo padrao do `outbound/noop.py` para o duble de teste.
"""

import uuid
from typing import Protocol

from arq.connections import ArqRedis

GERAR_RESUMO_JOB = "gerar_resumo"


class AgendadorDeResumoPort(Protocol):
    async def agendar(self, handoff_id: uuid.UUID) -> None: ...


class AgendadorNoop:
    """Nao agenda nada. O default de todo teste que nao e sobre o resumo."""

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        return None


class AgendadorArq:
    """Enfileira o job de geracao.

    `_job_id` derivado do handoff: dois gatilhos que criem o handoff em
    corrida produziriam dois enqueues, e o ARQ recusa o segundo enquanto o
    primeiro estiver pendente. Como `gerar_resumo` e registrado com
    `keep_result=0` -- mesma razao escrita em `WorkerSettings` para o
    `process_message` --, a chave de resultado nao sobrevive para bloquear uma
    regeneracao legitima depois.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def agendar(self, handoff_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(
            GERAR_RESUMO_JOB, str(handoff_id), _job_id=f"resumo:{handoff_id}"
        )

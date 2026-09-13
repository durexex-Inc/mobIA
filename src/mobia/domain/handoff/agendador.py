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

    `_job_id` derivado do handoff nao existe para arbitrar uma corrida real:
    tanto `_agendar_resumo` quanto o bloco equivalente de `process_message.py`
    so enfileiram sob `registro.criado`, e o `ON CONFLICT` de
    `registrar_handoff` devolve `criado=True` exatamente uma vez por linha
    (ver `test_duas_escritas_concorrentes_produzem_uma_linha`) -- os dois
    gatilhos do mesmo turno rodam na mesma transacao, e o segundo ve a linha
    do primeiro e cai no UPDATE. O `_job_id` fixo e idempotencia barata caso
    um chamador futuro perca essa guarda de `criado`, nao protecao contra algo
    que o codigo de hoje produz. Como `gerar_resumo` e registrado com
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

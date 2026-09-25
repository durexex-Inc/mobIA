"""O job que apaga a trilha de auditoria com mais de 12 meses. TEC-206, D6."""

from typing import Any

from mobia.domain.auditoria.retencao import LOTE_PADRAO, apagar_vencidos

SWEEP_RETENCAO_AUDITORIA_JOB = "sweep_retencao_auditoria"


async def sweep_retencao_auditoria(ctx: dict[str, Any], lote: int = LOTE_PADRAO) -> int:
    """Fino de proposito, como `sweep_conversas_inativas`.

    O rastro da passagem e a linha `auditoria.retencao_executada`, emitida por
    `apagar_vencidos` com a contagem -- e nao este numero de retorno, que o
    ARQ descarta (`keep_result=0`).
    """
    return await apagar_vencidos(ctx["session_factory"], lote=lote)

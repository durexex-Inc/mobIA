"""O job que notifica o corretor do handoff. TEC-177."""

import uuid
from typing import Any

from mobia.domain.notificacao.envio import notificar

NOTIFICAR_JOB = "notificar_corretor"


async def notificar_corretor(ctx: dict[str, Any], handoff_id: str) -> str:
    """Notifica o corretor do handoff. Devolve um rotulo para o log do ARQ.

    Os canais e o `outbound` vem do `ctx`, no mesmo molde de `gerar_resumo`: e
    o `startup` do worker que decide a implementacao, e o teste troca a
    decisao sem tocar no job. Este job nunca e disparado por relogio -- so
    `gerar_resumo` o enfileira, ao terminar, com ou sem resumo gravado.
    """
    aceitou = await notificar(
        ctx["session_factory"],
        canais=ctx["canais_de_notificacao"],
        outbound=ctx["outbound"],
        handoff_id=uuid.UUID(handoff_id),
    )
    return "notificado" if aceitou else "aviso_manual"

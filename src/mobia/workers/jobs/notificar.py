"""O job que notifica o corretor do handoff. TEC-177."""

import uuid
from typing import Any

# A constante mudou de casa para `envio.py` na TEC-279 (comentario la explica
# o porque); o `as NOTIFICAR_JOB` e reexportacao deliberada -- e o que
# `workers/jobs/gerar_resumo.py` ainda importa daqui -- e evita o F401 de
# "importado e nao usado" que um import comum levaria.
from mobia.domain.notificacao.envio import NOTIFICAR_JOB as NOTIFICAR_JOB
from mobia.domain.notificacao.envio import notificar


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

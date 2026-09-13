"""O job que escala o handoff sem aceite dentro do prazo. TEC-178."""

from typing import Any

from mobia.domain.handoff.escalada import escalar_vencidos

SWEEP_SLA_JOB = "sweep_sla"


async def sweep_sla(ctx: dict[str, Any], limite: int = 100) -> int:
    """Escala os handoffs vencidos. Devolve quantos.

    Os canais e o `session_factory` vem do `ctx`, no mesmo molde de
    `notificar_corretor`: e o `startup` do worker que decide a implementacao,
    e o teste troca a decisao sem tocar neste job.
    """
    return await escalar_vencidos(
        ctx["session_factory"], canais=ctx["canais_de_notificacao"], limite=limite
    )

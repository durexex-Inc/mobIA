"""O job que redige o resumo do handoff. TEC-175."""

import uuid
from typing import Any

from mobia.domain.handoff.geracao import gerar_resumo as _gerar
from mobia.infra.db import get_sessionmaker


async def gerar_resumo(ctx: dict[str, Any], handoff_id: str) -> str:
    """Gera o resumo de um handoff. Devolve um rotulo para o log do ARQ.

    O redator vem do `ctx` e nao e construido aqui, pelo mesmo motivo que o
    `classificador` e o `resumidor` do `process_message` vem de la: e o
    `startup` do worker que decide qual implementacao roda, e o teste troca a
    decisao sem tocar no job.
    """
    gravou = await _gerar(
        get_sessionmaker(), redator=ctx["redator"], handoff_id=uuid.UUID(handoff_id)
    )
    return "gravado" if gravou else "sem_resumo"

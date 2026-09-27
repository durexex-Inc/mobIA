"""Preenche a temperatura da cadencia dos leads que ja tinham no-show. TEC-385.

Rode uma vez, depois de `alembic upgrade head` ate a 0068. A migration copia a
temperatura de quem nao tem penalidade; os outros ficam nulos, e a varredura de
follow-up os trata como antes da card ate este script -- ou um recalculo
qualquer -- passar por eles. Pode rodar com o worker de pe: cada lead e
recalculado sob o lock da propria linha, como no turno.
"""

import asyncio
import sys

from mobia.domain.context.repositorio import preencher_temperaturas_da_cadencia
from mobia.infra.db import dispose_engine, get_sessionmaker


async def _rodar() -> int:
    preenchidos = await preencher_temperaturas_da_cadencia(get_sessionmaker())
    await dispose_engine()
    print(f"{preenchidos} lead(s) recalculado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_rodar()))

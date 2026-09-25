"""A retencao da trilha de auditoria: 12 meses e o maximo. TEC-206, D6.

Decidido em conversa em 25/09/2026: como os prazos da RNF-22, e nao como
piso. Uma trilha que sobrevive a transcricao que ela referencia guarda
referencia a um dado que ja nao existe.

**Esta funcao nao decide o que pode ser apagado.** Ela pede as linhas com mais
de 12 meses, e o trigger `eventos_auditoria_imutavel` (migration 0053) confere
linha por linha: um erro no corte daqui esbarra nele e reprova, em vez de
apagar historico recente. "12 meses" e `interval '12 months'` sobre o relogio
do banco -- a mesma definicao do trigger, e nao o `datetime.now()` do worker.
Como o relogio do banco so anda para frente, o corte do trigger, calculado
depois, e sempre mais novo que o desta consulta.
"""

import typing
from typing import Any

import structlog
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

LOTE_PADRAO = 1000

_APAGAR_UM_LOTE = text(
    """
    DELETE FROM eventos_auditoria
    WHERE id IN (
        SELECT id FROM eventos_auditoria
        WHERE criado_em < clock_timestamp() - interval '12 months'
        ORDER BY criado_em
        LIMIT :lote
    )
    """
)


async def apagar_vencidos(
    session_factory: async_sessionmaker[AsyncSession], *, lote: int = LOTE_PADRAO
) -> int:
    """Apaga, lote a lote, o que passou de 12 meses. Devolve quantas linhas.

    Commit por lote: a primeira passagem numa base antiga pode ter milhoes de
    linhas, e um DELETE unico seguraria lock sobre todas ate o fim. O laco
    para no primeiro lote incompleto.
    """
    if lote < 1:
        raise ValueError(f"lote tem de ser positivo: {lote}")
    total = 0
    while True:
        async with session_factory() as session:
            # `CursorResult` porque a tipagem do SQLAlchemy declara o Result
            # generico, sem `rowcount` -- mesmo `cast` de `context/repositorio.py`.
            resultado = typing.cast(
                CursorResult[Any], await session.execute(_APAGAR_UM_LOTE, {"lote": lote})
            )
            await session.commit()
        total += resultado.rowcount
        if resultado.rowcount < lote:
            break
    log.info("auditoria.retencao_executada", apagadas=total)
    return total

"""Job ARQ que processa uma importacao de catalogo ja registrada.

TEC-156. Recebe so o id: os bytes do arquivo moram em `importacoes.arquivo`,
e nao no payload do job. Passar 10 MB pelo Redis a cada importacao
transformaria a fila em armazenamento de arquivo. Ver D9 do desenho.

Casca fina de proposito -- toda a logica esta em `catalogo.importacao.executar`,
que a CLI tambem chama.
"""

import uuid
from typing import Any

import structlog

from mobia.domain.catalogo.importacao import executar
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)


async def importar_catalogo(ctx: dict[str, Any], importacao_id: str) -> None:
    try:
        identificador = uuid.UUID(importacao_id)
    except ValueError:
        log.error("catalogo.job_id_invalido", importacao_id=importacao_id)
        return

    try:
        await executar(get_sessionmaker(), importacao_id=identificador)
    except LookupError:
        # A linha sumiu entre o enqueue e o job. Nao ha o que retentar: sem a
        # linha nao ha nem arquivo nem lugar para gravar o relatorio.
        log.error("catalogo.job_importacao_ausente", importacao_id=importacao_id)

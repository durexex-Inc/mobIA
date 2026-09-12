from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from mobia.api.routes.whatsapp import router as whatsapp_router
from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.infra.db import dispose_engine
from mobia.infra.queue import create_redis_pool

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not hasattr(app.state, "redis_pool"):
        app.state.redis_pool = await create_redis_pool()
        app.state.owns_redis_pool = True
    yield
    if getattr(app.state, "owns_redis_pool", False):
        await app.state.redis_pool.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="mobIA", version="0.1.0", lifespan=lifespan)
    app.include_router(whatsapp_router)

    # Sem token configurado o router NAO entra no app. Nao e 401: rota que nao
    # existe nao pode ser exposta por engano de configuracao, e este projeto
    # ainda nao tem camada de autenticacao. Ver D1 do desenho da TEC-156.
    if settings.catalogo_admin_token:
        from mobia.api.routes.corretores import router as corretores_router
        from mobia.api.routes.imoveis import router as imoveis_router

        app.include_router(imoveis_router)
        app.include_router(corretores_router)
    else:
        log.warning("catalogo.rota_de_importacao_desligada", motivo="sem CATALOGO_ADMIN_TOKEN")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

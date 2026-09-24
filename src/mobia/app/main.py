from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from mobia.api.middleware import RateLimitPorIP
from mobia.api.routes.whatsapp import router as whatsapp_router
from mobia.api.routes.widget import router as widget_router
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
    # Antes do pool: a escuta da central usa uma conexao dele (TEC-124).
    central = getattr(app.state, "central_do_widget", None)
    if central is not None:
        await central.encerrar()
    if getattr(app.state, "owns_redis_pool", False):
        await app.state.redis_pool.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="mobIA", version="0.1.0", lifespan=lifespan)

    # Primeiro middleware do projeto (TEC-205). Aplica-se por omissao e nao por
    # opt-in: uma lista de rotas incluidas erraria para o lado de esquecer uma
    # rota nova, que e o erro caro. Quem precisa ficar de fora esta em
    # `ROTAS_ISENTAS`, com a razao de cada uma escrita la.
    #
    # **Ele nao cobre o widget, e ate a TEC-124 este comentario dizia que
    # sim.** `BaseHTTPMiddleware` devolve cedo para todo escopo que nao seja
    # `http`, entao o handshake de `/widget/chat` nunca passa por aqui. O
    # limite por IP daquela rota e aplicado dentro dela -- ver
    # `_cabe_no_limite_por_ip` em `api/routes/widget.py`.
    app.add_middleware(RateLimitPorIP)

    app.include_router(whatsapp_router)
    # Publico por natureza, e por isso fora do gate de token logo abaixo: e o
    # chat do site, e quem o abre e visitante anonima.
    app.include_router(widget_router)

    # Sem token configurado os routers NAO entram no app. Nao e 401: rota que
    # nao existe nao pode ser exposta por engano de configuracao, e este
    # projeto ainda nao tem camada de autenticacao. Ver D1 do desenho da
    # TEC-156.
    if settings.catalogo_admin_token:
        from mobia.api.routes.conversas import router as conversas_router
        from mobia.api.routes.corretores import router as corretores_router
        from mobia.api.routes.handoffs import router as handoffs_router
        from mobia.api.routes.imoveis import router as imoveis_router
        from mobia.api.routes.metricas import router as metricas_router

        app.include_router(imoveis_router)
        app.include_router(corretores_router)
        app.include_router(handoffs_router)
        app.include_router(conversas_router)
        app.include_router(metricas_router)
    else:
        log.warning("catalogo.rota_de_importacao_desligada", motivo="sem CATALOGO_ADMIN_TOKEN")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

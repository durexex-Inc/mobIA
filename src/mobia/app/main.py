from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mobia.api.routes.whatsapp import router as whatsapp_router
from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.infra.db import dispose_engine
from mobia.infra.queue import create_redis_pool


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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

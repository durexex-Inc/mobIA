import subprocess
import sys
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.app.main import create_app
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.queue import create_redis_pool

if TYPE_CHECKING:
    from arq.connections import ArqRedis

TABELAS = ("message_telemetry", "outbound_dispatches", "messages")


@pytest.fixture(scope="session", autouse=True)
def configurar_logging() -> None:
    """Configura o structlog uma vez por sessao de teste.

    structlog e estado global de processo e em producao so e configurado dentro
    de `create_app()`. Sem esta fixture, um teste que nao sobe o app fica com o
    logger nao-configurado e `caplog` nao enxerga evento nenhum -- a suite
    passaria so por acidente de ordenacao entre arquivos.
    """
    configure_logging(get_settings().log_level)


@pytest.fixture(scope="session", autouse=True)
def migrar_banco() -> None:
    """Aplica as migrations uma vez por sessao de teste.

    Roda o Alembic de verdade em vez de `metadata.create_all` para que as
    migrations sejam exercitadas pelos testes.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
async def banco_limpo(migrar_banco: None) -> AsyncIterator[None]:
    """Trunca antes do teste e descarta o engine depois.

    Truncar na entrada (nao na saida) evita disputar lock com a sessao do teste.
    O dispose no fim e obrigatorio: cada teste roda no seu proprio event loop e
    conexoes asyncpg nao sobrevivem a troca de loop.
    """
    async with get_sessionmaker()() as sessao:
        for tabela in TABELAS:
            existe = await sessao.scalar(text(f"SELECT to_regclass('public.{tabela}')"))
            if existe:
                await sessao.execute(text(f"TRUNCATE TABLE {tabela} CASCADE"))
        await sessao.commit()
    yield
    await dispose_engine()


@pytest.fixture
async def session(banco_limpo: None) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as sessao:
        yield sessao


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def redis_pool() -> AsyncIterator["ArqRedis"]:
    pool = await create_redis_pool()
    await pool.flushdb()
    try:
        yield pool
    finally:
        await pool.flushdb()
        await pool.aclose()


@pytest.fixture
async def client(banco_limpo: None, redis_pool) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.redis_pool = redis_pool
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

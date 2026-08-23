import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.infra.db import dispose_engine, get_sessionmaker

TABELAS = ("outbound_dispatches", "messages")


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

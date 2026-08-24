from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from mobia.app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # hide_parameters: um DBAPIError incorpora os bind params na propria
        # mensagem de erro, e essa mensagem acaba em log (webhook.persist_failed,
        # webhook.error). Sem isso, text_body e raw_payload -- hoje ainda em
        # texto claro, cifrados so a partir do escritor do TEC-126 -- vazariam
        # pelo log de erro mesmo com a mascara de PII, que so olha para
        # campos estruturados, nunca para dentro da string de excecao.
        _engine = create_async_engine(
            get_settings().database_url, pool_pre_ping=True, hide_parameters=True
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None

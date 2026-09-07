from typing import cast

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


def engine_de(session_factory: async_sessionmaker[AsyncSession]) -> AsyncEngine:
    """O engine a que um sessionmaker esta ligado.

    Existe para quem precisa de uma CONEXAO, e nao de uma sessao: um lock
    consultivo de sessao do Postgres vive na conexao do backend, e
    `Session.rollback()` devolve a conexao ao pool -- solta o lock junto. Quem
    precisa que o lock atravesse a passagem inteira tem de segurar uma
    `AsyncConnection`, que sobrevive ao rollback e so e devolvida no `close()`.
    Ver `workers/jobs/indexar_catalogo.py`.

    Le `.kw["bind"]` porque e onde o `sessionmaker` guarda o bind que recebeu
    no construtor, e nao existe acessor melhor: `AsyncSession.get_bind()`
    devolve o `Engine` sincrono de dentro do `AsyncEngine`, que nao serve para
    abrir conexao async. Passa por aqui, e nao espalhado pelos jobs, para que
    esse detalhe tenha um lugar so.
    """
    return cast(AsyncEngine, session_factory.kw["bind"])


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None

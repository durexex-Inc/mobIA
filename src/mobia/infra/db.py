from typing import cast

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from mobia.app.config import get_settings
from mobia.infra.tls import argumentos_de_conexao_do_banco

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
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=argumentos_de_conexao_do_banco(settings),
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


def motivo_do_erro_de_banco(exc: BaseException) -> str | None:
    """O porque de um erro do Postgres, sem a linha que o causou.

    **O vetor nao e o que parece.** `hide_parameters=True`, logo acima, cala o
    eco de parametros da SQLAlchemy -- e ele funciona: o texto do erro traz
    `[SQL parameters hidden due to hide_parameters=True]`. O que vaza e a linha
    `DETAIL`, que o SERVIDOR escreve e nenhuma configuracao de cliente alcanca:

        UNIQUE -> DETAIL:  Key (channel, provider_message_id)=(whatsapp, wamid...)
        CHECK  -> DETAIL:  Failing row contains (5511987654321, quero 2 quartos, -1)

    O segundo despeja a LINHA INTEIRA. Medido na TEC-292.

    Dai extrair campos em vez de repassar texto. `sqlstate`, `table_name` e
    `constraint_name` vivem na excecao do asyncpg, que a SQLAlchemy embrulha --
    por isso o `orig.__cause__`. `detail` fica de fora de proposito: e ele o
    vetor.

    **Isto e diagnostico melhor, nao pior.** `23514 constraint_name=ck_...` e
    estruturado e greppavel; `str(exc)` obrigava a ler prosa para chegar no
    mesmo, e trazia os dados junto.

    **A ultima meia frase deixou de valer na SQLAlchemy 2.1 (TEC-369).** Ela
    parou de compor o `DETAIL` dentro do `str()` da excecao que embrulha, entao
    hoje aquele texto NAO traz a linha do lead -- so o `[SQL parameters hidden
    due to hide_parameters=True]`. Isso nao muda nada do que esta escrito
    acima, e e importante nao confundir as duas coisas: **o servidor continua
    mandando o `DETAIL` e ele continua a carregar a linha inteira**, agora
    alcancavel so por `orig.__cause__.detail`. O que mudou foi o ENDERECO do
    vetor, nao a existencia dele -- quem logar aquele campo vaza igual, e por
    isso esta funcao segue deixando `detail` de fora.

    A guarda que prova isso vive em `tests/integration/test_motivo_do_erro_de_banco.py`
    (ver `_detalhe`), e foi ela que denunciou a mudanca ao reprovar.

    Devolve `None` para o que nao for erro do driver -- sem ramo de melhor
    esforco, que seria o buraco que esta funcao existe para nao abrir.
    """
    origem = getattr(exc, "orig", None)
    causa = getattr(origem, "__cause__", None)
    sqlstate = getattr(causa, "sqlstate", None)
    if not isinstance(sqlstate, str):
        return None
    partes = [sqlstate]
    for campo in ("table_name", "constraint_name"):
        valor = getattr(causa, campo, None)
        if isinstance(valor, str) and valor:
            partes.append(f"{campo}={valor}")
    return " ".join(partes)

"""A gravacao do bloqueio por rate limit, com guarda de janela (TEC-205).

Uma linha por (escopo, chave) por janela. A guarda e um `SET NX EX` em Redis:
quem cria a chave grava a linha, os demais bloqueios da mesma janela so
aparecem no log. Ver o docstring de `models.py` para por que a alternativa --
uma linha por requisicao bloqueada -- transforma a defesa em vetor de ataque.

Este modulo NAO propaga excecao de banco. O bloqueio ja aconteceu e ja foi
logado quando ele e chamado; perder o registro nao pode derrubar a rota nem a
ingestao, que e o mesmo contrato de `MessageRecorder` e o oposto do de
`bloqueio.py`, onde a excecao sobe porque a marca de moderacao faz parte da
decisao. Aqui nao ha decisao pendurada na linha: ela e evidencia posterior.

A construcao do `RateLimitEvent` fica FORA do try de banco: um erro ali e
defeito de codigo (kwarg errado, tipo errado), nao indisponibilidade, e
engoli-lo no mesmo except transformaria um bug em no-op permanente.
"""

import math
import uuid

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.limites.models import RateLimitEvent
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_guarda

log = structlog.get_logger(__name__)


async def _ganhou_a_guarda(
    pool: Redis | None, escopo: str, chave: str, janela_segundos: float
) -> bool:
    """Fail-open: sem Redis nao ha como deduplicar, e perder o registro do
    abuso e pior que registra-lo de mais.
    """
    if pool is None:
        return True
    try:
        criou = await pool.set(
            chave_de_guarda(escopo, chave),
            "1",
            nx=True,
            # ceil e nao int/trunc: truncar deixaria a guarda expirar antes do
            # fim da janela, e uma segunda linha seria gravada dentro da
            # mesma janela -- o que esta funcao existe para impedir.
            ex=math.ceil(janela_segundos),
        )
    except RedisError as exc:
        log.warning("ratelimit.guarda_indisponivel", erro=type(exc).__name__)
        return True
    return bool(criou)


async def registrar_bloqueio(
    session_factory: async_sessionmaker[AsyncSession],
    pool: Redis | None,
    *,
    escopo: str,
    chave: str,
    channel: str,
    volume: int,
    limite: int,
    message_id: uuid.UUID | None = None,
    janela_segundos: float = JANELA_DE_UM_MINUTO,
) -> bool:
    """Grava o bloqueio se esta for a primeira vez nesta janela.

    Devolve se gravou. O `volume` que acaba na linha e, por consequencia, o do
    PRIMEIRO disparo da janela -- `limite + 1` no caso comum, que e
    literalmente "o volume que disparou o limite" do criterio de aceite. O
    volume total de cada janela continua visivel no log `ratelimit.blocked`,
    que sai a cada bloqueio.
    """
    if not await _ganhou_a_guarda(pool, escopo, chave, janela_segundos):
        return False

    evento = RateLimitEvent(
        id=uuid.uuid4(),
        escopo=escopo,
        chave=chave,
        channel=channel,
        volume=volume,
        limite=limite,
        message_id=message_id,
    )

    try:
        async with session_factory() as session:
            session.add(evento)
            await session.commit()
    except Exception as exc:
        log.warning("ratelimit.evento_nao_gravado", erro=type(exc).__name__)
        return False
    return True

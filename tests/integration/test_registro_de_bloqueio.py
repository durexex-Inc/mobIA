"""A guarda que faz UMA linha de evento por chave por janela (TEC-205)."""

import uuid

from sqlalchemy import func, select

from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_IP, ESCOPO_NUMERO, RateLimitEvent


async def _quantas(session) -> int:
    return (await session.execute(select(func.count()).select_from(RateLimitEvent))).scalar_one()


async def test_o_primeiro_bloqueio_grava(session_factory, redis_pool, session) -> None:
    gravou = await registrar_bloqueio(
        session_factory,
        redis_pool,
        escopo=ESCOPO_NUMERO,
        chave="5511999999999",
        channel="whatsapp",
        volume=21,
        limite=20,
        message_id=uuid.uuid4(),
    )
    assert gravou is True
    assert await _quantas(session) == 1


async def test_os_bloqueios_seguintes_da_mesma_janela_nao_gravam(
    session_factory, redis_pool, session
) -> None:
    """Sem esta guarda, o registro de abuso e o proprio vetor de abuso: uma
    linha de banco por requisicao bloqueada.
    """
    for volume in range(21, 121):
        await registrar_bloqueio(
            session_factory,
            redis_pool,
            escopo=ESCOPO_NUMERO,
            chave="5511999999999",
            channel="whatsapp",
            volume=volume,
            limite=20,
            message_id=uuid.uuid4(),
        )
    assert await _quantas(session) == 1

    # E o que ficou gravado e o volume do PRIMEIRO disparo -- "o volume que
    # disparou o limite", na letra do criterio de aceite.
    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.volume == 21


async def test_chaves_diferentes_gravam_cada_uma(session_factory, redis_pool, session) -> None:
    await registrar_bloqueio(
        session_factory,
        redis_pool,
        escopo=ESCOPO_NUMERO,
        chave="5511111111111",
        channel="whatsapp",
        volume=21,
        limite=20,
        message_id=uuid.uuid4(),
    )
    await registrar_bloqueio(
        session_factory,
        redis_pool,
        escopo=ESCOPO_NUMERO,
        chave="5522222222222",
        channel="whatsapp",
        volume=21,
        limite=20,
        message_id=uuid.uuid4(),
    )
    assert await _quantas(session) == 2


async def test_escopos_diferentes_com_a_mesma_chave_nao_se_calam(
    session_factory, redis_pool, session
) -> None:
    """A guarda e por (escopo, chave). Um numero e um IP textualmente iguais
    sao dois assuntos distintos.
    """
    await registrar_bloqueio(
        session_factory,
        redis_pool,
        escopo=ESCOPO_NUMERO,
        chave="123456789",
        channel="whatsapp",
        volume=21,
        limite=20,
        message_id=uuid.uuid4(),
    )
    await registrar_bloqueio(
        session_factory,
        redis_pool,
        escopo=ESCOPO_IP,
        chave="123456789",
        channel="http",
        volume=101,
        limite=100,
    )
    assert await _quantas(session) == 2


async def test_sem_redis_grava_e_nao_explode(session_factory, session) -> None:
    """Fail-open da guarda: sem Redis nao ha como deduplicar, e perder o
    registro do abuso e pior que registra-lo de mais.
    """
    gravou = await registrar_bloqueio(
        session_factory,
        None,
        escopo=ESCOPO_IP,
        chave="203.0.113.9",
        channel="http",
        volume=101,
        limite=100,
    )
    assert gravou is True
    assert await _quantas(session) == 1

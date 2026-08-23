import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_stalled import sweep_stalled


async def mensagem(
    session,
    status: str,
    idade_segundos: int,
    attempts: int = 0,
) -> uuid.UUID:
    instante = datetime.now(UTC) - timedelta(seconds=idade_segundos)
    message = Message(
        id=uuid.uuid4(),
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="oi",
        raw_payload={},
        status=status,
        attempts=attempts,
        received_at=instante,
        queued_at=instante if status != MessageStatus.RECEIVED else None,
    )
    session.add(message)
    await session.commit()
    return message.id


def contexto(redis_pool, settings) -> dict:
    return {
        "session_factory": get_sessionmaker(),
        "redis": redis_pool,
        "settings": settings,
    }


async def test_reenfileira_received_parado(session, redis_pool, settings) -> None:
    message_id = await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1

    jobs = await redis_pool.queued_jobs()
    assert [job.args for job in jobs] == [(str(message_id),)]

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.attempts == 1


async def test_nao_toca_em_received_recente(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.RECEIVED, idade_segundos=5)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_reenfileira_processing_travado(session, redis_pool, settings) -> None:
    message_id = await mensagem(session, MessageStatus.PROCESSING, idade_segundos=3600)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1
    assert [job.args for job in await redis_pool.queued_jobs()] == [(str(message_id),)]


async def test_nao_toca_em_queued_recente(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.QUEUED, idade_segundos=60)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_ignora_processed(session, redis_pool, settings) -> None:
    """PROCESSED e o unico estado realmente terminal.

    FAILED nao e terminal: o ARQ nao re-tenta excecao comum, entao o sweeper e o
    unico caminho de volta para uma mensagem que falhou.
    """
    await mensagem(session, MessageStatus.PROCESSED, idade_segundos=3600)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_respeita_o_teto_de_tentativas(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120, attempts=5)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_varre_varias_de_uma_vez(session, redis_pool, settings) -> None:
    for _ in range(3):
        await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 3
    assert len(await redis_pool.queued_jobs()) == 3

    paradas = (
        await session.scalars(
            select(Message).where(Message.status == MessageStatus.RECEIVED)
        )
    ).all()
    assert all(linha.attempts == 1 for linha in paradas)

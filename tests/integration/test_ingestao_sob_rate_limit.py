"""O excedente por numero e adiado, nao recusado (TEC-205)."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.limites.models import RateLimitEvent
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus


def _parsed(indice: int, remetente: str = "5511999999999") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=f"wamid.rl{indice}",
        sender_external_id=remetente,
        recipient_external_id="5511000000000",
        content_type=MessageContentType.TEXTO,
        text_body=f"mensagem {indice}",
        raw_payload={},
    )


async def _defers(redis_pool) -> list[float]:
    """Quantos milissegundos no futuro cada job foi agendado."""
    agora_ms = datetime.now(UTC).timestamp() * 1000
    jobs = await redis_pool.zrange("arq:queue", 0, -1, withscores=True)
    return sorted(score - agora_ms for _, score in jobs)


async def test_dentro_do_limite_nada_muda(
    session_factory, redis_pool, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "5")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(5)])

    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0
    # Todas esperam a janela de debounce, nenhuma o backoff.
    janela_ms = get_settings().debounce_de_rajada_segundos * 1000
    for defer in await _defers(redis_pool):
        assert defer <= janela_ms + 500


async def test_o_excedente_espera_o_backoff(
    session_factory, redis_pool, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    """Cenario do card: o vigesimo primeiro entra em backoff."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "3")
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "1")
    monkeypatch.setenv("ATRASO_DE_BACKOFF_SEGUNDOS", "20")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(4)])

    defers = await _defers(redis_pool)
    assert len(defers) == 4
    # Tres em ~1s (a janela) e uma em ~20s (o backoff).
    assert sum(1 for d in defers if d > 10_000) == 1


async def test_o_excedente_nao_e_recusado(
    session_factory, redis_pool, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    """Adiada, nao descartada: a linha existe e chega a QUEUED."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "3")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    ids = await service.ingest([_parsed(i) for i in range(4)])

    assert len(ids) == 4
    status = (await session.execute(select(Message.status))).scalars().all()
    assert all(s == MessageStatus.QUEUED for s in status)


async def test_o_bloqueio_vira_evento(
    session_factory, redis_pool, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "3")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(6)])

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.chave == "5511999999999"
    assert linha.channel == "whatsapp"
    assert linha.limite == 3
    assert linha.volume == 4


async def test_numeros_diferentes_nao_compartilham_cota(
    session_factory, redis_pool, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "2")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(0, "5511111111111"), _parsed(1, "5522222222222")])

    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0


async def test_limite_zero_nao_conta_nada(
    session_factory, redis_pool, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "0")
    get_settings.cache_clear()

    service = IngestionService(session_factory, redis_pool)
    await service.ingest([_parsed(i) for i in range(30)])

    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0

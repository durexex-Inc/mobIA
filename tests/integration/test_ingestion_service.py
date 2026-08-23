from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker


def parsed(provider_message_id: str = "wamid.SERVICO") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="quero agendar visita",
        raw_payload={"id": provider_message_id, "type": "text"},
    )


class FilaQuebrada:
    async def enqueue_job(self, *args, **kwargs):
        raise ConnectionError("redis fora do ar")


async def test_persiste_e_enfileira(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    ids = await service.ingest([parsed()])

    assert len(ids) == 1
    linha = await session.get(Message, ids[0])
    assert linha is not None
    assert linha.channel == "whatsapp"
    assert linha.status == MessageStatus.QUEUED
    assert linha.queued_at is not None
    assert len(await redis_pool.queued_jobs()) == 1


async def test_redis_fora_do_ar_nao_perde_a_mensagem(session, caplog) -> None:
    service = IngestionService(get_sessionmaker(), FilaQuebrada())

    with caplog.at_level("WARNING"):
        ids = await service.ingest([parsed("wamid.SEM_REDIS")])

    linha = await session.get(Message, ids[0])
    assert linha is not None, "a mensagem tem de existir mesmo sem fila"
    assert linha.status == MessageStatus.RECEIVED
    assert linha.queued_at is None
    assert "enqueue.failed" in caplog.text


async def test_sem_fila_configurada_a_mensagem_fica_received(session) -> None:
    service = IngestionService(get_sessionmaker(), None)

    ids = await service.ingest([parsed("wamid.SEM_FILA")])

    linha = await session.get(Message, ids[0])
    assert linha.status == MessageStatus.RECEIVED


async def test_lote_com_varias_mensagens(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    ids = await service.ingest([parsed("wamid.A"), parsed("wamid.B")])

    assert len(ids) == 2
    linhas = (await session.scalars(select(Message))).all()
    assert {linha.provider_message_id for linha in linhas} == {"wamid.A", "wamid.B"}
    assert len(await redis_pool.queued_jobs()) == 2


async def test_lista_vazia_nao_faz_nada(redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)
    assert await service.ingest([]) == []
    assert await redis_pool.queued_jobs() == []

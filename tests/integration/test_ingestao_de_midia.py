"""A ingestao grava a midia pendente e enfileira o download. TEC-132, Task 4."""

from sqlalchemy import select

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.midia.models import MidiaRecebida, StatusDaMidia
from mobia.infra.db import get_sessionmaker


def _imagem(provider_message_id: str = "wamid.IMG") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.IMAGEM,
        text_body=None,
        raw_payload={
            "id": provider_message_id,
            "type": "image",
            "image": {"id": "media-1", "mime_type": "image/jpeg", "sha256": "ab" * 32},
        },
    )


def _documento(provider_message_id: str = "wamid.DOC") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.DOCUMENTO,
        text_body=None,
        raw_payload={
            "id": provider_message_id,
            "type": "document",
            "document": {"id": "media-2", "mime_type": "application/pdf", "filename": "rg.pdf"},
        },
    )


def _texto(provider_message_id: str = "wamid.TXT") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body="quero agendar visita",
        raw_payload={"id": provider_message_id, "type": "text", "text": {"body": "oi"}},
    )


async def test_imagem_gera_midia_pendente_e_job(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await service.ingest([_imagem()])

    linha = await session.get(MidiaRecebida, message_id)
    assert linha is not None
    assert linha.status == StatusDaMidia.PENDENTE
    assert linha.media_id_da_meta == "media-1"
    assert await redis_pool.zscore("arq:queue", f"midia:{message_id}") is not None


async def test_texto_nao_gera_midia_nem_job(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await service.ingest([_texto()])

    assert await session.get(MidiaRecebida, message_id) is None
    assert await redis_pool.zscore("arq:queue", f"midia:{message_id}") is None


async def test_reentrega_nao_cria_segunda_midia(session, redis_pool) -> None:
    """O mesmo envelope duas vezes deixa uma mensagem, uma linha de midia e um
    job de download -- a segunda chamada nao acha linha nova em `messages`
    (ON CONFLICT DO NOTHING de sempre) e por isso nem entra no loop que
    enfileira."""
    service = IngestionService(get_sessionmaker(), redis_pool)
    envelope = _imagem("wamid.REENTREGA")

    (message_id,) = await service.ingest([envelope])
    segunda_entrega = await service.ingest([envelope])

    assert segunda_entrega == []
    linhas = (
        (await session.execute(select(MidiaRecebida).where(MidiaRecebida.message_id == message_id)))
        .scalars()
        .all()
    )
    assert len(linhas) == 1
    jobs_de_midia = [
        job for job in await redis_pool.queued_jobs() if job.function == "baixar_midia"
    ]
    assert len(jobs_de_midia) == 1


async def test_documento_gera_midia_pendente(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await service.ingest([_documento()])

    linha = await session.get(MidiaRecebida, message_id)
    assert linha is not None
    assert linha.status == StatusDaMidia.PENDENTE
    assert linha.media_id_da_meta == "media-2"
    # O nome do arquivo nao vira coluna (D2 da Task 3).
    assert linha.mime_type == "application/pdf"


async def test_falha_no_enqueue_da_midia_nao_derruba_a_ingestao(
    session, redis_pool, monkeypatch, caplog
) -> None:
    async def _quebrado(pool, message_id):
        raise RuntimeError("fila de midia fora do ar")

    monkeypatch.setattr("mobia.domain.messages.service.enqueue_baixar_midia", _quebrado)
    service = IngestionService(get_sessionmaker(), redis_pool)

    with caplog.at_level("WARNING"):
        (message_id,) = await service.ingest([_imagem("wamid.FALHA_MIDIA")])

    # process_message foi enfileirado normalmente -- so a midia falhou.
    assert await redis_pool.zscore("arq:queue", f"msg:{message_id}") is not None
    assert "midia.enqueue_failed" in caplog.text

    linha = await session.get(MidiaRecebida, message_id)
    assert linha is not None
    assert linha.status == StatusDaMidia.PENDENTE

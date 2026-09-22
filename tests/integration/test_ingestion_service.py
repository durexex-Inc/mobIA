from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, decrypt, decrypt_json
from mobia.infra.db import get_sessionmaker


def parsed(provider_message_id: str = "wamid.SERVICO") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body="quero agendar visita",
        raw_payload={"id": provider_message_id, "type": "text"},
    )


class _PipelineQuebrado:
    """Enfileira comandos sem tocar rede, como o pipeline de verdade -- so
    falha no `execute`, que e onde o redis-py de fato conversa com o servidor.
    """

    def zremrangebyscore(self, *args, **kwargs):
        return self

    def zadd(self, *args, **kwargs):
        return self

    def zcard(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    async def execute(self):
        raise RedisConnectionError("redis fora do ar")


class FilaQuebrada:
    """Simula o Redis inteiro fora do ar, nao so o enqueue.

    Desde a TEC-205 `self._queue` tambem e o pool que `consumir` usa para o
    rate limit, entao um duble que so derrubasse `enqueue_job` deixaria
    `consumir` chamar `pipeline()` num objeto sem o metodo -- `AttributeError`,
    nao a falha de conexao que este teste quer exercitar. `pipeline()` aqui
    devolve algo que so falha no `execute`, igual ao redis-py real, para que o
    fail-open de `consumir` (que so pega `RedisError`) valha tambem aqui.
    """

    async def enqueue_job(self, *args, **kwargs):
        raise ConnectionError("redis fora do ar")

    def pipeline(self, *args, **kwargs):
        return _PipelineQuebrado()


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


async def test_entrada_grava_papel_direcao_e_conversa(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await service.ingest([parsed("wamid.PAPEL")])

    linha = await session.get(Message, message_id)
    assert linha is not None
    assert linha.role == MessageRole.LEAD
    assert linha.direction == MessageDirection.INBOUND
    assert linha.conversation_key == linha.sender_external_id


async def test_ingestao_atrasa_o_job_pela_janela(session, redis_pool, monkeypatch) -> None:
    """A ingestao e o unico ponto que atrasa: e onde a rajada pode estar se formando."""
    from datetime import UTC, datetime

    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed()])

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
        assert 5_000 < jobs[0].score - antes_ms < 7_000
    finally:
        get_settings.cache_clear()


async def test_janela_zero_enfileira_para_agora(session, redis_pool, monkeypatch) -> None:
    from datetime import UTC, datetime

    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "0")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed()])

        jobs = await redis_pool.queued_jobs()
        assert jobs[0].score is not None
        assert jobs[0].score - antes_ms < 1_000
    finally:
        get_settings.cache_clear()


async def test_conteudo_vai_cifrado_para_o_banco(session, redis_pool) -> None:
    """Um SELECT cru nao pode devolver o que a Marina escreveu."""
    service = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await service.ingest([parsed("wamid.CIFRADO")])

    cru = (
        await session.execute(
            sql("SELECT text_body, raw_payload FROM messages WHERE id = :id"),
            {"id": message_id},
        )
    ).one()
    assert isinstance(cru.text_body, bytes | memoryview)
    assert b"quero agendar visita" not in bytes(cru.text_body)

    assert decrypt(bytes(cru.text_body), aad_de(message_id, "text_body")) is not None
    assert decrypt_json(bytes(cru.raw_payload), aad_de(message_id, "raw_payload")) is not None

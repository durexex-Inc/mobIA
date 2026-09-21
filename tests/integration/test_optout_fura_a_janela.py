"""O opt-out nao espera a janela, e a janela nao pode engoli-lo (TEC-128, D5)."""

import uuid
from datetime import UTC, datetime, timedelta

from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker

PEDIDO = "nao quero mais receber mensagens"


def parsed_com(texto: str, sufixo: str = "") -> ParsedMessage:
    identificador = sufixo or uuid.uuid4().hex
    return ParsedMessage(
        provider_message_id=f"wamid.{identificador}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body=texto,
        raw_payload={"id": f"wamid.{identificador}", "type": "text"},
    )


async def test_optout_nao_espera_a_janela(session, redis_pool, monkeypatch) -> None:
    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed_com(PEDIDO)])

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
        assert jobs[0].score - antes_ms < 1_000
    finally:
        get_settings.cache_clear()


async def test_mensagem_comum_no_mesmo_lote_continua_esperando(
    session, redis_pool, monkeypatch
) -> None:
    """Um envelope com as duas: cada uma recebe o seu proprio tratamento."""
    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed_com("ainda tem o 2 quartos?", "A"), parsed_com(PEDIDO, "B")])

        jobs = {job.job_id: job for job in await redis_pool.queued_jobs()}
        assert len(jobs) == 2
        atrasos = sorted(job.score - antes_ms for job in jobs.values() if job.score is not None)
        assert atrasos[0] < 1_000
        assert 5_000 < atrasos[1] < 7_000
    finally:
        get_settings.cache_clear()


async def test_optout_superado_ainda_roda_o_turno(session, redis_pool, monkeypatch) -> None:
    """O defeito que a TEC-182 previu: sem esta excecao, o opt-out sumiria.

    O lead pede para parar e, nos milissegundos seguintes, manda outra coisa. A
    checagem de superacao declararia o opt-out superado e ele nunca seria
    registrado -- em silencio, sem log de erro e sem nada no banco.
    """
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    pedido = await gravar(session, created_at=agora, texto=PEDIDO)
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="ou melhor, me liga")

    rodou = {"turno": False}

    async def turno_espiao(*args, **kwargs):
        rodou["turno"] = True
        return "opt_out"

    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", turno_espiao)

    resultado = await process_message(_ctx(), str(pedido.id))

    assert rodou["turno"] is True
    assert resultado != "agrupado"


async def test_superada_que_nao_pediu_optout_continua_agrupando(
    session, redis_pool, monkeypatch
) -> None:
    """A excecao da D5 nao pode virar um furo geral na D3."""
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    comum = await gravar(session, created_at=agora, texto="ainda tem o 2 quartos?")
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="ou de 3?")

    async def turno_que_nao_devia_rodar(*args, **kwargs):
        raise AssertionError("executar_turno rodou para uma mensagem superada comum")

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", turno_que_nao_devia_rodar
    )

    resultado = await process_message(_ctx(), str(comum.id))

    assert resultado == "agrupado"

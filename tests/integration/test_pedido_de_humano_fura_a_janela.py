"""O pedido de humano nao espera a janela, e a janela nao pode engoli-lo.

TEC-128, onda final, Critical 1. Molde de `test_optout_fura_a_janela.py`: os
dois furos sao o MESMO idioma (D5 do desenho), aplicado a `pediu_humano` em
vez de `pediu_optout`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker

PEDIDO = "quero falar com um atendente"


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


async def test_pedido_de_humano_nao_espera_a_janela(session, redis_pool, monkeypatch) -> None:
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


async def test_pedido_de_humano_superado_ainda_roda_o_turno(
    session, redis_pool, monkeypatch
) -> None:
    """O defeito simetrico ao do opt-out: sem esta excecao, o pedido de humano
    isolado que perde a corrida contra uma mensagem mais nova fecha como
    "agrupado", `pediu_humano` nunca roda sobre ele e nenhum handoff nasce --
    em silencio, sem log de erro.
    """
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    pedido = await gravar(session, created_at=agora, texto=PEDIDO)
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="alo?")

    rodou = {"turno": False}

    async def turno_espiao(*args, **kwargs):
        rodou["turno"] = True
        return "handoff_humano"

    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", turno_espiao)

    resultado = await process_message(_ctx(), str(pedido.id))

    assert rodou["turno"] is True
    assert resultado != "agrupado"


async def test_superada_que_nao_pediu_humano_continua_agrupando(
    session, redis_pool, monkeypatch
) -> None:
    """A excecao nao pode virar um furo geral na D3 (nao-regressao)."""
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

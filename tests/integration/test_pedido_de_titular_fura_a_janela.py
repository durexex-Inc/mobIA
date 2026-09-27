"""O pedido de titular nao espera a janela, e a janela nao pode engoli-lo.

TEC-207, D3. Molde de `test_pedido_de_humano_fura_a_janela.py`: o mesmo idioma
dos dois furos que ja existiam (opt-out e pedido de humano), aplicado a
`pedido_de_titular`. Sem ele, "quero apagar meus dados" seguido de "ok,
obrigado" dentro da janela fechava como "agrupado": nenhuma solicitacao,
nenhum prazo de 15 dias, nenhum log de erro.

Desde a revisao final (C2) a eliminacao e em dois passos, e a palavra que
confirma ("apagar") fura a janela do mesmo jeito: segura-la atrasaria o
registro, e engoli-la como "agrupado" perderia a confirmacao.
"""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import OutboundFake  # type: ignore[import-not-found]
from sqlalchemy import select
from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.titular.deteccao import (
    KIND_DA_PERGUNTA_DE_ELIMINACAO,
    TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO,
    TEXTO_DA_PERGUNTA_DE_ELIMINACAO,
)
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.vocabulario import TipoDeSolicitacao
from mobia.infra.db import get_sessionmaker

PEDIDO = "quero apagar meus dados"


def parsed_com(texto: str) -> ParsedMessage:
    identificador = uuid.uuid4().hex
    return ParsedMessage(
        provider_message_id=f"wamid.{identificador}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body=texto,
        raw_payload={"id": f"wamid.{identificador}", "type": "text"},
    )


async def test_pedido_de_titular_nao_espera_a_janela(session, redis_pool, monkeypatch) -> None:
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


async def test_pedido_de_titular_superado_pergunta(session, redis_pool) -> None:
    """O turno de verdade roda sobre a superada: a pergunta de eliminacao sai
    mesmo com uma mensagem mais nova do mesmo lead."""
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    pedido = await gravar(session, created_at=agora, texto=PEDIDO)
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="ok, obrigado")

    ctx = _ctx()
    outbound = OutboundFake(get_sessionmaker())
    ctx["outbound"] = outbound

    resultado = await process_message(ctx, str(pedido.id))

    assert resultado == "confirmacao_de_titular_pedida"
    assert len(outbound.entregues) == 1
    assert TEXTO_DA_PERGUNTA_DE_ELIMINACAO in outbound.entregues[0]


async def test_apagar_nao_espera_a_janela(session, redis_pool, monkeypatch) -> None:
    """A palavra solta fura o debounce sempre -- com ou sem pergunta pendente,
    porque a ingestao nao consulta o banco para saber. Furar sem ser
    confirmacao e inofensivo: o turno roda normalmente."""
    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed_com("APAGAR")])

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
        assert jobs[0].score - antes_ms < 1_000
    finally:
        get_settings.cache_clear()


async def test_apagar_superado_depois_da_pergunta_registra_e_confirma(session, redis_pool) -> None:
    """A confirmacao seguida de "ok" dentro da janela: sem o furo, "apagar"
    fechava como "agrupado" e o pedido confirmado nunca era registrado."""
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    pedido = await gravar(session, created_at=agora - timedelta(minutes=1), texto=PEDIDO)
    # A pergunta que o turno do pedido teria mandado: a reserva e o que o
    # segundo passo le.
    session.add(OutboundDispatch(message_id=pedido.id, kind=KIND_DA_PERGUNTA_DE_ELIMINACAO))
    await session.commit()
    confirmacao = await gravar(session, created_at=agora, texto="apagar")
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="ok")

    ctx = _ctx()
    outbound = OutboundFake(get_sessionmaker())
    ctx["outbound"] = outbound

    resultado = await process_message(ctx, str(confirmacao.id))

    assert resultado == "pedido_de_titular"
    session.expire_all()
    [linha] = (await session.execute(select(SolicitacaoDeTitular))).scalars().all()
    assert linha.tipo == TipoDeSolicitacao.ELIMINACAO
    assert len(outbound.entregues) == 1
    assert TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO in outbound.entregues[0]

"""O indicador de digitacao escolhido pelo canal da linha. TEC-124, D5."""

import uuid
from datetime import UTC, datetime
from typing import Any

from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.app.config import get_settings
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.crypto import aad_de, encrypt
from mobia.workers.jobs.process_message import process_message

SESSAO = "8c0f0a3e-0000-4000-8000-0000000000cc"


class IndicadorEspiao:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, str]] = []

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        self.chamadas.append((provider_message_id, de))


async def _entrada_web(session) -> Message:
    """A entrada do widget, com os DOIS campos que enganam a guarda de insumo."""
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL_WEB,
        provider_message_id="m-1",
        sender_external_id=SESSAO,
        recipient_external_id=REMETENTE_DO_WIDGET,
        conversation_key=SESSAO,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("oi", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.RECEIVED,
        created_at=datetime.now(UTC),
    )
    session.add(linha)
    await session.commit()
    return linha


def _ctx_com(espiao: IndicadorEspiao, outbound: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = _ctx()
    ctx["outbound"] = outbound
    ctx["indicadores"] = {CANAL_WHATSAPP: espiao, CANAL_WEB: IndicadorNoop()}
    return ctx


async def test_a_linha_web_nao_indica_pela_meta(
    session, redis_pool, monkeypatch, outbound_fake, caches_de_cliente_limpos
) -> None:
    """O perigo e concreto, e nao hipotetico.

    `indicador_de_digitacao` desiste cedo quando `provider_message_id` ou
    `recipient_external_id` sao nulos. No web os DOIS estao preenchidos -- o
    id do cliente e a constante `widget` --, entao a guarda nao desiste e o
    `WhatsAppIndicador` dispararia um POST para a Meta com um UUID de sessao
    no lugar do wamid.
    """
    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "0")
    get_settings.cache_clear()

    linha = await _entrada_web(session)
    espiao = IndicadorEspiao()

    await process_message(_ctx_com(espiao, outbound_fake()), str(linha.id))

    assert espiao.chamadas == []


async def test_a_linha_whatsapp_continua_indicando(
    session, redis_pool, monkeypatch, outbound_fake, caches_de_cliente_limpos
) -> None:
    """A outra metade: o dicionario lido do lado errado calaria o WhatsApp."""
    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "0")
    get_settings.cache_clear()

    linha = await gravar(session, created_at=datetime.now(UTC))
    espiao = IndicadorEspiao()

    await process_message(_ctx_com(espiao, outbound_fake()), str(linha.id))

    assert len(espiao.chamadas) == 1

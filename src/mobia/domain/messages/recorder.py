import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import PRECOS_POR_MODELO
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.infra.crypto import aad_de, encrypt

log = structlog.get_logger(__name__)

_MILIONESIMO_DE_DOLAR = Decimal("0.000001")


def custo_em_dolar(model: str, tokens_in: int, tokens_out: int) -> Decimal | None:
    """Devolve None para modelo sem preco cadastrado, nunca zero.

    Zero somaria silenciosamente no painel de custo e faria o gasto parecer
    menor do que foi. None aparece como lacuna e alguem conserta.
    """
    preco = PRECOS_POR_MODELO.get(model)
    if preco is None:
        return None
    entrada, saida = preco
    total = (Decimal(tokens_in) / Decimal(1_000_000)) * entrada + (
        Decimal(tokens_out) / Decimal(1_000_000)
    ) * saida
    return total.quantize(_MILIONESIMO_DE_DOLAR)


class MessageRecorder:
    """Registra a fala do agente e a telemetria dela.

    Dois passos, nao uma transacao. Se os dois inserts fossem atomicos, uma
    falha de telemetria derrubaria junto o registro da fala -- e o criterio pede
    o oposto: a resposta e entregue normalmente e a falha de telemetria e
    registrada sem interromper o fluxo.

    E a mesma filosofia do `_try_enqueue` do TEC-122: persiste primeiro, o
    efeito secundario e otimista e engole a propria falha.

    Nenhum metodo propaga excecao. Quem chama esta no meio de responder ao lead.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_agent_message(
        self,
        *,
        conversation_key: str,
        channel: str,
        text: str,
        model: str,
        subagent: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        sender_external_id: str | None = None,
        recipient_external_id: str | None = None,
    ) -> uuid.UUID | None:
        identificador = uuid.uuid4()
        try:
            async with self._session_factory() as session:
                session.add(
                    Message(
                        id=identificador,
                        channel=channel,
                        provider_message_id=None,
                        sender_external_id=sender_external_id,
                        recipient_external_id=recipient_external_id,
                        conversation_key=conversation_key,
                        role=MessageRole.AGENTE,
                        direction=MessageDirection.OUTBOUND,
                        content_type=MessageContentType.TEXTO,
                        text_body=encrypt(text, aad_de(identificador, "text_body")),
                        raw_payload=None,
                        # NULL: a fala do agente nao participa do pipeline de
                        # ingestao e o sweeper nao pode reivindica-la.
                        status=None,
                    )
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "message.record_failed",
                conversation_key=conversation_key,
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return None

        await self._registrar_telemetria(
            identificador,
            model,
            subagent,
            tokens_in,
            tokens_out,
            latency_ms,
            cache_read_tokens,
            cache_write_tokens,
        )
        return identificador

    async def _registrar_telemetria(
        self,
        message_id: uuid.UUID,
        model: str,
        subagent: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        cache_read_tokens: int | None,
        cache_write_tokens: int | None,
    ) -> None:
        custo = custo_em_dolar(model, tokens_in, tokens_out)
        if custo is None:
            log.warning("telemetry.unknown_model", model=model, message_id=str(message_id))

        try:
            async with self._session_factory() as session:
                session.add(
                    MessageTelemetry(
                        message_id=message_id,
                        model=model,
                        subagent=subagent,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cache_read_tokens=cache_read_tokens,
                        cache_write_tokens=cache_write_tokens,
                        cost_usd=custo,
                        latency_ms=latency_ms,
                    )
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "telemetry.record_failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        log.info(
            "telemetry.recorded",
            message_id=str(message_id),
            model=model,
            subagent=subagent,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            latency_ms=latency_ms,
        )

import re
import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import PRECOS_POR_MODELO
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import motivo_do_erro_de_banco

log = structlog.get_logger(__name__)

_MILIONESIMO_DE_DOLAR = Decimal("0.000001")


# Um snapshot datado e o MESMO modelo pelo MESMO preco:
# `claude-haiku-4-5-20251001` custa o que `claude-haiku-4-5` custa. Sem esta
# reducao a tabela precisaria de uma linha por data, e a primeira que faltasse
# viraria custo nulo -- foi exatamente o que aconteceu com `modelo_moderacao`,
# que e um ID datado e nunca teve entrada.
#
# So um sufixo de OITO digitos sai, e so no fim. Isso e estreito de proposito:
# nao e normalizacao generosa, e a unica reducao que a tabela de precos
# garante ser verdadeira. `claude-opus-9-20260101` continua devolvendo None,
# porque `claude-opus-9` tambem nao esta na tabela -- a lacuna continua
# aparecendo, que e o que o docstring abaixo promete.
_SEM_SNAPSHOT = re.compile(r"-\d{8}$")


# Multiplicadores do preco de ENTRADA para os dois lados do cache. Escrever
# custa agio, ler custa quase nada -- e a diferenca entre os dois e a razao de
# o cache valer a pena so quando o prefixo e reusado.
_AGIO_DE_ESCRITA_NO_CACHE = Decimal("1.25")
_DESCONTO_DE_LEITURA_NO_CACHE = Decimal("0.1")


def custo_em_dolar(
    model: str,
    tokens_in: int,
    tokens_out: int,
    cache_write: int = 0,
    cache_read: int = 0,
) -> Decimal | None:
    """Devolve None para modelo sem preco cadastrado, nunca zero.

    Zero somaria silenciosamente no painel de custo e faria o gasto parecer
    menor do que foi. None aparece como lacuna e alguem conserta.

    `cache_write` e `cache_read` existem desde a TEC-251, e sem eles esta
    funcao passou a MENTIR PARA BAIXO no dia em que o cache entrou: os tokens
    cacheados saem de `input_tokens` e vao para contadores proprios, entao um
    turno que antes reportava ~1.700 de entrada passou a reportar 54 -- e o
    custo caiu junto, sem que o gasto tivesse caido tanto.

    E o mesmo defeito que a TEC-249 consertou, entrando pela outra porta:
    subestimar em silencio e exatamente o que o paragrafo acima promete nao
    fazer. Os dois default zero mantem toda chamada antiga correta -- sem
    cache, nao ha o que somar.
    """
    preco = PRECOS_POR_MODELO.get(model) or PRECOS_POR_MODELO.get(_SEM_SNAPSHOT.sub("", model))
    if preco is None:
        return None
    entrada, saida = preco
    por_milhao = Decimal(1_000_000)
    total = (
        (Decimal(tokens_in) / por_milhao) * entrada
        + (Decimal(tokens_out) / por_milhao) * saida
        + (Decimal(cache_write) / por_milhao) * entrada * _AGIO_DE_ESCRITA_NO_CACHE
        + (Decimal(cache_read) / por_milhao) * entrada * _DESCONTO_DE_LEITURA_NO_CACHE
    )
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
                detail=motivo_do_erro_de_banco(exc),
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
        # Os tokens de cache entram na conta aqui pelo mesmo motivo que entram
        # no log do classificador: eles SAEM de `input_tokens` e vao para
        # contadores proprios, entao ignora-los faz `cost_usd` cair sem o
        # gasto ter caido. Subestimar em silencio e exatamente o que o
        # docstring de `custo_em_dolar` promete nao fazer.
        #
        # `or 0` porque os dois parametros sao `int | None`: `None` e "esta
        # chamada nao mediu cache" -- o caso das gravacoes anteriores a
        # TEC-231 --, e para a conta isso vale zero.
        custo = custo_em_dolar(
            model,
            tokens_in,
            tokens_out,
            cache_write=cache_write_tokens or 0,
            cache_read=cache_read_tokens or 0,
        )
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
                detail=motivo_do_erro_de_banco(exc),
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

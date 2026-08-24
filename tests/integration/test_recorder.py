import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.recorder import MessageRecorder, custo_em_dolar
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker


def recorder() -> MessageRecorder:
    return MessageRecorder(get_sessionmaker())


async def gravar(**extra) -> tuple[MessageRecorder, object]:
    argumentos = {
        "conversation_key": "5511911112222",
        "channel": "whatsapp",
        "text": "Ola! Em qual regiao voce procura?",
        "model": "claude-sonnet-5",
        "subagent": "qualificador",
        "tokens_in": 1200,
        "tokens_out": 180,
        "latency_ms": 1450,
    }
    argumentos.update(extra)
    instancia = recorder()
    return instancia, await instancia.record_agent_message(**argumentos)


async def test_grava_a_fala_do_agente_na_linha_do_tempo(session) -> None:
    _, message_id = await gravar()

    linha = await session.get(Message, message_id)
    assert linha is not None
    assert linha.role == MessageRole.AGENTE
    assert linha.direction == MessageDirection.OUTBOUND
    assert linha.conversation_key == "5511911112222"
    assert linha.status is None, "a fala do agente nao entra no pipeline de ingestao"
    assert linha.provider_message_id is None
    assert (
        decrypt(linha.text_body, aad_de(message_id, "text_body"))
        == "Ola! Em qual regiao voce procura?"
    )


async def test_telemetria_traz_tokens_custo_latencia_e_subagente(session) -> None:
    _, message_id = await gravar()

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.tokens_in == 1200
    assert telemetria.tokens_out == 180
    assert telemetria.latency_ms == 1450
    assert telemetria.subagent == "qualificador"
    assert telemetria.model == "claude-sonnet-5"
    assert telemetria.cost_usd == custo_em_dolar("claude-sonnet-5", 1200, 180)
    assert telemetria.cost_usd is not None and telemetria.cost_usd > 0


async def test_modelo_sem_preco_grava_lacuna_e_nao_zero(session, caplog) -> None:
    """Zero somaria silenciosamente no painel e faria o custo parecer menor."""
    with caplog.at_level(logging.WARNING):
        _, message_id = await gravar(model="modelo-que-nao-existe")

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.cost_usd is None
    assert "telemetry.unknown_model" in caplog.text


async def test_falha_de_telemetria_preserva_a_mensagem(session, caplog) -> None:
    """O criterio pede que a resposta seja entregue mesmo sem telemetria.

    `subagent` e VARCHAR(32): um valor maior estoura o INSERT da telemetria e
    so dele -- e uma falha de banco de verdade, nao um mock.
    """
    with caplog.at_level(logging.WARNING):
        _, message_id = await gravar(subagent="x" * 100)

    assert message_id is not None, "o recorder nao pode devolver None por causa da telemetria"

    linha = await session.get(Message, message_id)
    assert linha is not None, "a fala do agente sobrevive a falha de telemetria"

    ausente = await session.get(MessageTelemetry, message_id)
    assert ausente is None
    assert "telemetry.record_failed" in caplog.text


async def test_nunca_propaga_excecao(session) -> None:
    """Quem chama esta no meio de responder ao lead e nao pode ser derrubado."""
    _, message_id = await gravar(conversation_key="x" * 200)
    assert message_id is None


def test_custo_e_calculado_por_milhao_de_tokens() -> None:
    esperado = (Decimal(1200) / Decimal(1_000_000)) * Decimal("3.00") + (
        Decimal(180) / Decimal(1_000_000)
    ) * Decimal("15.00")
    assert custo_em_dolar("claude-sonnet-5", 1200, 180) == esperado.quantize(Decimal("0.000001"))


def test_modelo_desconhecido_nao_tem_custo() -> None:
    assert custo_em_dolar("modelo-que-nao-existe", 10, 10) is None


async def test_timeline_intercala_entrada_e_saida_da_mesma_conversa(session) -> None:
    """A consulta que TEC-127 faz a cada turno.

    `sender` e `recipient` se invertem entre as direcoes; `conversation_key`
    nao -- e por isso que ela existe.
    """
    base = datetime.now(UTC) - timedelta(minutes=10)
    entrada = _uuid.uuid4()
    session.add(
        Message(
            id=entrada,
            channel="whatsapp",
            provider_message_id="wamid.TIMELINE",
            sender_external_id="5511911112222",
            recipient_external_id="222222222",
            conversation_key="5511911112222",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=base,
        )
    )
    await session.commit()

    _, saida = await gravar(conversation_key="5511911112222")

    # Outra conversa, para provar que o agrupamento nao vaza.
    _, outra = await gravar(conversation_key="5511999998888")

    linhas = (
        await session.scalars(
            select(Message)
            .where(Message.channel == "whatsapp", Message.conversation_key == "5511911112222")
            .order_by(Message.created_at.desc())
            .limit(20)
        )
    ).all()

    assert [linha.id for linha in linhas] == [saida, entrada]
    assert outra not in [linha.id for linha in linhas]
    assert [linha.direction for linha in linhas] == [
        MessageDirection.OUTBOUND,
        MessageDirection.INBOUND,
    ]

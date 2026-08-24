"""Criterios de aceite do TEC-126 como testes executaveis.

Cada teste corresponde a um cenario Gherkin da historia. Ha sobreposicao
deliberada com os testes de unidade e integracao: estes existem para que o
criterio de aceite tenha um endereco, nao para cobrir codigo novo.
"""

import logging

import structlog
from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.messages.schemas import parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker

TELEFONE = "5511987654321"


def envelope(texto: str = "quero apto na zona sul") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [
                                {
                                    "id": "wamid.CRITERIO",
                                    "from": TELEFONE,
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


async def test_registrar_mensagem_de_entrada_do_lead(session, redis_pool) -> None:
    """Cenario: Registrar mensagem de entrada do lead."""
    servico = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await servico.ingest(parse_meta_envelope(envelope()))

    linha = await session.get(Message, message_id)
    assert linha is not None
    assert linha.role == MessageRole.LEAD
    assert linha.channel == "whatsapp"
    assert linha.content_type == MessageContentType.TEXTO
    assert linha.direction == MessageDirection.INBOUND
    assert linha.created_at is not None


async def test_registrar_resposta_do_agente_com_custo(session) -> None:
    """Cenario: Registrar resposta do agente com custo."""
    recorder = MessageRecorder(get_sessionmaker())

    message_id = await recorder.record_agent_message(
        conversation_key=TELEFONE,
        channel="whatsapp",
        text="Ola! Em qual regiao voce procura?",
        model="claude-sonnet-5",
        subagent="qualificador",
        tokens_in=1200,
        tokens_out=180,
        latency_ms=1450,
    )

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.tokens_in == 1200
    assert telemetria.tokens_out == 180
    assert telemetria.cost_usd is not None and telemetria.cost_usd > 0
    assert telemetria.latency_ms == 1450
    assert telemetria.subagent == "qualificador"


async def test_conteudo_pessoal_nao_vaza_para_o_log(session, redis_pool, caplog) -> None:
    """Cenario: Conteudo pessoal nao vaza para o log.

    Duas linhas de defesa, testadas separadamente. A primeira e a real no
    caminho de ingestao: `service.py` e `schemas.py` nunca colocam
    `sender_external_id` ou `text_body` num event dict, entao os eventos
    emitidos (`message.received`, `message.queued`) so carregam uuids e
    canal -- o telefone e o texto simplesmente nao chegam ao logger. As
    duas assercoes de ausencia abaixo comprovam isso, nao que algo tenha
    sido mascarado; se provassem mascaramento seriam um passe vazio, o
    modo de falha que o brief desta tarefa aponta.

    A segunda linha de defesa e o processor `_mascarar_pii` de
    `app/logging.py`, para o dia em que um log statement passar a carregar
    o numero. Esse caminho so e exercitado de verdade emitindo um evento
    que carrega o telefone por um logger configurado pelo `configure_logging`
    real (fixture `configurar_logging`, autouse) -- nao chamando o processor
    diretamente -- e verificando que o que chega ao caplog e a forma
    mascarada, nunca o numero em claro.
    """
    servico = IngestionService(get_sessionmaker(), redis_pool)

    with caplog.at_level(logging.INFO):
        (message_id,) = await servico.ingest(
            parse_meta_envelope(envelope(f"me liga no {TELEFONE}"))
        )

    assert TELEFONE not in caplog.text
    assert "zona sul" not in caplog.text

    cru = await session.scalar(
        sql("SELECT text_body FROM messages WHERE id = :id"), {"id": message_id}
    )
    assert TELEFONE.encode() not in bytes(cru)
    assert decrypt(bytes(cru), aad_de(message_id, "text_body")) == f"me liga no {TELEFONE}"

    caplog.clear()
    log = structlog.get_logger("teste.criterio")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", sender_external_id=TELEFONE)

    assert TELEFONE not in caplog.text
    assert "*********4321" in caplog.text


async def test_falha_de_telemetria_nao_derruba_o_atendimento(session, caplog) -> None:
    """Cenario: Falha de telemetria nao derruba o atendimento."""
    recorder = MessageRecorder(get_sessionmaker())

    with caplog.at_level(logging.WARNING):
        message_id = await recorder.record_agent_message(
            conversation_key=TELEFONE,
            channel="whatsapp",
            text="Ola! Em qual regiao voce procura?",
            model="claude-sonnet-5",
            subagent="x" * 100,
            tokens_in=1200,
            tokens_out=180,
            latency_ms=1450,
        )

    assert message_id is not None
    assert await session.get(Message, message_id) is not None
    assert await session.get(MessageTelemetry, message_id) is None
    assert "telemetry.record_failed" in caplog.text

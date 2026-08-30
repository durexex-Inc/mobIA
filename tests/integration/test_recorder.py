import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from mobia.app.config import PRECOS_POR_MODELO
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
    """Testa a ARITMETICA, lendo o preco da tabela em vez de repeti-lo.

    Antes esta funcao trazia `3.00`/`15.00` escritos a mao. Isso duplicava a
    constante, entao ela so pegava erro de formula -- nunca erro de preco --,
    e passou verde durante todo o tempo em que a tabela dizia que o sonnet-5
    custava o preco do sonnet-4-6. Quem guarda o preco e o teste abaixo.
    """
    entrada, saida = PRECOS_POR_MODELO["claude-sonnet-5"]
    esperado = (Decimal(1200) / Decimal(1_000_000)) * entrada + (
        Decimal(180) / Decimal(1_000_000)
    ) * saida
    assert custo_em_dolar("claude-sonnet-5", 1200, 180) == esperado.quantize(Decimal("0.000001"))


def test_precos_batem_com_a_tabela_publicada() -> None:
    """O preco em si, que o teste de aritmetica acima nao pode guardar.

    Existe porque a tabela ja esteve errada: `claude-sonnet-5` estava com
    $3/$15, que sao os precos do `claude-sonnet-4-6`. Enquanto o agente rodava
    em opus-5 isso era so um numero errado num dicionario; no dia em que
    `modelo_agente` virou sonnet-5, virou 50% de erro na telemetria de custo
    de todo turno de producao.
    """
    assert PRECOS_POR_MODELO["claude-opus-5"] == (Decimal("5.00"), Decimal("25.00"))
    assert PRECOS_POR_MODELO["claude-sonnet-5"] == (Decimal("2.00"), Decimal("10.00"))
    assert PRECOS_POR_MODELO["claude-haiku-4-5"] == (Decimal("1.00"), Decimal("5.00"))


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


async def test_tokens_de_cache_sao_gravados_quando_informados(session) -> None:
    """TEC-127 reenvia uma janela de 20 mensagens a cada turno -- e a carga
    canonica de prompt caching. Capturar o numero desde a primeira linha e a
    parte que nao da para recuperar depois."""
    _, message_id = await gravar(cache_read_tokens=9000, cache_write_tokens=1200)

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.cache_read_tokens == 9000
    assert telemetria.cache_write_tokens == 1200


async def test_tokens_de_cache_sao_opcionais(session) -> None:
    """Sem agente ligado, quem chama ainda nao tem esses numeros."""
    _, message_id = await gravar()

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.cache_read_tokens is None
    assert telemetria.cache_write_tokens is None


async def test_custo_ignora_tokens_de_cache_por_ora(session) -> None:
    """Precificacao ciente de cache fica para a historia que liga o agente.

    Sem agente nao ha forma de uso real para tarifar, e inventar taxa agora
    seria chute materializado no historico de custo.
    """
    _, com_cache = await gravar(cache_read_tokens=50_000, cache_write_tokens=50_000)

    telemetria = await session.get(MessageTelemetry, com_cache)
    assert telemetria is not None
    assert telemetria.cost_usd == custo_em_dolar("claude-sonnet-5", 1200, 180)


def test_snapshot_datado_custa_o_mesmo_que_o_modelo_base() -> None:
    """`claude-haiku-4-5-20251001` e o mesmo modelo que `claude-haiku-4-5`.

    Sem a reducao do sufixo, `modelo_moderacao` -- que e um ID datado -- nunca
    achava preco, e a moderacao ficaria com custo nulo no dia em que ganhasse
    telemetria. Uma linha por data na tabela seria a alternativa, e a primeira
    que faltasse reabriria o buraco.
    """
    assert custo_em_dolar("claude-haiku-4-5-20251001", 1000, 100) == custo_em_dolar(
        "claude-haiku-4-5", 1000, 100
    )


def test_a_reducao_de_snapshot_nao_inventa_preco_para_modelo_desconhecido() -> None:
    """A reducao e estreita de proposito: ela resolve a data, nao o modelo.

    Um modelo que nao esta na tabela continua devolvendo None mesmo com
    sufixo de data -- a lacuna continua aparecendo, que e o que o docstring de
    `custo_em_dolar` promete.
    """
    assert custo_em_dolar("modelo-que-nao-existe-20260101", 10, 10) is None
    assert custo_em_dolar("claude-haiku-4-5-2025", 10, 10) is None

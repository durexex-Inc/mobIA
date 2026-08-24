import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus
from mobia.infra.crypto import aad_de, decrypt, decrypt_json, encrypt, encrypt_json


def test_statuses_reivindicaveis() -> None:
    """Só PROCESSED é terminal: FAILED tem de ser reivindicável para o retry do ARQ."""
    assert CLAIMABLE_STATUSES == (
        MessageStatus.RECEIVED,
        MessageStatus.QUEUED,
        MessageStatus.PROCESSING,
        MessageStatus.FAILED,
    )
    assert MessageStatus.PROCESSED not in CLAIMABLE_STATUSES


def nova_mensagem(
    provider_message_id: str,
    channel: str = "whatsapp",
    raw_payload: dict[str, Any] | None = None,
) -> Message:
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        channel=channel,
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        conversation_key="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("oi", aad_de(identificador, "text_body")),
        raw_payload=encrypt_json(raw_payload, aad_de(identificador, "raw_payload")),
        status=MessageStatus.RECEIVED,
    )


async def test_persiste_mensagem_com_defaults(session) -> None:
    message = nova_mensagem("wamid.PERSIST")
    session.add(message)
    await session.commit()

    resultado = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.PERSIST")
    )
    assert resultado is not None
    assert isinstance(resultado.id, uuid.UUID)
    assert resultado.role == MessageRole.LEAD
    assert resultado.direction == MessageDirection.INBOUND
    assert resultado.conversation_key == "5511911112222"
    assert resultado.content_type == MessageContentType.TEXTO
    assert resultado.created_at is not None
    assert resultado.attempts == 0
    assert resultado.queued_at is None
    assert resultado.processed_at is None
    assert resultado.last_error is None
    assert decrypt(resultado.text_body, aad_de(resultado.id, "text_body")) == "oi"


async def test_id_sem_valor_explicito_usa_o_default_de_uuid4(session) -> None:
    """Todo outro teste passa `id=` na hora de montar o AAD -- este cobre quem nao passa."""
    message = Message(
        channel="whatsapp",
        provider_message_id="wamid.SEM_ID_EXPLICITO",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        conversation_key="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
        status=MessageStatus.RECEIVED,
    )
    session.add(message)
    await session.commit()

    assert isinstance(message.id, uuid.UUID)
    resultado = await session.get(Message, message.id)
    assert resultado is not None


async def test_raw_payload_persiste_cifrado_e_decifra_pelo_orm(session) -> None:
    """Todo outro teste do arquivo grava `raw_payload=None` -- este cobre o caminho com dado."""
    payload = {"id": "wamid.PAYLOAD", "envelope": {"tipo": "text"}}
    message = nova_mensagem("wamid.RAW_PAYLOAD", raw_payload=payload)
    session.add(message)
    await session.commit()

    resultado = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.RAW_PAYLOAD")
    )
    assert resultado is not None
    assert decrypt_json(resultado.raw_payload, aad_de(resultado.id, "raw_payload")) == payload


async def test_linha_de_saida_nasce_sem_status(session) -> None:
    """A fala do agente nao participa do pipeline de ingestao.

    Se ela nascesse com o default RECEIVED, o sweeper do TEC-122 varreria a
    propria resposta do agente e a enfileiraria para processamento.
    """
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel="whatsapp",
            provider_message_id=None,
            sender_external_id=None,
            recipient_external_id=None,
            conversation_key="5511911112222",
            role=MessageRole.AGENTE,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(
                "Ola! Em qual regiao voce procura?", aad_de(identificador, "text_body")
            ),
            raw_payload=None,
            status=None,
        )
    )
    await session.commit()

    linha = await session.get(Message, identificador)
    assert linha is not None
    assert linha.status is None
    assert linha.provider_message_id is None


async def test_varias_linhas_de_saida_convivem(session) -> None:
    """A UNIQUE (channel, provider_message_id) sobrevive ao nullable.

    Postgres nao considera dois NULLs iguais, entao as linhas de saida nao
    colidem entre si nem enfraquecem a dedup do TEC-125.
    """
    for _ in range(3):
        identificador = uuid.uuid4()
        session.add(
            Message(
                id=identificador,
                channel="whatsapp",
                provider_message_id=None,
                conversation_key="5511911112222",
                role=MessageRole.AGENTE,
                direction=MessageDirection.OUTBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=None,
                raw_payload=None,
                status=None,
            )
        )
    await session.commit()

    total = await session.scalar(text("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'"))
    assert total == 3


async def test_telemetria_e_um_para_um_com_a_mensagem(session) -> None:
    message = nova_mensagem("wamid.TELEMETRIA")
    session.add(message)
    await session.commit()

    session.add(
        MessageTelemetry(
            message_id=message.id,
            model="claude-sonnet-5",
            subagent="qualificador",
            tokens_in=1200,
            tokens_out=180,
            cost_usd=Decimal("0.006300"),
            latency_ms=1450,
        )
    )
    await session.commit()

    linha = await session.get(MessageTelemetry, message.id)
    assert linha is not None
    assert linha.cost_usd == Decimal("0.006300")

    session.add(
        MessageTelemetry(
            message_id=message.id,
            model="outro",
            subagent="roteador",
            tokens_in=1,
            tokens_out=1,
            cost_usd=None,
            latency_ms=1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_provider_message_id_e_unico_por_canal(session) -> None:
    """TEC-125: a unicidade vive no banco, nao so em memoria."""
    session.add(nova_mensagem("wamid.DUPLICADO"))
    await session.commit()

    session.add(nova_mensagem("wamid.DUPLICADO"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    linhas = (
        await session.scalars(
            select(Message).where(Message.provider_message_id == "wamid.DUPLICADO")
        )
    ).all()
    assert len(linhas) == 1


async def test_mesmo_id_em_canais_diferentes_convive(session) -> None:
    """A UNIQUE e composta com `channel`: o widget web (TEC-124) tem espaco de ids proprio."""
    session.add(nova_mensagem("id.COMPARTILHADO", channel="whatsapp"))
    session.add(nova_mensagem("id.COMPARTILHADO", channel="web"))
    await session.commit()

    linhas = (
        await session.scalars(
            select(Message).where(Message.provider_message_id == "id.COMPARTILHADO")
        )
    ).all()
    assert {linha.channel for linha in linhas} == {"whatsapp", "web"}


async def test_colunas_reservadas_nascem_nulas(session) -> None:
    """`envelope_context` (TEC-217) e `claimed_at` (TEC-218) entram no esquema sem escritor."""
    session.add(nova_mensagem("wamid.RESERVADAS"))
    await session.commit()

    linha = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.RESERVADAS")
    )
    assert linha.envelope_context is None
    assert linha.claimed_at is None


@pytest.mark.parametrize("coluna", ["text_body", "raw_payload"])
def test_texto_claro_nas_colunas_cifradas_e_recusado(coluna: str) -> None:
    """Fecha por construcao o canal de vazamento pelo texto da excecao.

    Sem a guarda, o asyncpg monta a mensagem de erro dele com o valor ofensivo
    dentro antes de a SQLAlchemy ver qualquer coisa, e `hide_parameters=True`
    nao alcanca isso. O texto chega ao log via `detail=str(exc)`, e frase livre
    nao e pega pelo mascarador de digitos.
    """
    with pytest.raises(TypeError) as erro:
        Message(**{coluna: "quero apto na zona sul, telefone 5511987654321"})

    assert coluna in str(erro.value)
    assert "zona sul" not in str(erro.value)
    assert "5511987654321" not in str(erro.value)


@pytest.mark.parametrize("valor", [None, b"\x01cifrado", bytearray(b"\x01cifrado")])
def test_bytes_e_none_atravessam_a_guarda(valor: object) -> None:
    assert Message(text_body=valor).text_body == valor

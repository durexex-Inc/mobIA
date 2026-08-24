import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus


def test_statuses_reivindicaveis() -> None:
    """Só PROCESSED é terminal: FAILED tem de ser reivindicável para o retry do ARQ."""
    assert CLAIMABLE_STATUSES == (
        MessageStatus.RECEIVED,
        MessageStatus.QUEUED,
        MessageStatus.PROCESSING,
        MessageStatus.FAILED,
    )
    assert MessageStatus.PROCESSED not in CLAIMABLE_STATUSES


async def test_persiste_mensagem_com_defaults(session) -> None:
    message = Message(
        channel="whatsapp",
        provider_message_id="wamid.PERSIST",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="oi",
        raw_payload={"id": "wamid.PERSIST", "type": "text"},
        status=MessageStatus.RECEIVED,
    )
    session.add(message)
    await session.commit()

    resultado = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.PERSIST")
    )
    assert resultado is not None
    assert isinstance(resultado.id, uuid.UUID)
    assert resultado.status == MessageStatus.RECEIVED
    assert resultado.attempts == 0
    assert resultado.received_at is not None
    assert resultado.queued_at is None
    assert resultado.processed_at is None
    assert resultado.last_error is None
    assert resultado.raw_payload["type"] == "text"


def nova_mensagem(provider_message_id: str, channel: str = "whatsapp") -> Message:
    return Message(
        channel=channel,
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="oi",
        raw_payload={},
        status=MessageStatus.RECEIVED,
    )


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

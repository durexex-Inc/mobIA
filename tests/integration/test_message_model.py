import uuid

from sqlalchemy import select

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


async def test_provider_message_id_ainda_nao_e_unico(session) -> None:
    """A UNIQUE de dedup entra no TEC-125; hoje duas linhas iguais convivem."""
    for _ in range(2):
        session.add(
            Message(
                channel="whatsapp",
                provider_message_id="wamid.DUPLICADO",
                sender_external_id="5511911112222",
                recipient_external_id="222222222",
                content_type="text",
                text_body="oi",
                raw_payload={},
                status=MessageStatus.RECEIVED,
            )
        )
    await session.commit()

    linhas = (
        await session.scalars(
            select(Message).where(Message.provider_message_id == "wamid.DUPLICADO")
        )
    ).all()
    assert len(linhas) == 2

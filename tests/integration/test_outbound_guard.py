import uuid
from typing import Any

from sqlalchemy import func, select

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.noop import NoopOutbound
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[tuple[uuid.UUID, str]] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregas.append((message_id, kind))


async def criar_mensagem(session) -> uuid.UUID:
    identificador = uuid.uuid4()
    message = Message(
        id=identificador,
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        conversation_key="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("oi", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.RECEIVED,
    )
    session.add(message)
    await session.commit()
    return message.id


async def test_primeiro_envio_reserva_e_entrega(session) -> None:
    message_id = await criar_mensagem(session)
    outbound = OutboundEspiao(get_sessionmaker())

    assert await outbound.send(message_id, "ack", {}) is True
    assert outbound.entregas == [(message_id, "ack")]

    total = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert total == 1


async def test_segundo_envio_do_mesmo_par_e_suprimido(session, caplog) -> None:
    message_id = await criar_mensagem(session)
    outbound = OutboundEspiao(get_sessionmaker())

    await outbound.send(message_id, "ack", {})
    with caplog.at_level("INFO"):
        assert await outbound.send(message_id, "ack", {}) is False

    assert len(outbound.entregas) == 1, "a reentrega nao pode disparar efeito externo"
    total = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert total == 1
    assert "outbound.duplicate_suppressed" in caplog.text


async def test_kinds_diferentes_nao_colidem(session) -> None:
    message_id = await criar_mensagem(session)
    outbound = OutboundEspiao(get_sessionmaker())

    assert await outbound.send(message_id, "ack", {}) is True
    assert await outbound.send(message_id, "reply", {}) is True
    assert len(outbound.entregas) == 2


async def test_noop_outbound_reserva_sem_efeito_externo(session) -> None:
    message_id = await criar_mensagem(session)
    outbound = NoopOutbound(get_sessionmaker())

    assert await outbound.send(message_id, "ack", {}) is True
    assert await outbound.send(message_id, "ack", {}) is False

    total = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert total == 1

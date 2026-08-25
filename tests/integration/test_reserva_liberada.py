import uuid
from typing import Any

from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel, GuardedOutbound
from mobia.infra.db import get_sessionmaker

KIND = "reply"


class OutboundQueFalha(GuardedOutbound):
    """Falha as primeiras `falhas` tentativas, depois entrega."""

    def __init__(self, session_factory, erro: Exception, falhas: int = 1) -> None:
        super().__init__(session_factory)
        self._erro = erro
        self._falhas = falhas
        self.entregues: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        if self._falhas > 0:
            self._falhas -= 1
            raise self._erro
        self.entregues.append(message_id)


async def uma_mensagem(session) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel="whatsapp",
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key="5511911112222",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()
    return identificador


async def reservas(session, message_id: uuid.UUID) -> int:
    return await session.scalar(
        sql("SELECT count(*) FROM outbound_dispatches WHERE message_id = :m"),
        {"m": message_id},
    )


async def test_falha_retentavel_libera_a_reserva(session) -> None:
    """Sem isso, a resposta ao lead se perde em silencio e para sempre.

    A reserva ja esta commitada quando o envio falha, entao o sweeper
    reenfileira, o worker reivindica, e a guarda responde "ja entreguei isso".
    A Marina nunca recebe nada sobre aquele turno.
    """
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await reservas(session, message_id) == 0, "a reserva tem de sair do caminho"


async def test_apos_liberar_a_retentativa_entrega(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await outbound.send(message_id, KIND, {}) is True
    assert outbound.entregues == [message_id]


async def test_falha_permanente_mantem_a_reserva(session) -> None:
    """4xx nao volta a dar certo. Retentar so queima chamada de modelo."""
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRecusado("payload invalido"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRecusado:
        pass

    assert await reservas(session, message_id) == 1


async def test_apos_falha_permanente_a_retentativa_e_no_op(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRecusado("payload invalido"), falhas=1)

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRecusado:
        pass

    assert await outbound.send(message_id, KIND, {}) is False
    assert outbound.entregues == [], "a guarda suprimiu, nada foi entregue"


async def test_entrega_bem_sucedida_mantem_a_reserva(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)

    assert await outbound.send(message_id, KIND, {}) is True
    assert await reservas(session, message_id) == 1

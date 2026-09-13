"""A guarda que cala o agente na porta de saida. TEC-179, RN-16.4."""

import uuid
from typing import Any

import pytest

from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.db import get_sessionmaker

pytestmark = pytest.mark.asyncio

CHANNEL = "whatsapp"
CHAVE = "5511988887777"


class OutboundEspiao(GuardedOutbound):
    """Registra o que chegou a `_deliver` -- e o que a guarda deixou passar."""

    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[tuple[uuid.UUID, str]] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregas.append((message_id, kind))


async def test_conversa_assumida_nao_recebe_nada_do_agente(
    session, semear_corretor, banco_limpo
) -> None:
    """A guarda barra TODO kind -- nao ha escotilha (D5 do desenho).

    Se algum dia alguem acrescentar uma excecao por `kind` aqui, este teste
    reprova, e e o alarme certo: a rota de envio manual do corretor tem de
    decidir isso explicitamente, nao herda-la por acidente.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    mensagem = Message(
        id=uuid.uuid4(),
        channel=CHANNEL,
        conversation_key=CHAVE,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status="PROCESSED",
    )
    session.add(mensagem)
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor.id)
    await session.commit()

    outbound = OutboundEspiao(get_sessionmaker())
    assert await outbound.send(mensagem.id, "texto", {"body": "oi"}) is False
    assert outbound.entregas == []


async def test_conversa_devolvida_volta_a_receber(session, banco_limpo) -> None:
    """Prova que a guarda le o estado CORRENTE, nao "ja foi assumida um dia"."""
    mensagem = Message(
        id=uuid.uuid4(),
        channel=CHANNEL,
        conversation_key=CHAVE,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status="PROCESSED",
    )
    session.add(mensagem)
    await session.commit()

    outbound = OutboundEspiao(get_sessionmaker())
    assert await outbound.send(mensagem.id, "texto", {"body": "oi"}) is True
    assert outbound.entregas == [(mensagem.id, "texto")]

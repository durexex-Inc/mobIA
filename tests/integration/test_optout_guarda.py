"""A guarda de opt-out na porta de saida.

Nenhum teste aqui passa por `executar_turno` -- eles chamam `outbound.send`
direto, que e exatamente o que a TEC-183 (cadencia de follow-up) vai fazer. Se
a guarda estivesse no turno em vez de na porta, os tres passariam sem barrar
nada: e essa a prova central do desenho desta task.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agente.turno import KIND_DA_CONFIRMACAO_DE_OPTOUT, KIND_DA_RESPOSTA
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import registrar_optout
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import GuardedOutbound


class _OutboundQueEntrega(GuardedOutbound):
    """Registra o que foi entregue, sem falar com a Meta."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(session_factory)
        self.entregues: list[str] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregues.append(kind)


async def _mensagem_gravada(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> Message:
    """Uma `Message` minima, so com as colunas obrigatorias, ja commitada.

    Espelha `_mensagem_do_lead` de `tests/integration/test_optout_repositorio.py`
    (Task 3): sem `text_body`, porque a guarda so olha `channel` e
    `conversation_key` -- o corpo da fala nao entra na decisao.
    """
    mensagem = Message(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
        status=None,
    )
    session.add(mensagem)
    await session.commit()
    return mensagem


async def test_lead_em_optout_nao_recebe_e_nao_reserva(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A guarda barra ANTES da reserva.

    Barrar depois deixaria linha orfa em `outbound_dispatches`, e o sweeper
    leria isso como tentativa feita.
    """
    mensagem = await _mensagem_gravada(session, channel="wa", conversation_key="5548999998888")
    await registrar_optout(
        session_factory,
        channel="wa",
        conversation_key="5548999998888",
        message_id=mensagem.id,
    )
    outbound = _OutboundQueEntrega(session_factory)

    entregue = await outbound.send(mensagem.id, KIND_DA_RESPOSTA, {"texto": "oi"})

    assert entregue is False
    assert outbound.entregues == []
    reservas = (
        await session.execute(select(func.count()).select_from(OutboundDispatch))
    ).scalar_one()
    assert reservas == 0


async def test_a_confirmacao_do_proprio_optout_atravessa(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O unico envio permitido depois do registro.

    Sem esta excecao o lead nunca saberia que o pedido dele foi atendido.
    """
    mensagem = await _mensagem_gravada(session, channel="wa", conversation_key="5548999998888")
    await registrar_optout(
        session_factory,
        channel="wa",
        conversation_key="5548999998888",
        message_id=mensagem.id,
    )
    outbound = _OutboundQueEntrega(session_factory)

    entregue = await outbound.send(mensagem.id, KIND_DA_CONFIRMACAO_DE_OPTOUT, {"texto": "pronto"})

    assert entregue is True
    assert outbound.entregues == [KIND_DA_CONFIRMACAO_DE_OPTOUT]


async def test_lead_sem_optout_recebe_normalmente(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A guarda nao pode barrar quem nunca pediu nada."""
    mensagem = await _mensagem_gravada(session, channel="wa", conversation_key="5548911112222")
    outbound = _OutboundQueEntrega(session_factory)

    assert await outbound.send(mensagem.id, KIND_DA_RESPOSTA, {"texto": "oi"}) is True
    assert outbound.entregues == [KIND_DA_RESPOSTA]

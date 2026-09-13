"""A guarda que cala o agente na porta de saida. TEC-179, RN-16.4."""

import uuid
from typing import Any

import pytest

from mobia.domain.atendimento.repositorio import assumir, devolver
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.deteccao import KIND_DA_CONFIRMACAO_DE_OPTOUT
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
    """A guarda barra todo kind, exceto o unico que a emenda (TEC-179, Task 7)
    abriu: `KIND_DA_CONFIRMACAO_DE_OPTOUT` -- ver
    `test_confirmacao_de_optout_atravessa_a_guarda_de_atendimento_humano`
    logo abaixo. Este teste usa `kind="texto"`, que continua sem escotilha
    nenhuma: se algum dia alguem acrescentar uma excecao por `kind` que nao
    seja essa, este teste reprova, e e o alarme certo -- a rota de envio
    manual do corretor tem de decidir isso explicitamente, nao herda-la por
    acidente.
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


async def test_confirmacao_de_optout_atravessa_a_guarda_de_atendimento_humano(
    session, semear_corretor, banco_limpo
) -> None:
    """A emenda TEC-179 (Task 7): `KIND_DA_CONFIRMACAO_DE_OPTOUT` e a UNICA
    excecao a guarda de atendimento humano, espelhando a excecao que a guarda
    de opt-out ja tinha.

    Sem isto, um lead que pede opt-out numa conversa assumida teria o pedido
    REGISTRADO (correcao no turno, ver `test_turno_atendimento_humano.py`) mas
    a confirmacao dele barrada bem aqui, pela guarda que a conversa assumida
    ativa -- o lead pediria para sair e nunca veria reconhecimento nenhum.
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
    assert (
        await outbound.send(mensagem.id, KIND_DA_CONFIRMACAO_DE_OPTOUT, {"body": "confirmacao"})
        is True
    )
    assert outbound.entregas == [(mensagem.id, KIND_DA_CONFIRMACAO_DE_OPTOUT)]


async def test_conversa_devolvida_volta_a_receber(session, semear_corretor, banco_limpo) -> None:
    """Prova que a guarda le o estado CORRENTE, nao "ja foi assumida um dia".

    Achado da revisao final (Important): a versao anterior deste teste nunca
    chamava `assumir` nem `devolver` -- so provava o default (sem linha, nao
    silenciada), nao a devolucao. Este exercita o ciclo completo: assume,
    commita, devolve, commita, e so entao manda -- e o unico teste do
    arquivo que fala em devolucao, entao e ele quem tem de pegar uma
    regressao em `devolver`.
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
    await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor.id)
    await session.commit()

    outbound = OutboundEspiao(get_sessionmaker())
    assert await outbound.send(mensagem.id, "texto", {"body": "oi"}) is True
    assert outbound.entregas == [(mensagem.id, "texto")]

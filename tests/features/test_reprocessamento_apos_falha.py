"""Cenario Gherkin de TEC-122: nao perder mensagem em falha do worker."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import claim_message, process_message


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregas.append(message_id)


class QuedaDoWorker(RuntimeError):
    pass


class OutboundQueCai(OutboundEspiao):
    """Registra a entrega e so entao levanta.

    Reproduz a janela que o cenario 3 precisa exercitar: o efeito externo ja
    saiu, mas a linha ainda nao chegou a PROCESSED.
    """

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        await super()._deliver(message_id, kind, payload)
        raise QuedaDoWorker("worker morto no meio do processamento")


async def enfileirada(session, status: str = MessageStatus.QUEUED) -> uuid.UUID:
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
        text_body=encrypt("ainda tem o 2 quartos?", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=status,
    )
    session.add(message)
    await session.commit()
    return message.id


async def test_processa_mensagem_enfileirada(session) -> None:
    message_id = await enfileirada(session)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    assert await process_message(ctx, str(message_id)) == "processed"

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.processed_at is not None
    assert outbound.entregas == [message_id]


async def test_mensagem_ja_processada_e_ignorada(session) -> None:
    message_id = await enfileirada(session, status=MessageStatus.PROCESSED)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    assert await process_message(ctx, str(message_id)) == "skipped"
    assert outbound.entregas == []


async def test_claim_recusa_status_terminal(session) -> None:
    message_id = await enfileirada(session, status=MessageStatus.PROCESSED)
    async with get_sessionmaker()() as sessao:
        assert await claim_message(sessao, message_id) is False


async def test_claim_aceita_processing_para_permitir_retomada(session) -> None:
    """PROCESSING e o estado que um worker morto deixa; tem de ser reivindicavel."""
    message_id = await enfileirada(session, status=MessageStatus.PROCESSING)
    async with get_sessionmaker()() as sessao:
        assert await claim_message(sessao, message_id) is True
        await sessao.commit()


async def test_claim_simultaneo_faz_o_segundo_worker_perder_limpo(session) -> None:
    """Dois workers na mesma mensagem ao mesmo tempo.

    Sem o SELECT ... FOR UPDATE SKIP LOCKED o segundo bloqueava no lock do
    primeiro, reavaliava o predicado contra a linha ja em PROCESSING -- que
    continua reivindicavel -- e reivindicava tambem, dobrando o trabalho.
    """
    message_id = await enfileirada(session)
    session_factory = get_sessionmaker()

    async with session_factory() as primeiro, session_factory() as segundo:
        # O primeiro nao commita: mantem o lock da linha, como um job em curso.
        assert await claim_message(primeiro, message_id) is True
        perdedor = await asyncio.wait_for(claim_message(segundo, message_id), timeout=5)
        assert perdedor is False, "o segundo worker tem de sair como no-op"
        await primeiro.commit()


async def test_nao_perder_mensagem_em_falha_do_worker(session) -> None:
    """Cenario: Nao perder mensagem em falha do worker.

    Dada uma mensagem ja enfileirada e um worker interrompido durante o
    processamento, quando o worker e reiniciado, a mensagem volta a ser
    processada e nenhuma resposta duplicada e enviada ao lead.
    """
    message_id = await enfileirada(session)

    # Worker interrompido logo depois da entrega, antes de marcar PROCESSED.
    caido = OutboundQueCai(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": caido}
    with pytest.raises(QuedaDoWorker):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.FAILED
    assert linha.attempts == 1
    assert len(caido.entregas) == 1

    # Worker reiniciado: instancia nova, sem a falha.
    reiniciado = OutboundEspiao(get_sessionmaker())
    ctx["outbound"] = reiniciado
    assert await process_message(ctx, str(message_id)) == "processed"

    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert reiniciado.entregas == [], "a guarda suprime a reentrega"
    assert await session.scalar(select(func.count()).select_from(OutboundDispatch)) == 1


async def test_mensagem_em_received_tambem_e_processavel(session) -> None:
    """Cobre a linha que o sweeper recupera: nunca chegou a ficar QUEUED."""
    message_id = await enfileirada(session, status=MessageStatus.RECEIVED)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    assert await process_message(ctx, str(message_id)) == "processed"
    assert outbound.entregas == [message_id]


async def test_mensagem_inexistente_e_ignorada() -> None:
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}
    assert await process_message(ctx, str(uuid.uuid4())) == "skipped"

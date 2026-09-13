import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import func, select

from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.sweep_stalled import sweep_stalled


def _ctx_do_turno(session_factory, outbound) -> dict:
    """`process_message` roda o turno inteiro desde a TEC-134 -- ver o mesmo
    helper em `tests/features/test_reprocessamento_apos_falha.py`."""
    return {
        "session_factory": session_factory,
        "outbound": outbound,
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
    }


async def mensagem(
    session,
    status: str,
    idade_segundos: int,
    attempts: int = 0,
) -> uuid.UUID:
    instante = datetime.now(UTC) - timedelta(seconds=idade_segundos)
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
        status=status,
        attempts=attempts,
        created_at=instante,
        queued_at=instante if status != MessageStatus.RECEIVED else None,
    )
    session.add(message)
    await session.commit()
    return message.id


def contexto(redis_pool, settings) -> dict:
    return {
        "session_factory": get_sessionmaker(),
        "redis": redis_pool,
        "settings": settings,
    }


async def test_reenfileira_received_parado(session, redis_pool, settings) -> None:
    message_id = await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1

    jobs = await redis_pool.queued_jobs()
    assert [job.args for job in jobs] == [(str(message_id),)]

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.attempts == 0, "varrer nao e tentar processar: o sweeper nao cobra attempts"


async def test_nao_toca_em_received_recente(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.RECEIVED, idade_segundos=5)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_reenfileira_processing_travado(session, redis_pool, settings) -> None:
    message_id = await mensagem(session, MessageStatus.PROCESSING, idade_segundos=3600)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1
    assert [job.args for job in await redis_pool.queued_jobs()] == [(str(message_id),)]


async def test_nao_toca_em_queued_recente(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.QUEUED, idade_segundos=60)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_ignora_processed(session, redis_pool, settings) -> None:
    """PROCESSED e o unico estado realmente terminal.

    FAILED nao e terminal: o ARQ nao re-tenta excecao comum, entao o sweeper e o
    unico caminho de volta para uma mensagem que falhou.
    """
    await mensagem(session, MessageStatus.PROCESSED, idade_segundos=3600)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_respeita_o_teto_de_tentativas(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120, attempts=5)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_varre_varias_de_uma_vez(session, redis_pool, settings) -> None:
    for _ in range(3):
        await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 3
    assert len(await redis_pool.queued_jobs()) == 3

    paradas = (
        await session.scalars(select(Message).where(Message.status == MessageStatus.RECEIVED))
    ).all()
    assert all(linha.attempts == 0 for linha in paradas)


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict) -> None:
        self.entregas.append(message_id)


class OutboundQueCai(OutboundEspiao):
    """Falha na entrega, como uma falha real de processamento."""

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict) -> None:
        raise RuntimeError("falha de processamento")


class FilaQuebrada:
    """Fila que levanta no enqueue, como o Redis fora do ar faria."""

    async def enqueue_job(self, *args, **kwargs):
        raise ConnectionError("redis fora do ar")


async def test_failed_volta_a_ser_processada_pelo_sweeper(session, redis_pool, settings) -> None:
    """Uma mensagem em FAILED nao pode ser um buraco negro.

    O ARQ nao re-tenta excecao comum: o job some da fila. Se o sweeper tambem
    pular FAILED, ninguem mais le a linha e a mensagem se perde. Round trip
    completo: o sweeper reenfileira e o process_message seguinte conclui.
    """
    message_id = await mensagem(session, MessageStatus.FAILED, idade_segundos=3600, attempts=1)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1
    assert [job.args for job in await redis_pool.queued_jobs()] == [(str(message_id),)]

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.attempts == 1, "a falha anterior ja contou; a varredura nao conta de novo"

    outbound = OutboundEspiao(get_sessionmaker())
    ctx = _ctx_do_turno(get_sessionmaker(), outbound)
    assert await process_message(ctx, str(message_id)) == "respondido"

    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert outbound.entregas == [message_id]
    assert await session.scalar(select(func.count()).select_from(OutboundDispatch)) == 1


async def test_fila_quebrada_nao_queima_attempts(session, redis_pool, settings) -> None:
    """Uma queda do Redis nao pode consumir o teto de tentativas em vazio.

    O sweeper roda a cada 30s e o teto e 5: cobrar tentativa sem ter conseguido
    enfileirar abandonaria tudo que esta em voo em ~2,5 min de outage --
    exatamente a janela que o sweeper existe para cobrir. Hoje a garantia e mais
    forte que antes: o sweeper nao escreve `attempts` em caminho nenhum, nem no
    de sucesso, entao nao ha como uma varredura queimar orcamento.
    """
    ids = [await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120) for _ in range(2)]

    assert await sweep_stalled(contexto(FilaQuebrada(), settings)) == 0

    linhas = (await session.scalars(select(Message).order_by(Message.created_at))).all()
    assert [linha.attempts for linha in linhas] == [0, 0]
    assert await redis_pool.queued_jobs() == []

    # Redis volta: a varredura seguinte enfileira as duas.
    assert await sweep_stalled(contexto(redis_pool, settings)) == 2
    assert {job.args[0] for job in await redis_pool.queued_jobs()} == {str(i) for i in ids}
    for linha in linhas:
        await session.refresh(linha)
    assert [linha.attempts for linha in linhas] == [0, 0]


async def test_teto_e_consumido_por_falha_de_processamento_e_continua_limitando(
    session, redis_pool, settings
) -> None:
    """Quem gasta o orcamento e a falha real; o teto continua limitando o re-sweep.

    Com o incremento do sweeper removido, `attempts` volta a valer o que o nome
    diz. O invariante que importa nao mudou: uma mensagem que falha sempre para
    de ser reenfileirada -- so que agora depois de `sweep_max_attempts` falhas de
    verdade, e nao de ~metade disso.
    """
    teto = settings.sweep_max_attempts
    message_id = await mensagem(
        session, MessageStatus.FAILED, idade_segundos=3600, attempts=teto - 1
    )

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1
    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.attempts == teto - 1, "a varredura nao pode consumir orcamento"

    ctx = _ctx_do_turno(get_sessionmaker(), OutboundQueCai(get_sessionmaker()))
    with pytest.raises(RuntimeError):
        await process_message(ctx, str(message_id))

    await session.refresh(linha)
    assert linha.attempts == teto
    assert linha.status == MessageStatus.FAILED

    # Sem o flush, o 0 abaixo poderia vir do dedup do job ainda em voo
    # (_job_id `msg:<id>`) em vez do teto -- e o teto e o que se quer provar.
    await redis_pool.flushdb()
    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_sweeper_ignora_linha_de_saida(session, redis_pool, settings) -> None:
    """A fala do agente nao e mensagem recebida e nao volta para a fila.

    Sem o filtro, o sweeper do TEC-122 varreria a propria resposta do agente e
    a mandaria para `process_message` -- um efeito externo a mais por resposta.
    """
    identificador = uuid.uuid4()
    antigo = datetime.now(UTC) - timedelta(seconds=3600)
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
            status=MessageStatus.RECEIVED,
            created_at=antigo,
        )
    )
    await session.commit()

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []

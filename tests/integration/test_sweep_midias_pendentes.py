"""A varredura das midias PENDENTE. TEC-132, D3 ("Enfileiramento perdido")."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.models import MidiaRecebida, MotivoDaMidia, StatusDaMidia
from mobia.domain.midia.repositorio import ler_midia
from mobia.infra import queue
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs import sweep_midias_pendentes as modulo
from mobia.workers.jobs.sweep_midias_pendentes import sweep_midias_pendentes
from mobia.workers.main import WorkerSettings


async def _pendente(
    session, idade: timedelta, status: StatusDaMidia = StatusDaMidia.PENDENTE
) -> uuid.UUID:
    mensagem = Message(
        channel="whatsapp",
        conversation_key="5511911112222",
        sender_external_id="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.IMAGEM,
        status=MessageStatus.RECEIVED,
    )
    session.add(mensagem)
    await session.commit()
    session.add(
        MidiaRecebida(
            message_id=mensagem.id,
            media_id_da_meta="media-1",
            mime_type="image/jpeg",
            status=status,
        )
    )
    await session.commit()
    await session.execute(
        update(MidiaRecebida)
        .where(MidiaRecebida.message_id == mensagem.id)
        .values(criado_em=datetime.now(UTC) - idade)
    )
    await session.commit()
    return mensagem.id


def _ctx(redis_pool) -> dict:
    return {"session_factory": get_sessionmaker(), "redis": redis_pool}


async def _na_fila(redis_pool, message_id: uuid.UUID) -> bool:
    return await redis_pool.zscore("arq:queue", f"midia:{message_id}") is not None


async def test_reenfileira_so_a_pendente_antiga(session, redis_pool) -> None:
    antiga = await _pendente(session, timedelta(minutes=30))
    recente = await _pendente(session, timedelta(minutes=2))
    terminal = await _pendente(session, timedelta(minutes=30), StatusDaMidia.ARMAZENADA)

    assert await sweep_midias_pendentes(_ctx(redis_pool)) == 1

    assert await _na_fila(redis_pool, antiga)
    assert not await _na_fila(redis_pool, recente)
    assert not await _na_fila(redis_pool, terminal)


async def test_expira_a_de_oito_dias(session, redis_pool) -> None:
    velha = await _pendente(session, timedelta(days=8))

    assert await sweep_midias_pendentes(_ctx(redis_pool)) == 0

    session.expire_all()
    linha = await ler_midia(session, velha)
    assert linha is not None
    assert linha.status == StatusDaMidia.FALHOU
    assert linha.motivo == MotivoDaMidia.EXPIRADA
    assert not await _na_fila(redis_pool, velha)


async def test_falha_no_enqueue_de_uma_nao_impede_as_outras(
    session, redis_pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    primeira = await _pendente(session, timedelta(minutes=40))
    segunda = await _pendente(session, timedelta(minutes=30))

    async def _enqueue(pool, message_id: uuid.UUID) -> bool:
        if message_id == primeira:
            raise ConnectionError("redis caiu")
        return await queue.enqueue_baixar_midia(pool, message_id)

    monkeypatch.setattr(modulo, "enqueue_baixar_midia", _enqueue)

    assert await sweep_midias_pendentes(_ctx(redis_pool)) == 1

    assert not await _na_fila(redis_pool, primeira)
    assert await _na_fila(redis_pool, segunda)


async def _tirar_da_fila(redis_pool, message_id: uuid.UUID) -> None:
    """Simula o job re-enfileirado ter rodado e falhado sem `Retry` (o
    `job_timeout`, um erro de banco em `marcar`): a linha continua PENDENTE e
    o `_job_id` fica livre para a proxima varredura."""
    await redis_pool.zrem("arq:queue", f"midia:{message_id}")
    await redis_pool.delete(f"arq:job:midia:{message_id}")


async def _tentativas(session, message_id: uuid.UUID) -> int:
    session.expire_all()
    linha = await ler_midia(session, message_id)
    assert linha is not None
    return linha.tentativas


async def test_reenfileira_ate_o_teto_e_fecha_na_varredura_seguinte(session, redis_pool) -> None:
    """I1 da revisao final. Sem teto, uma falha que nao e `Retry` voltava a
    fila a cada 5 minutos por 7 dias. Seis re-enfileiramentos, cada um contado
    na linha; a setima varredura fecha como FALHOU/`tentativas_esgotadas` e
    nao enfileira mais."""
    assert modulo.TETO_DE_REENFILEIRAMENTOS == 6
    presa = await _pendente(session, timedelta(minutes=30))
    assert await _tentativas(session, presa) == 0

    for passada in range(1, modulo.TETO_DE_REENFILEIRAMENTOS + 1):
        assert await sweep_midias_pendentes(_ctx(redis_pool)) == 1
        assert await _na_fila(redis_pool, presa)
        assert await _tentativas(session, presa) == passada
        await _tirar_da_fila(redis_pool, presa)

    assert await sweep_midias_pendentes(_ctx(redis_pool)) == 0

    assert not await _na_fila(redis_pool, presa)
    session.expire_all()
    linha = await ler_midia(session, presa)
    assert linha is not None
    assert (linha.status, linha.motivo) == (
        StatusDaMidia.FALHOU,
        MotivoDaMidia.TENTATIVAS_ESGOTADAS,
    )
    assert linha.tentativas == modulo.TETO_DE_REENFILEIRAMENTOS

    # E fechada continua fechada: a varredura seguinte nao a ve mais.
    assert await sweep_midias_pendentes(_ctx(redis_pool)) == 0
    assert not await _na_fila(redis_pool, presa)


async def test_armazenada_nunca_e_tocada_pela_varredura(session, redis_pool) -> None:
    """Nem contada, nem fechada -- mesmo com o contador ja no teto."""
    armazenada = await _pendente(session, timedelta(minutes=30), StatusDaMidia.ARMAZENADA)
    no_teto = await _pendente(session, timedelta(minutes=30), StatusDaMidia.ARMAZENADA)
    await session.execute(
        update(MidiaRecebida)
        .where(MidiaRecebida.message_id == no_teto)
        .values(tentativas=modulo.TETO_DE_REENFILEIRAMENTOS)
    )
    await session.commit()

    for _ in range(modulo.TETO_DE_REENFILEIRAMENTOS + 1):
        assert await sweep_midias_pendentes(_ctx(redis_pool)) == 0

    session.expire_all()
    for message_id, tentativas in (
        (armazenada, 0),
        (no_teto, modulo.TETO_DE_REENFILEIRAMENTOS),
    ):
        linha = await ler_midia(session, message_id)
        assert linha is not None
        assert (linha.status, linha.motivo, linha.tentativas) == (
            StatusDaMidia.ARMAZENADA,
            None,
            tentativas,
        )
        assert not await _na_fila(redis_pool, message_id)


def test_sweep_midias_pendentes_esta_no_cron_de_cinco_em_cinco_minutos() -> None:
    """Sem este teste, apagar a entrada `cron(...)` nao quebra nada: os testes
    acima chamam a funcao direto. Ver o irmao de `sweep_followups` em
    `test_worker_startup.py`."""
    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == "sweep_midias_pendentes"
    )
    assert registrada.keep_result_s == 0

    candidatos = [
        job for job in WorkerSettings.cron_jobs if job.coroutine is sweep_midias_pendentes
    ]
    assert len(candidatos) == 1
    assert candidatos[0].minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
    assert candidatos[0].run_at_startup is False

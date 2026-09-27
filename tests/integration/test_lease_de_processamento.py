"""Um worker de cada vez por mensagem: o lease de `claimed_at`. TEC-218.

Antes desta card, PROCESSING era reivindicavel sempre -- e o que permite
retomar o trabalho de um worker morto --, entao um segundo worker que
chegasse depois do commit do primeiro reivindicava a mesma linha, e os dois
pagavam o mesmo turno. Agora PROCESSING so e reivindicavel com o lease
expirado, e toda escrita depois do claim exige a ficha do worker.
"""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import update
from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.app.config import get_settings
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message, reivindicar


async def _reivindicar(message_id: uuid.UUID):
    async with get_sessionmaker()() as sessao:
        resultado = await reivindicar(sessao, message_id)
        await sessao.commit()
        return resultado


async def _ler(session, message_id: uuid.UUID) -> Message:
    session.expire_all()
    linha = await session.get(Message, message_id)
    assert linha is not None
    return linha


async def _envelhecer_o_lease(message_id: uuid.UUID, segundos: int) -> None:
    async with get_sessionmaker()() as sessao:
        await sessao.execute(
            update(Message)
            .where(Message.id == message_id)
            .values(claimed_at=datetime.now(UTC) - timedelta(seconds=segundos))
        )
        await sessao.commit()


class TurnoQueNaoDeviaRodar:
    async def __call__(self, *args, **kwargs):
        raise AssertionError("o turno rodou para uma mensagem que outro worker tem")


async def test_segundo_worker_nao_reivindica_mensagem_em_processamento(
    session, redis_pool, monkeypatch, caplog
) -> None:
    """Cenario 1 da card: sai sem processar, e o log diz por que."""
    linha = await gravar(session, created_at=datetime.now(UTC))
    primeira = await _reivindicar(linha.id)
    assert primeira is not None

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", TurnoQueNaoDeviaRodar()
    )
    with caplog.at_level("INFO"):
        resultado = await process_message(_ctx(), str(linha.id))

    assert resultado == "skipped"
    ((_, corpo),) = eventos_de_log(caplog, "message.skipped")
    assert corpo["reason"] == "lease_ativo"
    depois = await _ler(session, linha.id)
    assert depois.status == MessageStatus.PROCESSING
    assert depois.claimed_at == primeira.lease, "o lease continua sendo do primeiro"
    assert depois.attempts == 0, "a recusa nao conta tentativa de ninguem"


async def test_lease_expirado_permite_retomada(session, redis_pool, monkeypatch) -> None:
    """Cenario 2 da card: o worker morto e substituido, e o turno conclui."""
    linha = await gravar(session, created_at=datetime.now(UTC))
    assert await _reivindicar(linha.id) is not None
    await _envelhecer_o_lease(linha.id, get_settings().sweep_inflight_after_seconds + 1)

    async def _turno(*args, **kwargs):
        return "respondido"

    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", _turno)
    resultado = await process_message(_ctx(), str(linha.id))

    assert resultado == "respondido"
    depois = await _ler(session, linha.id)
    assert depois.status == MessageStatus.PROCESSED
    # A retomada conta a tentativa do worker que morreu (TEC-209, D4).
    assert depois.attempts == 1


async def test_lease_dentro_da_janela_nao_expira(session, redis_pool) -> None:
    """A fronteira do outro lado: um segundo antes da janela, ainda e do primeiro."""
    linha = await gravar(session, created_at=datetime.now(UTC))
    assert await _reivindicar(linha.id) is not None
    await _envelhecer_o_lease(linha.id, get_settings().sweep_inflight_after_seconds - 5)

    assert await _reivindicar(linha.id) is None


async def test_processing_sem_lease_de_antes_da_card_e_retomavel(session, redis_pool) -> None:
    """A linha em PROCESSING gravada antes da TEC-218 nao tem `claimed_at`.

    Tratada como lease expirado: sem isto, o worker que morreu antes do deploy
    deixaria a linha parada para sempre.
    """
    linha = await gravar(session, created_at=datetime.now(UTC))
    async with get_sessionmaker()() as sessao:
        await sessao.execute(
            update(Message)
            .where(Message.id == linha.id)
            .values(status=MessageStatus.PROCESSING, claimed_at=None)
        )
        await sessao.commit()

    reivindicacao = await _reivindicar(linha.id)

    assert reivindicacao is not None
    assert reivindicacao.anterior == MessageStatus.PROCESSING


async def test_worker_que_perde_a_corrida_nao_sobrescreve_estado_terminal(
    session, redis_pool, monkeypatch, caplog
) -> None:
    """Cenario 3 da card.

    O worker A reivindica e demora alem da janela. O B assume a linha pelo
    lease expirado e a conclui como PROCESSED. Quando A finalmente falha, a
    falha dele nao pode virar FAILED por cima do PROCESSED de B -- nem contar
    tentativa, nem abrir DLQ.
    """
    linha = await gravar(session, created_at=datetime.now(UTC))

    async def _turno_de_a_que_perde_a_vez(*args, **kwargs):
        # Enquanto A "roda", o lease dele vence e B assume e conclui.
        await _envelhecer_o_lease(linha.id, get_settings().sweep_inflight_after_seconds + 1)
        b = await _reivindicar(linha.id)
        assert b is not None
        async with get_sessionmaker()() as sessao:
            await sessao.execute(
                update(Message)
                .where(Message.id == linha.id)
                .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
            )
            await sessao.commit()
        raise RuntimeError("A falhou depois de B concluir")

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", _turno_de_a_que_perde_a_vez
    )
    with caplog.at_level("INFO"):
        try:
            await process_message(_ctx(), str(linha.id))
        except RuntimeError:
            pass
        else:
            raise AssertionError("a falha de A tem de subir para quem roda o job")

    depois = await _ler(session, linha.id)
    assert depois.status == MessageStatus.PROCESSED
    # B reivindicou pelo `reivindicar` direto, que nao conta tentativa -- quem
    # conta a retomada e `process_message`. Zero aqui quer dizer que a falha
    # de A tambem nao contou.
    assert depois.attempts == 0, "a falha de A nao conta tentativa numa linha que nao e dela"
    assert depois.last_error != "RuntimeError"
    perdas = eventos_de_log(caplog, "message.lease_perdido")
    assert [p.corpo["etapa"] for p in perdas] == ["falha"]


async def test_worker_que_perde_a_vez_nao_fecha_processed_por_cima_do_outro(
    session, redis_pool, monkeypatch, caplog
) -> None:
    """O mesmo lado do sucesso: A termina depois de B ter assumido a linha.

    O PROCESSED de A nao e gravado -- a linha e de B, e so B a fecha. A entrega
    nao duplica por outra guarda, a reserva de `outbound_dispatches`.
    """
    linha = await gravar(session, created_at=datetime.now(UTC))

    async def _turno_lento(*args, **kwargs):
        await _envelhecer_o_lease(linha.id, get_settings().sweep_inflight_after_seconds + 1)
        assert await _reivindicar(linha.id) is not None
        return "respondido"

    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", _turno_lento)
    with caplog.at_level("INFO"):
        await process_message(_ctx(), str(linha.id))

    depois = await _ler(session, linha.id)
    assert depois.status == MessageStatus.PROCESSING, "a linha continua de B, em curso"
    perdas = eventos_de_log(caplog, "message.lease_perdido")
    assert [p.corpo["etapa"] for p in perdas] == ["concluir"]

"""O handoff por erro irrecuperavel, e o aviso que vai com ele."""

import asyncio
from typing import Any

import pytest
from conftest import ClassificadorFake, ContadorFake, ModeradorFake, OutboundFake, ResumidorFake
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message
from mobia.domain.outbound.port import EnvioRecusado
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message


async def _total(session: AsyncSession) -> int:
    return await session.scalar(text("SELECT count(*) FROM handoffs")) or 0


def _ctx(outbound, classificador) -> dict[str, Any]:
    return {
        "session_factory": get_sessionmaker(),
        "outbound": outbound,
        "classificador": classificador,
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
    }


@pytest.fixture
def processar_com_turno_que_falha():
    """Roda `process_message` sobre um classificador que levanta.

    O erro default e um `RuntimeError` generico -- o que importa a esta
    suite e o TETO de tentativas, nao o tipo da excecao. `erro=` troca o
    que o classificador levanta (usado para provar que cancelamento nao
    conta como falha irrecuperavel), e `outbound_quebrado=` troca o envio
    do aviso por um que recusa, sem tocar o classificador.
    """

    async def _processar(
        linha: Message,
        *,
        erro: BaseException | None = None,
        outbound_quebrado: bool = False,
    ) -> None:
        erro_do_envio = EnvioRecusado() if outbound_quebrado else None
        outbound = OutboundFake(get_sessionmaker(), erro=erro_do_envio)
        classificador = ClassificadorFake(erro=erro or RuntimeError("turno falhou de proposito"))
        await process_message(_ctx(outbound, classificador), str(linha.id))

    return _processar


async def test_falha_antes_do_teto_nao_cria_handoff(
    session, semear_entrada, processar_com_turno_que_falha
) -> None:
    """Retentar ainda pode resolver: encaminhar aqui seria alarme falso."""
    linha = await semear_entrada(session)
    with pytest.raises(RuntimeError):
        await processar_com_turno_que_falha(linha)
    assert await _total(session) == 0


async def test_falha_que_atinge_o_teto_cria_handoff(
    session, semear_entrada, processar_com_turno_que_falha, settings
) -> None:
    linha = await semear_entrada(session)
    await session.execute(
        update(Message)
        .where(Message.id == linha.id)
        .values(attempts=settings.sweep_max_attempts - 1)
    )
    await session.commit()
    with pytest.raises(RuntimeError):
        await processar_com_turno_que_falha(linha)
    resultado = await session.execute(text("SELECT gatilho, etiqueta FROM handoffs"))
    linhas = [dict(item) for item in resultado.mappings()]
    assert len(linhas) == 1
    assert linhas[0]["gatilho"] == "ERRO_DO_AGENTE"
    assert linhas[0]["etiqueta"] == "erro-do-agente"


async def test_aviso_quebrado_nao_desfaz_o_handoff(
    session, semear_entrada, processar_com_turno_que_falha, settings
) -> None:
    """O corretor ser avisado nao pode depender de o lead ter sido avisado."""
    linha = await semear_entrada(session)
    await session.execute(
        update(Message)
        .where(Message.id == linha.id)
        .values(attempts=settings.sweep_max_attempts - 1)
    )
    await session.commit()
    with pytest.raises(RuntimeError):
        await processar_com_turno_que_falha(linha, outbound_quebrado=True)
    assert await _total(session) == 1


async def test_cancelamento_nao_cria_handoff(
    session, semear_entrada, processar_com_turno_que_falha, settings
) -> None:
    """Desligamento limpo nao e falha do agente.

    A mensagem volta para a fila e o sweeper a recupera. Handoff aqui
    encaminharia ao corretor um lead que so pegou um deploy no meio.
    """
    linha = await semear_entrada(session)
    await session.execute(
        update(Message)
        .where(Message.id == linha.id)
        .values(attempts=settings.sweep_max_attempts - 1)
    )
    await session.commit()
    with pytest.raises(asyncio.CancelledError):
        await processar_com_turno_que_falha(linha, erro=asyncio.CancelledError())
    assert await _total(session) == 0

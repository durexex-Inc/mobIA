"""A mensagem superada fecha sem responder (TEC-128, D4)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import select
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import GuardedOutbound
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message


class TurnoQueNaoDeviaRodar:
    """Duble que transforma em falha o turno rodar para uma mensagem superada."""

    def __init__(self) -> None:
        self.chamou = False

    async def __call__(self, *args, **kwargs):
        self.chamou = True
        raise AssertionError("executar_turno rodou para uma mensagem superada")


def _ctx() -> dict[str, Any]:
    # `GuardedOutbound` cru, sem `_deliver` implementado: no caminho
    # `agrupado` o outbound nunca e chamado, entao um duble espiao seria
    # so ceremonia. Se algum dia `_deliver` for alcancado aqui, o
    # `NotImplementedError` denuncia a regressao alto.
    return {
        "session_factory": get_sessionmaker(),
        "outbound": GuardedOutbound(get_sessionmaker()),
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "indicador": IndicadorNoop(),
    }


async def test_superada_fecha_como_processed_sem_rodar_o_turno(
    session, redis_pool, monkeypatch
) -> None:
    agora = datetime.now(UTC)
    primeira = await gravar(session, created_at=agora)
    await gravar(session, created_at=agora + timedelta(seconds=2))

    espiao = TurnoQueNaoDeviaRodar()
    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", espiao)

    resultado = await process_message(_ctx(), str(primeira.id))

    assert resultado == "agrupado"
    assert espiao.chamou is False

    await session.commit()
    estado = await session.scalar(select(Message.status).where(Message.id == primeira.id))
    assert estado == MessageStatus.PROCESSED


async def test_superada_registra_processed_at(session, redis_pool, monkeypatch) -> None:
    agora = datetime.now(UTC)
    primeira = await gravar(session, created_at=agora)
    await gravar(session, created_at=agora + timedelta(seconds=2))

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", TurnoQueNaoDeviaRodar()
    )

    await process_message(_ctx(), str(primeira.id))

    await session.commit()
    carimbo = await session.scalar(select(Message.processed_at).where(Message.id == primeira.id))
    assert carimbo is not None

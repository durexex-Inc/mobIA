"""A mensagem agrupada passa pela moderacao de entrada (TEC-295, D1-D3)."""

from datetime import UTC, datetime, timedelta

from conftest import (  # type: ignore[import-not-found]
    ClassificadorFake,
    ContadorFake,
    ResumidorFake,
)
from sqlalchemy import func, select
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel, Veredito
from mobia.domain.outbound.port import GuardedOutbound
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

REPROVAVEL = "texto que a moderacao reprova"


class ModeradorQueBloqueia:
    """Bloqueia so o texto combinado, e conta quantas vezes foi chamado."""

    def __init__(self, texto_bloqueado: str = REPROVAVEL) -> None:
        self.texto_bloqueado = texto_bloqueado
        self.chamadas: list[str] = []

    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito:
        self.chamadas.append(texto)
        if texto == self.texto_bloqueado:
            return Veredito(bloqueado=True, motivo="teste", categoria="ASSEDIO")
        return Veredito(bloqueado=False, motivo="liberado")


class ModeradorCaido:
    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito:
        raise ModeracaoIndisponivel("provedor fora do ar")


def _ctx(moderador) -> dict:
    """O ctx de oito chaves que `process_message` exige.

    Molde de `tests/integration/test_process_message_agrupado.py`; so o
    moderador varia entre os testes deste arquivo.
    """
    return {
        "session_factory": get_sessionmaker(),
        "outbound": GuardedOutbound(get_sessionmaker()),
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": moderador,
        "agendador": AgendadorNoop(),
        "indicador": IndicadorNoop(),
    }


async def test_superada_reprovavel_recebe_marca_e_auditoria(session) -> None:
    """A garantia 3: marca e evento saem juntos, pela mesma `marcar_bloqueada`."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    await gravar(session, created_at=agora + timedelta(seconds=1))

    moderador = ModeradorQueBloqueia()
    resultado = await process_message(_ctx(moderador), str(superada.id))

    assert resultado == "agrupado"
    await session.commit()
    linha = await session.get(Message, superada.id)
    assert linha is not None
    await session.refresh(linha)
    assert linha.bloqueada_em is not None
    eventos = await session.scalar(
        select(func.count())
        .select_from(ModerationEvent)
        .where(ModerationEvent.message_id == superada.id)
    )
    assert eventos == 1


async def test_superada_liberada_nao_ganha_marca(session) -> None:
    """A D1 nao pode bloquear o caminho comum."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto="tem 2 quartos?")
    await gravar(session, created_at=agora + timedelta(seconds=1))

    moderador = ModeradorQueBloqueia()
    resultado = await process_message(_ctx(moderador), str(superada.id))

    assert resultado == "agrupado"
    assert moderador.chamadas == ["tem 2 quartos?"]
    await session.commit()
    linha = await session.get(Message, superada.id)
    assert linha is not None
    await session.refresh(linha)
    assert linha.bloqueada_em is None


async def test_superada_bloqueada_ainda_fecha_agrupado(session) -> None:
    """A D3: ela ganha a marca, nao vira turno e nao gera recusa propria."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    await gravar(session, created_at=agora + timedelta(seconds=1))

    resultado = await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))

    assert resultado == "agrupado"
    await session.commit()
    estado = await session.scalar(select(Message.status).where(Message.id == superada.id))
    assert estado == MessageStatus.PROCESSED


async def test_moderacao_indisponivel_nao_derruba_o_agrupamento(session) -> None:
    """A D2: fail-open. Deixar subir faria `attempts` crescer e, esgotadas as
    cinco, o lead receberia um aviso de erro por uma mensagem que so precisava
    ser agrupada."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    await gravar(session, created_at=agora + timedelta(seconds=1))

    resultado = await process_message(_ctx(ModeradorCaido()), str(superada.id))

    assert resultado == "agrupado"
    await session.commit()
    linha = await session.get(Message, superada.id)
    assert linha is not None
    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.attempts == 0
    assert linha.bloqueada_em is None

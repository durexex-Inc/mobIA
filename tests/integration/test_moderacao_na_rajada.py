"""A mensagem agrupada passa pela moderacao de entrada (TEC-295, D1-D3).

A Task 2 prova que a marca `bloqueada_em` e gravada. Os testes abaixo, da
Task 3, provam que ela SERVE -- que a fala bloqueada some dos quatro
consumidores (janela de contexto, contagem do lead score e ancora da
cadencia de follow-up) e que a liberada continua entrando normalmente.
"""

from datetime import UTC, datetime, timedelta

from conftest import (  # type: ignore[import-not-found]
    ClassificadorFake,
    ContadorFake,
    ResumidorFake,
)
from sqlalchemy import func, insert, select, update
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.repositorio import candidatos_a_followup
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


async def test_superada_bloqueada_sai_da_janela_de_contexto(session) -> None:
    """Garantia 2 (TEC-236), provada por `literais_apos` e nao pelo desfecho."""
    from mobia.domain.context.janela import literais_apos

    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))
    await session.commit()

    literais = await literais_apos(session, ultima.channel, ultima.conversation_key, None)
    ids = {linha.id for linha in literais}
    assert superada.id not in ids
    assert ultima.id in ids


async def test_superada_bloqueada_sai_da_contagem_do_score(session) -> None:
    """Garantia 4, lado do lead score."""
    from mobia.domain.context.repositorio import contar_mensagens_do_lead

    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    antes = await contar_mensagens_do_lead(
        session, channel=ultima.channel, conversation_key=ultima.conversation_key
    )
    assert antes == 2

    await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))
    await session.commit()

    depois = await contar_mensagens_do_lead(
        session, channel=ultima.channel, conversation_key=ultima.conversation_key
    )
    assert depois == 1


async def test_superada_liberada_continua_no_contexto(session) -> None:
    """A D1 nao pode tirar do contexto a fala que a moderacao liberou."""
    from mobia.domain.context.janela import literais_apos

    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto="tem 2 quartos?")
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))
    await session.commit()

    literais = await literais_apos(session, ultima.channel, ultima.conversation_key, None)
    assert superada.id in {linha.id for linha in literais}


async def test_ancora_da_cadencia_ignora_fala_bloqueada(session) -> None:
    """Garantia 4, lado do follow-up: a fala bloqueada nao pode ser a ancora.

    Exercita o caminho completo, `candidatos_a_followup`, e nao a CTE isolada:
    a unica montagem extra em relacao aos testes acima e uma linha de
    `lead_qualification`, entao "meia duzia de entidades" nao se aplica aqui
    -- nao ha conversa, qualificacao completa, cadencia nem janela de horario
    para montar, so a linha minima que o INNER JOIN da consulta exige.

    A marca e gravada direto na coluna, e nao via `process_message`: a Task 2
    ja prova que `marcar_bloqueada` grava certo, e aqui o que se testa e o
    lado da LEITURA. Um `process_message` so bloqueia a fala SUPERADA, que ja
    e a mais antiga das duas -- nunca mudaria qual e a ancora, porque a mais
    nova sempre venceria de qualquer jeito. Marcar a MAIS NOVA como bloqueada
    e o que exercita o caso que importa: a ancora tem de recuar para a fala
    anterior, nao ficar presa na bloqueada.
    """
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora - timedelta(hours=3))
    bloqueada = await gravar(session, created_at=agora - timedelta(minutes=30))
    await session.execute(
        update(Message).where(Message.id == bloqueada.id).values(bloqueada_em=agora)
    )
    await session.execute(
        insert(LeadQualification).values(
            channel=bloqueada.channel,
            conversation_key=bloqueada.conversation_key,
            temperatura=Temperatura.FRIO.value,
        )
    )
    await session.commit()

    candidatos = await candidatos_a_followup(session, agora=agora)
    relevantes = [
        candidato
        for candidato in candidatos
        if candidato.channel == bloqueada.channel
        and candidato.conversation_key == bloqueada.conversation_key
    ]

    assert len(relevantes) == 1
    candidato = relevantes[0]
    assert candidato.ancora_message_id == superada.id
    assert candidato.ancora_em == superada.created_at

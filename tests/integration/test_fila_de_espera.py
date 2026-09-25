"""A fila no nivel do orquestrador. TEC-169, RN-11.5.

Os quatro cenarios da card estao em `tests/features/test_lista_de_espera.py` e
em `test_sweep_lista_de_espera.py`. O que mora aqui sao os INVARIANTES que
nenhum deles exercita -- o que acontece quando o lead repete, quando ele
aceita duas vezes, e quando quem nao tem janela e alguem que ja tem visita
marcada.

Chama `conversa.py::atender` direto, e nao o turno inteiro, pelo mesmo motivo
que `test_conversa_de_agendamento.py`: o que se afirma e sobre o estado no
banco, e o turno so acrescentaria ruido entre a fala e a linha.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agendamento.conversa import (
    AceitouEspera,
    NadaAFazer,
    OfereceuEspera,
    atender,
)
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import (
    Agendamento,
    ListaDeEspera,
    StatusDoAgendamento,
)
from mobia.domain.agendamento.repositorio import AgendaPostgres
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.infra.db import get_sessionmaker

SP = ZoneInfo("America/Sao_Paulo")
CANAL = "whatsapp"
LEAD = "5511911118888"


async def _lotar_agenda(session: AsyncSession, corretor: Corretor, agora: datetime) -> None:
    """Ocupa a jornada inteira dos proximos quatro dias.

    Quatro pela mesma razao que `tests/features/test_lista_de_espera.py`
    registra: as 72 horas contam de AGORA, entao mordem parte do quarto dia
    quando a suite roda de tarde.
    """
    hoje = agora.astimezone(SP).date()
    for dia in range(4):
        inicio = datetime.combine(
            hoje + timedelta(days=dia), datetime.min.time(), tzinfo=SP
        ).replace(hour=9)
        session.add(
            Agendamento(
                id=uuid.uuid4(),
                corretor_id=corretor.id,
                channel=CANAL,
                conversation_key="5511900000000",
                imovel_id=None,
                tipo=TipoDeCompromisso.VISITA_PRESENCIAL.value,
                inicio=inicio,
                fim=inicio + timedelta(hours=9),
                status=StatusDoAgendamento.CONFIRMADO.value,
                reservado_ate=agora + timedelta(days=30),
                criado_em=agora,
                confirmado_em=agora,
                motivo_da_alocacao=MotivoDaAlocacao.SEM_MATCH.value,
            )
        )
    await session.commit()


async def _atender(session: AsyncSession, texto: str, *, agora: datetime):
    agenda = AgendaPostgres(get_sessionmaker())
    desfecho = await atender(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        texto=texto,
        estado=None,
        agora=agora,
        agenda=agenda,
        visitas=agenda,
    )
    await session.commit()
    return desfecho


async def _linhas(session: AsyncSession) -> list[ListaDeEspera]:
    return list(
        (
            await session.scalars(
                select(ListaDeEspera)
                .where(ListaDeEspera.conversation_key == LEAD)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def test_pedir_visita_duas_vezes_nao_ocupa_dois_lugares(
    session: AsyncSession, semear_corretor
) -> None:
    """O indice parcial e a funcao `oferecer` dizem a mesma coisa, e aqui se prova.

    Um lead numa semana lotada que insiste -- o que e o comportamento normal
    de quem quer visitar -- nao pode ocupar tres posicoes da mesma fila.
    """
    agora = datetime.now(UTC)
    corretor = await semear_corretor(email=f"ana-{uuid.uuid4().hex[:8]}@imob.com.br")
    await _lotar_agenda(session, corretor, agora)

    assert isinstance(
        await _atender(session, "quero agendar uma visita", agora=agora), OfereceuEspera
    )
    assert isinstance(await _atender(session, "quero marcar visita", agora=agora), OfereceuEspera)

    assert len(await _linhas(session)) == 1


async def test_aceitar_duas_vezes_nao_move_o_lugar_na_fila(
    session: AsyncSession, semear_corretor
) -> None:
    """`aceita_em` e a posicao na fila, e o segundo "sim" nao pode empurra-la.

    Sem o filtro `aceita_em IS NULL` no UPDATE, o lead que confirma de novo
    -- por entusiasmo, ou porque nao viu a resposta -- iria para tras de quem
    chegou depois dele.
    """
    agora = datetime.now(UTC)
    corretor = await semear_corretor(email=f"ana-{uuid.uuid4().hex[:8]}@imob.com.br")
    await _lotar_agenda(session, corretor, agora)
    await _atender(session, "quero agendar uma visita", agora=agora)

    primeiro = await _atender(session, "pode ser", agora=agora)
    assert isinstance(primeiro, AceitouEspera)
    (linha,) = await _linhas(session)
    entrada = linha.aceita_em

    # Uma hora depois, o mesmo "sim". A oferta ja nao esta pendente, entao a
    # etapa da espera nem chega a olhar o detector -- mas se um dia chegar, a
    # posicao nao pode mudar.
    await _atender(session, "pode ser", agora=agora + timedelta(hours=1))
    (linha,) = await _linhas(session)
    assert linha.aceita_em == entrada


async def test_o_aceite_e_o_handoff_entram_juntos(session: AsyncSession, semear_corretor) -> None:
    """Lead na fila sem handoff e o estado que a card existe para impedir."""
    agora = datetime.now(UTC)
    corretor = await semear_corretor(email=f"ana-{uuid.uuid4().hex[:8]}@imob.com.br")
    await _lotar_agenda(session, corretor, agora)
    await _atender(session, "quero agendar uma visita", agora=agora)

    # Antes do aceite nao ha handoff nenhum: a oferta sozinha nao pede nada ao
    # corretor.
    assert not (await session.scalars(select(Handoff))).all()

    desfecho = await _atender(session, "sim", agora=agora)
    assert isinstance(desfecho, AceitouEspera)
    (handoff,) = (await session.scalars(select(Handoff))).all()
    assert handoff.id == desfecho.handoff_id


async def test_texto_que_nao_e_sim_nem_nao_deixa_a_oferta_de_pe(
    session: AsyncSession, semear_corretor
) -> None:
    """A oferta nao e um menu do qual nao se sai.

    O lead que pergunta outra coisa no meio recebe o turno normal, e a oferta
    continua valendo no turno seguinte -- o mesmo limite de sequestro que a
    docstring do modulo declara para as outras etapas.
    """
    agora = datetime.now(UTC)
    corretor = await semear_corretor(email=f"ana-{uuid.uuid4().hex[:8]}@imob.com.br")
    await _lotar_agenda(session, corretor, agora)
    await _atender(session, "quero agendar uma visita", agora=agora)

    assert isinstance(await _atender(session, "quanto é o condomínio?", agora=agora), NadaAFazer)
    (linha,) = await _linhas(session)
    assert linha.aceita_em is None and linha.recusada_em is None

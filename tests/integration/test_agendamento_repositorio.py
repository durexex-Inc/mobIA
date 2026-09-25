"""Reservar, confirmar e ler a agenda do corretor. TEC-168, RN-11.4.

`agora` e literal: os cenarios "reservado ha 5 minutos" e "ha 2 minutos"
sao aritmetica sobre ele, sem dormir.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from mobia.domain.agendamento.janelas import (
    Intervalo,
    TipoDeCompromisso,
    propor_janelas_do_corretor,
)
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.repositorio import (
    DURACAO_DA_RESERVA,
    AgendaPostgres,
    Confirmado,
    Conflito,
    Expirado,
    Reserva,
    confirmar,
    reservar,
)

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 8, 25, 14, 0, tzinfo=SP)
VISITA = TipoDeCompromisso.VISITA_PRESENCIAL


def _qui(hora: int, minuto: int = 0) -> Intervalo:
    inicio = datetime(2026, 8, 27, hora, minuto, tzinfo=SP)
    return Intervalo(inicio, inicio + timedelta(hours=1))


async def _reservar(session, corretor_id, janela, *, agora=AGORA, chave="5511911111111"):
    return await reservar(
        session,
        corretor_id=corretor_id,
        channel="whatsapp",
        conversation_key=chave,
        janela=janela,
        tipo=VISITA,
        imovel_id=None,
        agora=agora,
    )


async def _status(session, reserva_id) -> str:
    session.expire_all()
    return await session.scalar(select(Agendamento.status).where(Agendamento.id == reserva_id))


async def test_reservar_grava_reservado_por_5_minutos(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    resultado = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(resultado, Reserva)
    assert resultado.janela == _qui(10)
    assert resultado.reservado_ate == AGORA + DURACAO_DA_RESERVA
    assert await _status(session, resultado.id) == StatusDoAgendamento.RESERVADO


async def test_confirmacao_dentro_do_prazo_mantem_a_reserva(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    resultado = await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=2))
    await session.commit()
    assert resultado == Confirmado(reserva.id, _qui(10))
    session.expire_all()
    linha = await session.get(Agendamento, reserva.id)
    assert linha is not None
    assert linha.status == StatusDoAgendamento.CONFIRMADO
    assert linha.confirmado_em == AGORA + timedelta(minutes=2)


async def test_confirmar_depois_do_prazo_e_expirado_e_nao_grava(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    resultado = await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=5))
    await session.commit()
    assert resultado == Expirado()
    assert await _status(session, reserva.id) == StatusDoAgendamento.RESERVADO


async def test_confirmar_duas_vezes_nao_regrava(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=1))
    await session.commit()
    segunda = await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=2))
    assert segunda == Expirado()


async def test_confirmar_id_inexistente_e_expirado(session) -> None:
    assert await confirmar(session, reserva_id=uuid.uuid4(), agora=AGORA) == Expirado()


async def test_reserva_valida_do_mesmo_slot_e_conflito(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    resultado = await _reservar(
        session, corretor.id, _qui(10), agora=AGORA + timedelta(minutes=1), chave="5511922222222"
    )
    assert resultado == Conflito()


async def test_sessao_continua_utilizavel_depois_do_conflito(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    await _reservar(session, corretor.id, _qui(10), chave="5511922222222")
    outra = await _reservar(session, corretor.id, _qui(15), chave="5511922222222")
    await session.commit()
    assert isinstance(outra, Reserva)


async def test_reservar_sobre_reserva_vencida_sucede_e_expira_a_antiga(
    session, semear_corretor
) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    antiga = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(antiga, Reserva)
    nova = await _reservar(
        session, corretor.id, _qui(10), agora=AGORA + timedelta(minutes=5), chave="5511922222222"
    )
    await session.commit()
    assert isinstance(nova, Reserva)
    assert await _status(session, antiga.id) == StatusDoAgendamento.EXPIRADO


async def test_reservar_nao_expira_reserva_vencida_de_outro_corretor(
    session, semear_corretor
) -> None:
    paulo = await semear_corretor(email="paulo@teste.com")
    ana = await semear_corretor(email="ana@teste.com")
    dela = await _reservar(session, ana.id, _qui(10))
    await session.commit()
    assert isinstance(dela, Reserva)
    await _reservar(session, paulo.id, _qui(10), agora=AGORA + timedelta(minutes=10))
    await session.commit()
    assert await _status(session, dela.id) == StatusDoAgendamento.RESERVADO


async def test_ocupados_conta_confirmado_e_reserva_valida(
    session, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    confirmada = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(confirmada, Reserva)
    await confirmar(session, reserva_id=confirmada.id, agora=AGORA)
    await _reservar(session, corretor.id, _qui(15), chave="5511922222222")
    await session.commit()
    agenda = AgendaPostgres(session_factory)
    ocupados = await agenda.ocupados(
        corretor.id, AGORA + timedelta(minutes=1), AGORA + timedelta(days=7)
    )
    assert ocupados == [_qui(10), _qui(15)]


async def test_reserva_vencida_some_da_agenda_e_volta_as_propostas(
    session, session_factory, semear_corretor
) -> None:
    """O cenario "reserva expira sem confirmacao" da card.

    Jornada de uma hora (10h-11h): cada dia tem uma janela so, e a de quinta
    so pode aparecer nas propostas se a reserva dela tiver vencido. Com a
    jornada inteira, o motor espalharia por dia e ofereceria quinta 9h -- e o
    teste passaria sem provar nada.
    """
    corretor = await semear_corretor(email="paulo@teste.com", horario_inicio=10, horario_fim=11)
    await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    agenda = AgendaPostgres(session_factory)
    ate = datetime(2026, 8, 27, 12, 0, tzinfo=SP)

    antes = await propor_janelas_do_corretor(
        corretor=corretor, agenda=agenda, agora=AGORA + timedelta(minutes=1), ate=ate, tipo=VISITA
    )
    depois = await propor_janelas_do_corretor(
        corretor=corretor, agenda=agenda, agora=AGORA + timedelta(minutes=5), ate=ate, tipo=VISITA
    )
    assert _qui(10) not in antes
    assert _qui(10) in depois


async def test_ocupados_devolve_o_que_sobrepoe_e_nao_so_o_contido(
    session, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    await confirmar(session, reserva_id=reserva.id, agora=AGORA)
    await session.commit()
    agenda = AgendaPostgres(session_factory)
    meio = datetime(2026, 8, 27, 10, 30, tzinfo=SP)
    assert await agenda.ocupados(corretor.id, meio, meio + timedelta(hours=2)) == [_qui(10)]

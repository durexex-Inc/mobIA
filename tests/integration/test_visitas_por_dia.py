"""A contagem de visitas por data local, no banco. TEC-166, D6 do desenho.

27/08/2026 e uma quinta. Nos testes da contagem as linhas entram direto pelo
modelo: o que se testa neles e a leitura, nao a reserva. Os dois ultimos
testam a escrita do motivo: `reservar` o grava, e o CHECK da 0045 recusa o
que esta fora do vocabulario.
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.repositorio import AgendaPostgres, Reserva, reservar
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 8, 27, 14, 0, tzinfo=SP)
QUINTA = date(2026, 8, 27)
SEXTA = date(2026, 8, 28)


async def _gravar(
    session,
    corretor_id,
    inicio: datetime,
    *,
    status=StatusDoAgendamento.CONFIRMADO,
    tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    reservado_ate: datetime | None = None,
) -> None:
    session.add(
        Agendamento(
            id=uuid.uuid4(),
            corretor_id=corretor_id,
            channel="whatsapp",
            conversation_key=str(uuid.uuid4())[:20],
            imovel_id=None,
            tipo=str(tipo),
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            status=status,
            reservado_ate=reservado_ate or inicio,
            criado_em=AGORA,
            confirmado_em=None,
            motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
        )
    )
    await session.commit()


async def _contar(session_factory, corretor_ids, *, de=QUINTA, ate=SEXTA):
    return await AgendaPostgres(session_factory).visitas_por_dia(
        corretor_ids, de=de, ate=ate, agora=AGORA
    )


async def test_conta_confirmada_e_reserva_viva(session, session_factory, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    await _gravar(session, ana.id, datetime(2026, 8, 27, 10, tzinfo=SP))
    await _gravar(
        session,
        ana.id,
        datetime(2026, 8, 27, 16, tzinfo=SP),
        status=StatusDoAgendamento.RESERVADO,
        reservado_ate=AGORA + timedelta(minutes=3),
    )
    assert await _contar(session_factory, [ana.id]) == {(ana.id, QUINTA): 2}


async def test_visita_de_hoje_antes_do_agora_gasta_capacidade(
    session, session_factory, semear_corretor
) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    await _gravar(session, ana.id, datetime(2026, 8, 27, 9, tzinfo=SP))
    assert await _contar(session_factory, [ana.id]) == {(ana.id, QUINTA): 1}


async def test_ignora_reserva_vencida_expirada_e_reuniao(
    session, session_factory, semear_corretor
) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    await _gravar(
        session,
        ana.id,
        datetime(2026, 8, 27, 10, tzinfo=SP),
        status=StatusDoAgendamento.RESERVADO,
        reservado_ate=AGORA - timedelta(minutes=1),
    )
    await _gravar(
        session, ana.id, datetime(2026, 8, 27, 12, tzinfo=SP), status=StatusDoAgendamento.EXPIRADO
    )
    await _gravar(
        session,
        ana.id,
        datetime(2026, 8, 27, 16, tzinfo=SP),
        tipo=TipoDeCompromisso.REUNIAO_REMOTA,
    )
    assert await _contar(session_factory, [ana.id]) == {}


async def test_visita_as_23h30_e_da_data_local(session, session_factory, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    # 23h30 de quinta em Sao Paulo ja e sexta em UTC.
    await _gravar(session, ana.id, datetime(2026, 8, 27, 23, 30, tzinfo=SP))
    assert await _contar(session_factory, [ana.id]) == {(ana.id, QUINTA): 1}


async def test_fora_das_datas_e_de_outro_corretor_nao_entra(
    session, session_factory, semear_corretor
) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    bia = await semear_corretor(email="bia@teste.com")
    await _gravar(session, ana.id, datetime(2026, 8, 29, 10, tzinfo=SP))
    await _gravar(session, bia.id, datetime(2026, 8, 27, 10, tzinfo=SP))
    assert await _contar(session_factory, [ana.id]) == {}


async def test_sem_corretores_nao_consulta(session_factory) -> None:
    assert await _contar(session_factory, []) == {}


async def test_reservar_grava_o_motivo(session, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    inicio = datetime(2026, 8, 28, 10, tzinfo=SP)
    resultado = await reservar(
        session,
        corretor_id=ana.id,
        channel="whatsapp",
        conversation_key="5511911111111",
        janela=Intervalo(inicio, inicio + timedelta(hours=1)),
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=AGORA,
        motivo=MotivoDaAlocacao.SEM_MATCH,
    )
    await session.commit()
    assert isinstance(resultado, Reserva)
    session.expire_all()
    linha = await session.get(Agendamento, resultado.id)
    assert linha is not None
    assert linha.motivo_da_alocacao == MotivoDaAlocacao.SEM_MATCH


async def test_motivo_fora_do_vocabulario_e_recusado(session, semear_corretor) -> None:
    ana = await semear_corretor(email="ana@teste.com")
    with pytest.raises(IntegrityError):
        await _gravar_com_motivo(session, ana.id, "PORQUE_SIM")


async def _gravar_com_motivo(session, corretor_id, motivo: str) -> None:
    inicio = datetime(2026, 8, 28, 10, tzinfo=SP)
    session.add(
        Agendamento(
            id=uuid.uuid4(),
            corretor_id=corretor_id,
            channel="whatsapp",
            conversation_key="5511922222222",
            imovel_id=None,
            tipo="VISITA_PRESENCIAL",
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            status="CONFIRMADO",
            reservado_ate=inicio,
            criado_em=AGORA,
            confirmado_em=None,
            motivo_da_alocacao=motivo,
        )
    )
    await session.commit()

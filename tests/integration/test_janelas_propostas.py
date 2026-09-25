"""As janelas oferecidas ao lead, gravadas e lidas de volta. TEC-371, D4.

O que estes testes protegem e a razao da tabela existir: o ordinal e a hora
que o lead responde tem de se referir ao que a frase anterior disse, e nao ao
que o motor devolveria agora.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from mobia.domain.agendamento.janelas import Intervalo, JanelaAlocada, TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, JanelaProposta, StatusDoAgendamento
from mobia.domain.agendamento.propostas import apagar, gravar, ler
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao

CANAL = "whatsapp"
LEAD = "5511999990000"


def _janela(corretor_id: uuid.UUID, *, daqui_a_horas: int) -> JanelaAlocada:
    inicio = datetime.now(UTC) + timedelta(hours=daqui_a_horas)
    return JanelaAlocada(
        janela=Intervalo(inicio, inicio + timedelta(hours=1)),
        corretor_id=corretor_id,
        motivo=MotivoDaAlocacao.MATCH_EXATO,
    )


async def test_grava_tres_e_le_na_ordem_do_ordinal(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="a@x.com")
    agora = datetime.now(UTC)

    gravadas = await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=h) for h in (4, 28, 52)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await session.commit()

    assert [p.ordinal for p in gravadas] == [1, 2, 3]

    lidas = await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora)
    assert [p.ordinal for p in lidas] == [1, 2, 3]
    assert [p.janela for p in lidas] == [p.janela for p in gravadas]
    assert all(p.corretor_id == corretor.id for p in lidas)
    assert all(p.tipo is TipoDeCompromisso.VISITA_PRESENCIAL for p in lidas)
    assert all(p.motivo is MotivoDaAlocacao.MATCH_EXATO for p in lidas)


async def test_a_rodada_nova_substitui_a_anterior(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="b@x.com")
    agora = datetime.now(UTC)

    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=h) for h in (4, 28, 52)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=h) for h in (5, 29)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await session.commit()

    lidas = await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora)
    # Duas, e nao tres: o ordinal 3 da rodada velha nao pode sobreviver a uma
    # frase que ofereceu duas janelas.
    assert [p.ordinal for p in lidas] == [1, 2]


async def test_rodada_vazia_apaga_a_anterior(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="c@x.com")
    agora = datetime.now(UTC)

    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=4)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await session.commit()

    assert await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora) == []


async def test_proposta_cujo_inicio_ja_passou_nao_e_lida(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="d@x.com")
    agora = datetime.now(UTC)

    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=4)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await session.commit()

    # Tres dias depois: a janela existe na tabela e nao serve para nada.
    depois = agora + timedelta(days=3)
    assert await ler(session, channel=CANAL, conversation_key=LEAD, agora=depois) == []


async def test_duas_conversas_nao_se_enxergam(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="e@x.com")
    agora = datetime.now(UTC)

    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=4)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await gravar(
        session,
        channel=CANAL,
        conversation_key="5511888880000",
        janelas=[_janela(corretor.id, daqui_a_horas=h) for h in (6, 30)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await session.commit()

    assert len(await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora)) == 1
    outra = await ler(session, channel=CANAL, conversation_key="5511888880000", agora=agora)
    assert len(outra) == 2


async def test_apagar_esquece_a_rodada(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="f@x.com")
    agora = datetime.now(UTC)

    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=4)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await apagar(session, channel=CANAL, conversation_key=LEAD)
    await session.commit()

    assert await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora) == []


async def test_o_unique_recusa_dois_ordinais_iguais(session, semear_corretor) -> None:
    """A regra "uma rodada de cada vez" e do schema, e nao da disciplina de quem consulta."""
    corretor = await semear_corretor(email="g@x.com")
    agora = datetime.now(UTC)
    inicio = agora + timedelta(hours=4)

    for _ in range(2):
        session.add(
            JanelaProposta(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=LEAD,
                ordinal=1,
                corretor_id=corretor.id,
                imovel_id=None,
                tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
                inicio=inicio,
                fim=inicio + timedelta(hours=1),
                motivo_da_alocacao=str(MotivoDaAlocacao.MATCH_EXATO),
                proposto_em=agora,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_remarcacao_em_curso_sobrevive_a_ida_e_volta(session, semear_corretor) -> None:
    """TEC-372, D4: e `remarcando_id` que da destino a rodada.

    Sem ele, a escolha do lead reservaria um agendamento novo em vez de
    remarcar o que ele ja tem -- e o original ficaria de pe, com dois
    compromissos no lugar de um.
    """
    corretor = await semear_corretor(email="h@x.com")
    agora = datetime.now(UTC)
    inicio = agora + timedelta(hours=4)
    original = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor.id,
        channel=CANAL,
        conversation_key=LEAD,
        imovel_id=None,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        status=StatusDoAgendamento.CONFIRMADO,
        reservado_ate=agora,
        criado_em=agora,
        confirmado_em=agora,
        motivo_da_alocacao=str(MotivoDaAlocacao.MATCH_EXATO),
    )
    session.add(original)
    await session.commit()

    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=28)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
        remarcando_id=original.id,
    )
    await session.commit()

    (lida,) = await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora)
    assert lida.remarcando_id == original.id
    # E o original nao foi tocado: so vira REAGENDADO quando o lead escolher.
    assert original.status == StatusDoAgendamento.CONFIRMADO
    assert original.presenca_confirmada_em is None


async def test_sem_remarcacao_o_campo_e_nulo(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="i@x.com")
    agora = datetime.now(UTC)
    await gravar(
        session,
        channel=CANAL,
        conversation_key=LEAD,
        janelas=[_janela(corretor.id, daqui_a_horas=4)],
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=agora,
    )
    await session.commit()
    (lida,) = await ler(session, channel=CANAL, conversation_key=LEAD, agora=agora)
    assert lida.remarcando_id is None

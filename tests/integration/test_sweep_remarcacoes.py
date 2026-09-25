"""A varredura do convite de remarcacao, ponta a ponta. TEC-172, RN-12.3.

A regua e pura e esta em `tests/unit/test_remarcacao.py`; aqui se verifica
quem entra na consulta, o que sai pela porta e o que fica gravado.

Molde de `test_sweep_lembretes.py`, que e o molde da varredura.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import OutboundFake, eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import Settings
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.remarcacao import (
    TEMPLATE_DO_CONVITE,
    TEXTO_DO_CONVITE_DE_REMARCACAO,
    VALIDADE_DO_CONVITE,
    kind_do_convite,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioRetentavel
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_remarcacoes import sweep_remarcacoes

CANAL = "whatsapp"
CONVERSA = "5511911111111"
NOME_DO_FUSO = "America/Sao_Paulo"
FUSO = ZoneInfo(NOME_DO_FUSO)

# O cancelamento acontece as 14h locais de uma sexta; o convite vence 24 horas
# depois, as 14h de sabado -- dentro da janela de contato nos dois dias.
CANCELADO_EM = datetime(2026, 9, 25, 14, tzinfo=FUSO)
DEVIDO_EM = CANCELADO_EM + timedelta(hours=24)
INICIO = datetime(2026, 9, 26, 15, tzinfo=FUSO)


async def _cancelado(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    cancelado_em: datetime | None = CANCELADO_EM,
    status: str = StatusDoAgendamento.CANCELADO,
    conversa: str = CONVERSA,
    inicio: datetime = INICIO,
) -> Agendamento:
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id,
        channel=CANAL,
        conversation_key=conversa,
        imovel_id=None,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        status=status,
        reservado_ate=inicio,
        criado_em=CANCELADO_EM - timedelta(days=1),
        confirmado_em=CANCELADO_EM - timedelta(days=1),
        motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
        cancelado_em=cancelado_em,
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def _mensagem_do_lead(
    session: AsyncSession, *, criada_em: datetime, conversa: str = CONVERSA
) -> Message:
    mensagem = Message(
        id=uuid.uuid4(),
        channel=CANAL,
        provider_message_id=f"wamid.{uuid.uuid4().hex[:10]}",
        sender_external_id=conversa,
        recipient_external_id="222222222",
        conversation_key=conversa,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
        created_at=criada_em,
    )
    session.add(mensagem)
    await session.commit()
    return mensagem


def _ctx(outbound: object | None = None, *, templates_aprovados: str = "") -> dict[str, Any]:
    return {
        "session_factory": get_sessionmaker(),
        "outbound": outbound if outbound is not None else OutboundFake(get_sessionmaker()),
        "settings": Settings(
            _env_file=None,
            followup_horario_inicio=9,
            followup_horario_fim=20,
            followup_fuso=NOME_DO_FUSO,
            whatsapp_templates_aprovados=templates_aprovados,
        ),
    }


async def _recarregar(session: AsyncSession, identificador: uuid.UUID) -> Agendamento:
    return (
        await session.execute(
            select(Agendamento)
            .where(Agendamento.id == identificador)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_o_convite_sai_vinte_e_quatro_horas_depois_do_cancelamento(
    session: AsyncSession, semear_corretor
) -> None:
    """RN-12.3: "agenda tentativa de remarcacao em 24 horas"."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM)

    assert enviados == 1
    assert outbound.entregues == [TEXTO_DO_CONVITE_DE_REMARCACAO]
    reservados = list((await session.execute(select(OutboundDispatch.kind))).scalars().all())
    assert kind_do_convite(agendamento.id) in reservados
    assert (await _recarregar(session, agendamento.id)).remarcacao_convidada_em is not None


async def test_nao_sai_antes_das_vinte_e_quatro_horas(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=CANCELADO_EM)

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM - timedelta(hours=1)) == 0
    assert outbound.entregues == []


async def test_nao_sai_depois_da_validade(session: AsyncSession, semear_corretor) -> None:
    """O teto da faixa, e as duas razoes dele.

    Um worker parado nao pode fazer o convite sair quando ele ja deixou de
    fazer sentido -- e, sem o teto, o primeiro deploy convidaria todo
    cancelamento anterior a esta card de uma vez.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=CANCELADO_EM)

    outbound = OutboundFake(get_sessionmaker())
    tarde = DEVIDO_EM + VALIDADE_DO_CONVITE + timedelta(minutes=1)
    # Reposicionado para dentro da janela de contato do dia seguinte, para o
    # que se testa ser o teto e nao o horario.
    tarde = tarde.astimezone(FUSO).replace(hour=14)
    assert await sweep_remarcacoes(_ctx(outbound), agora=tarde) == 0
    assert outbound.entregues == []


async def test_a_segunda_passagem_nao_convida_de_novo(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 1
    assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 0
    assert len(outbound.entregues) == 1


@pytest.mark.parametrize("status", [StatusDoAgendamento.CONFIRMADO, StatusDoAgendamento.REAGENDADO])
async def test_so_cancelado_recebe_convite(
    session: AsyncSession, semear_corretor, status: str
) -> None:
    """Quem remarcou por outro caminho nao pode receber o convite antigo -- e
    isso sai de graca da consulta, que filtra por CANCELADO."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _cancelado(session, corretor_id=corretor.id, status=status)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 0


async def test_cancelamento_sem_carimbo_nao_recebe_convite(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _cancelado(session, corretor_id=corretor.id, cancelado_em=None)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 0


async def test_fora_do_horario_de_contato_nada_sai(session: AsyncSession, semear_corretor) -> None:
    """RN-13.3, o terceiro sitio a aplicar a guarda."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))

    outbound = OutboundFake(get_sessionmaker())
    madrugada = DEVIDO_EM.astimezone(FUSO).replace(hour=3)
    assert await sweep_remarcacoes(_ctx(outbound), agora=madrugada) == 0
    assert (await _recarregar(session, agendamento.id)).remarcacao_convidada_em is None


async def test_fora_da_janela_de_24h_sem_template_nada_sai(
    session: AsyncSession, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    """A lacuna maior, e aqui ela morde mais que na TEC-171.

    Quem cancelou e, por definicao, alguem que parou de falar com o agente --
    entao o convite quase sempre cai fora da janela de 24h da Meta.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(days=4))

    outbound = OutboundFake(get_sessionmaker())
    with caplog.at_level(logging.WARNING):
        assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 0

    assert outbound.entregues == []
    assert eventos_de_log(caplog, "remarcacao.sem_template")
    assert (await _recarregar(session, agendamento.id)).remarcacao_convidada_em is not None


async def test_fora_da_janela_com_template_aprovado_sai_o_template(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(days=4))

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_remarcacoes(
        _ctx(outbound, templates_aprovados=TEMPLATE_DO_CONVITE), agora=DEVIDO_EM
    )

    assert enviados == 1
    assert outbound.entregues == [TEMPLATE_DO_CONVITE]
    (payload,) = outbound.payloads
    assert payload["tipo"] == "template"
    # O convite nao descreve compromisso nenhum, entao nao ha parametro a
    # preencher -- e `outbound/whatsapp.py` ja trata a lista vazia.
    assert payload["parametros"] == []


async def test_lead_em_optout_nao_recebe_e_nao_repete(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))
    session.add(
        OptoutEvent(
            id=uuid.uuid4(), channel=CANAL, conversation_key=CONVERSA, evento=EVENTO_OPT_OUT
        )
    )
    await session.commit()

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 0
    assert outbound.entregues == []
    assert (await _recarregar(session, agendamento.id)).remarcacao_convidada_em is not None


async def test_falha_de_canal_deixa_a_coluna_nula_e_a_proxima_tenta(
    session: AsyncSession, semear_corretor
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _cancelado(session, corretor_id=corretor.id)
    await _mensagem_do_lead(session, criada_em=DEVIDO_EM - timedelta(hours=3))

    que_falha = OutboundFake(get_sessionmaker(), erro=EnvioRetentavel("5xx"))
    assert await sweep_remarcacoes(_ctx(que_falha), agora=DEVIDO_EM) == 0
    assert (await _recarregar(session, agendamento.id)).remarcacao_convidada_em is None

    bom = OutboundFake(get_sessionmaker())
    assert await sweep_remarcacoes(_ctx(bom), agora=DEVIDO_EM + timedelta(hours=1)) == 1


async def test_sem_fala_do_lead_nao_ha_de_quem_mandar(
    session: AsyncSession, semear_corretor, caplog: pytest.LogCaptureFixture
) -> None:
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _cancelado(session, corretor_id=corretor.id)

    outbound = OutboundFake(get_sessionmaker())
    with caplog.at_level(logging.INFO):
        assert await sweep_remarcacoes(_ctx(outbound), agora=DEVIDO_EM) == 0

    assert eventos_de_log(caplog, "remarcacao.sem_ancora")
    assert (await _recarregar(session, agendamento.id)).remarcacao_convidada_em is not None


def test_sweep_remarcacoes_esta_no_cron_de_cinco_em_cinco_minutos() -> None:
    """Sem este teste, apagar a entrada `cron(...)` nao quebra nada: os testes
    acima chamam a funcao direto. Ver o irmao em `test_sweep_lembretes.py`."""
    from mobia.workers.main import WorkerSettings

    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == "sweep_remarcacoes"
    )
    assert registrada.keep_result_s == 0

    candidatos = [job for job in WorkerSettings.cron_jobs if job.coroutine is sweep_remarcacoes]
    assert len(candidatos) == 1
    assert candidatos[0].minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
    assert candidatos[0].run_at_startup is False

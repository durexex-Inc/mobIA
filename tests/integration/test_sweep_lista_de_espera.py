"""A varredura do slot liberado, ponta a ponta. TEC-169, RN-11.5.

Molde de `test_sweep_remarcacoes.py`, que e o molde da varredura: aqui se
verifica quem entra na consulta, o que sai pela porta e o que fica gravado.

O terceiro cenario do Gherkin da card mora aqui, e nao em
`tests/features/`, porque ele e sobre a ORDEM da fila -- um fato entre duas
linhas do banco, que nenhum turno de conversa produz sozinho.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from conftest import OutboundFake  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import Settings
from mobia.domain.agendamento.espera import (
    TEMPLATE_DO_AVISO,
    TEXTO_DO_SLOT_LIBERADO,
    kind_do_aviso,
)
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import (
    Agendamento,
    ListaDeEspera,
    StatusDoAgendamento,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_lista_de_espera import sweep_lista_de_espera

CANAL = "whatsapp"
PRIMEIRO = "5511911111111"
SEGUNDO = "5511922222222"
NOME_DO_FUSO = "America/Sao_Paulo"
FUSO = ZoneInfo(NOME_DO_FUSO)

# Uma sexta as 14h locais, dentro da janela de contato. O slot liberado comeca
# no dia seguinte -- dentro das 72 horas, que e o que a RN-11.5 exige.
AGORA = datetime(2026, 9, 25, 14, tzinfo=FUSO)
INICIO_DO_SLOT = AGORA + timedelta(days=1)


async def _slot_liberado(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    status: str = StatusDoAgendamento.CANCELADO,
    inicio: datetime = INICIO_DO_SLOT,
) -> Agendamento:
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id,
        channel=CANAL,
        conversation_key="5511900000000",
        imovel_id=None,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        status=status,
        reservado_ate=inicio,
        criado_em=AGORA - timedelta(days=2),
        confirmado_em=AGORA - timedelta(days=2),
        motivo_da_alocacao=MotivoDaAlocacao.MATCH_EXATO,
        cancelado_em=AGORA - timedelta(hours=1),
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def _na_fila(session: AsyncSession, *, conversa: str, aceita_em: datetime) -> ListaDeEspera:
    linha = ListaDeEspera(
        id=uuid.uuid4(),
        channel=CANAL,
        conversation_key=conversa,
        imovel_id=None,
        oferecida_em=aceita_em - timedelta(minutes=1),
        aceita_em=aceita_em,
    )
    session.add(linha)
    await session.commit()
    return linha


async def _mensagem_do_lead(
    session: AsyncSession, *, criada_em: datetime, conversa: str
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


async def _recarregar(session: AsyncSession, identificador: uuid.UUID) -> ListaDeEspera:
    return (
        await session.execute(
            select(ListaDeEspera)
            .where(ListaDeEspera.id == identificador)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_slot_liberado_avisa_a_fila_em_ordem(session: AsyncSession, semear_corretor) -> None:
    """Terceiro cenario do Gherkin, literal: o primeiro da fila e avisado primeiro.

    Um slot liberado, dois leads na fila. Quem aceitou antes recebe; o outro
    continua esperando, e e isso que a D7 chama de "um por slot".
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id)
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    segundo = await _na_fila(session, conversa=SEGUNDO, aceita_em=AGORA - timedelta(hours=1))
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=PRIMEIRO)
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=SEGUNDO)

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lista_de_espera(_ctx(outbound), agora=AGORA)

    assert enviados == 1
    assert outbound.entregues == [TEXTO_DO_SLOT_LIBERADO]

    # O primeiro saiu da fila; o segundo continua nela.
    assert (await _recarregar(session, primeiro.id)).avisada_em is not None
    assert (await _recarregar(session, segundo.id)).avisada_em is None

    reservados = list((await session.execute(select(OutboundDispatch.kind))).scalars().all())
    assert kind_do_aviso(primeiro.id) in reservados


async def test_o_mesmo_slot_nao_avisa_duas_vezes(session: AsyncSession, semear_corretor) -> None:
    """Uma segunda passagem sobre o mesmo cancelamento nao gasta o proximo da fila.

    E o que `avisada_por_agendamento_id` existe para garantir: sem ela, o cron
    de cinco em cinco minutos esvaziaria a fila inteira por causa de um
    cancelamento so.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    agendamento = await _slot_liberado(session, corretor_id=corretor.id)
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    segundo = await _na_fila(session, conversa=SEGUNDO, aceita_em=AGORA - timedelta(hours=1))
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=PRIMEIRO)
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=SEGUNDO)

    assert await sweep_lista_de_espera(_ctx(), agora=AGORA) == 1
    assert await sweep_lista_de_espera(_ctx(), agora=AGORA) == 0

    assert (await _recarregar(session, primeiro.id)).avisada_por_agendamento_id == agendamento.id
    assert (await _recarregar(session, segundo.id)).avisada_em is None


async def test_dois_slots_avisam_dois_leads_em_ordem(
    session: AsyncSession, semear_corretor
) -> None:
    """Dois cancelamentos na janela gastam os dois primeiros da fila."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id)
    await _slot_liberado(
        session, corretor_id=corretor.id, inicio=INICIO_DO_SLOT + timedelta(hours=3)
    )
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    segundo = await _na_fila(session, conversa=SEGUNDO, aceita_em=AGORA - timedelta(hours=1))
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=PRIMEIRO)
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=SEGUNDO)

    assert await sweep_lista_de_espera(_ctx(), agora=AGORA) == 2
    assert (await _recarregar(session, primeiro.id)).avisada_em is not None
    assert (await _recarregar(session, segundo.id)).avisada_em is not None


async def test_slot_fora_das_72_horas_nao_avisa_ninguem(
    session: AsyncSession, semear_corretor
) -> None:
    """A regra e sobre a janela de 72 horas, e o cancelamento distante nao entra.

    Quem esta na fila quer visita ESTA semana -- foi por nao haver nada nela
    que ele entrou. Um horario que abriu para dali a dez dias nao responde ao
    que ele pediu, e avisa-lo seria ruido.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id, inicio=AGORA + timedelta(days=10))
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=PRIMEIRO)

    assert await sweep_lista_de_espera(_ctx(), agora=AGORA) == 0
    assert (await _recarregar(session, primeiro.id)).avisada_em is None


async def test_quem_so_recebeu_a_oferta_nao_esta_na_fila(
    session: AsyncSession, semear_corretor
) -> None:
    """`aceita_em` nula e "nao respondeu", e nao um lugar na fila (D3)."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id)
    linha = ListaDeEspera(
        id=uuid.uuid4(),
        channel=CANAL,
        conversation_key=PRIMEIRO,
        imovel_id=None,
        oferecida_em=AGORA - timedelta(hours=5),
    )
    session.add(linha)
    await session.commit()
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=PRIMEIRO)

    assert await sweep_lista_de_espera(_ctx(), agora=AGORA) == 0
    assert (await _recarregar(session, linha.id)).avisada_em is None


async def test_sem_template_a_fila_anda_mesmo_assim(session: AsyncSession, semear_corretor) -> None:
    """A lacuna da TEC-373, e a decisao que impede a fila de travar nela.

    Fora da janela de 24 horas e sem template aprovado, nada sai -- mas
    `avisada_em` e carimbada assim mesmo. Sem isso o proximo da fila ficaria
    preso atras de um lead que nao pode ser avisado, para sempre.
    """
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id)
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    # Tres dias atras: muito alem das 24 horas da Meta.
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(days=3), conversa=PRIMEIRO)

    outbound = OutboundFake(get_sessionmaker())
    assert await sweep_lista_de_espera(_ctx(outbound), agora=AGORA) == 0
    assert outbound.entregues == []
    assert (await _recarregar(session, primeiro.id)).avisada_em is not None


async def test_com_o_template_aprovado_o_aviso_sai_fora_da_janela(
    session: AsyncSession, semear_corretor
) -> None:
    """A outra metade da mesma lacuna: aprovado o template, o aviso sai."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id)
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(days=3), conversa=PRIMEIRO)

    outbound = OutboundFake(get_sessionmaker())
    enviados = await sweep_lista_de_espera(
        _ctx(outbound, templates_aprovados=TEMPLATE_DO_AVISO), agora=AGORA
    )

    assert enviados == 1
    assert (await _recarregar(session, primeiro.id)).avisada_em is not None


async def test_fora_do_horario_de_contato_nao_varre(session: AsyncSession, semear_corretor) -> None:
    """RN-13.3, a guarda no topo -- a mesma das tres varreduras irmas."""
    corretor = await semear_corretor(email="ana@imob.com.br")
    await _slot_liberado(session, corretor_id=corretor.id)
    primeiro = await _na_fila(session, conversa=PRIMEIRO, aceita_em=AGORA - timedelta(hours=5))
    await _mensagem_do_lead(session, criada_em=AGORA - timedelta(hours=2), conversa=PRIMEIRO)

    madrugada = AGORA.replace(hour=3)
    assert await sweep_lista_de_espera(_ctx(), agora=madrugada) == 0
    assert (await _recarregar(session, primeiro.id)).avisada_em is None

"""Cenarios Gherkin de TEC-372.

Funcionalidade: Resposta ao lembrete de agendamento

Os quatro cenarios da card, rodando o turno inteiro por `executar_turno`. O
angulo, como em `test_agendamento_pela_conversa.py`, e o que o lead le e o
que existe no banco -- a linguagem em que os criterios de aceite estao
escritos.

O lembrete nao e enviado de verdade aqui: `sweep_lembretes` tem os proprios
testes, e o que abre a janela desta card e a coluna `lembrete_24h_em`
carimbada. Semea-la direto e o que mantem este arquivo sobre a RESPOSTA.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.repositorio import Reserva, reservar
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.agente.turno import executar_turno
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
LEAD = "5511911117777"


class _AvisosEspiao:
    def __init__(self) -> None:
        self.confirmacoes: list[uuid.UUID] = []
        self.cancelamentos: list[uuid.UUID] = []

    async def confirmacao(self, agendamento_id: uuid.UUID) -> None:
        self.confirmacoes.append(agendamento_id)

    async def cancelamento(self, agendamento_id: uuid.UUID) -> None:
        self.cancelamentos.append(agendamento_id)


async def _corretor(session) -> Corretor:
    agora = datetime.now(UTC)
    corretor = Corretor(
        id=uuid.uuid4(),
        nome="Paula M.",
        email="paula372@imobiliaria.com.br",
        telefone="11999999999",
        creci=None,
        especialidades=["COMPRA"],
        regioes_atuacao=["pinheiros"],
        horario_inicio=9,
        horario_fim=18,
        capacidade_diaria=5,
        plantao=True,
        gerente=False,
        ativo=True,
        criado_em=agora,
        atualizado_em=agora,
    )
    session.add(corretor)
    await session.commit()
    return corretor


async def _visita_com_lembrete_enviado(
    session, corretor: Corretor, *, lembrete_enviado: bool = True, daqui_a_horas: int = 20
) -> Agendamento:
    agora = datetime.now(UTC)
    inicio = agora + timedelta(hours=daqui_a_horas)
    agendamento = Agendamento(
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
        lembrete_24h_em=agora - timedelta(minutes=5) if lembrete_enviado else None,
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def _falar(session, texto: str) -> Message:
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=LEAD,
        recipient_external_id="222222222",
        conversation_key=LEAD,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    return linha


async def _turno(session, texto, *, dubles, avisos=None):
    entrada = await _falar(session, texto)
    outbound = dubles["outbound_fake"]()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=entrada,
        classificador=dubles["classificador_fake"](),
        resumidor=dubles["resumidor_fake"](),
        contador=dubles["contador_fake"](),
        outbound=outbound,
        moderador=dubles["moderador_fake"](),
        agendador=AgendadorNoop(),
        agendador_de_avisos=avisos if avisos is not None else AgendadorDeAvisosNoop(),
    )
    return resultado, outbound


@pytest.fixture
def dubles(classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake):
    return {
        "classificador_fake": classificador_fake,
        "outbound_fake": outbound_fake,
        "resumidor_fake": resumidor_fake,
        "contador_fake": contador_fake,
        "moderador_fake": moderador_fake,
    }


async def test_a_confirmacao_de_presenca_fica_registrada(session, dubles) -> None:
    """Cenario 1: a confirmacao fica registrada no agendamento."""
    corretor = await _corretor(session)
    agendamento = await _visita_com_lembrete_enviado(session, corretor)

    resultado, outbound = await _turno(session, "sim, estarei lá", dubles=dubles)

    assert resultado == "presenca_confirmada"
    await session.refresh(agendamento)
    assert agendamento.presenca_confirmada_em is not None
    # Registrada na coluna, e nao no status: o compromisso ja era CONFIRMADO.
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO
    assert len(outbound.entregues) == 1


async def test_o_cancelamento_libera_o_slot_e_notifica_o_corretor(session, dubles) -> None:
    """Cenario 2: CANCELADO, horario de volta ao pool, corretor notificado."""
    corretor = await _corretor(session)
    agendamento = await _visita_com_lembrete_enviado(session, corretor)
    horario = Intervalo(agendamento.inicio, agendamento.fim)
    avisos = _AvisosEspiao()

    resultado, outbound = await _turno(session, "preciso cancelar", dubles=dubles, avisos=avisos)

    assert resultado == "agendamento_cancelado"
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CANCELADO
    assert len(outbound.entregues) == 1

    # **O slot voltou ao pool**, e a prova e contra a constraint real: uma
    # reserva nova no MESMO horario e corretor tem de ser aceita.
    reserva = await reservar(
        session,
        corretor_id=corretor.id,
        channel=CANAL,
        conversation_key="5511900000000",
        janela=horario,
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        imovel_id=None,
        agora=datetime.now(UTC),
        motivo=MotivoDaAlocacao.MATCH_EXATO,
    )
    assert isinstance(reserva, Reserva)

    # E o corretor foi notificado -- pelo job, enfileirado depois do commit.
    assert avisos.cancelamentos == [agendamento.id]


async def test_a_remarcacao_oferece_horarios_e_so_cai_na_escolha(session, dubles) -> None:
    """Cenario 3: o original so vira REAGENDADO quando o lead escolhe."""
    corretor = await _corretor(session)
    agendamento = await _visita_com_lembrete_enviado(session, corretor)

    resultado, outbound = await _turno(session, "podemos remarcar?", dubles=dubles)

    assert resultado == "agendamento_oferecido"
    assert "1." in outbound.entregues[0]
    # A primeira metade do cenario e sobre o que NAO mudou.
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO

    resultado, _ = await _turno(session, "a primeira", dubles=dubles)

    assert resultado == "agendamento_confirmado"
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.REAGENDADO
    sucessor = (
        await session.scalars(select(Agendamento).where(Agendamento.origem_id == agendamento.id))
    ).one()
    assert sucessor.status == StatusDoAgendamento.CONFIRMADO


@pytest.mark.parametrize(
    ("cenario", "com_agendamento", "lembrete_enviado"),
    [
        ("sem agendamento nenhum", False, False),
        ("com agendamento e sem lembrete enviado", True, False),
    ],
)
async def test_fora_do_contexto_do_lembrete_nada_muda(
    session, dubles, cenario: str, com_agendamento: bool, lembrete_enviado: bool
) -> None:
    """Cenario 4: "cancela aquele outro assunto" nao derruba nada."""
    corretor = await _corretor(session)
    agendamento = (
        await _visita_com_lembrete_enviado(session, corretor, lembrete_enviado=lembrete_enviado)
        if com_agendamento
        else None
    )

    resultado, _ = await _turno(session, "cancela aquele outro assunto", dubles=dubles)

    # O turno normal respondeu: o modelo foi chamado, e nenhum status mudou.
    assert resultado == "respondido", cenario
    if agendamento is not None:
        await session.refresh(agendamento)
        assert agendamento.status == StatusDoAgendamento.CONFIRMADO, cenario


async def test_depois_do_inicio_da_visita_o_cancelamento_nao_vale(session, dubles) -> None:
    """A terceira condicao do predicado: visita comecada nao se cancela pela conversa."""
    corretor = await _corretor(session)
    agendamento = await _visita_com_lembrete_enviado(session, corretor, daqui_a_horas=-1)

    resultado, _ = await _turno(session, "preciso cancelar", dubles=dubles)

    assert resultado == "respondido"
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO

"""Cenarios Gherkin de TEC-371.

Funcionalidade: Agendar a visita pela conversa

Os quatro cenarios da card, cada um num teste, rodando o turno inteiro por
`executar_turno` -- e nao o orquestrador direto, que e o que
`tests/integration/test_conversa_de_agendamento.py` ja faz. O que muda aqui e
o angulo: as assertas sao sobre **o que o lead le** e sobre **o que existe no
banco**, que e a linguagem em que os criterios de aceite estao escritos.

`agora` nao entra por parametro no turno -- ele carimba com o relogio --,
entao os cenarios que dependem de tempo envelhecem a linha no banco em vez de
dormir, como `test_sweep_lembretes.py` ja faz.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeConfirmacaoNoop
from mobia.domain.agendamento.data_falada import DIAS_DA_SEMANA
from mobia.domain.agendamento.models import (
    Agendamento,
    JanelaProposta,
    StatusDoAgendamento,
)
from mobia.domain.agente.turno import executar_turno
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

SP = ZoneInfo("America/Sao_Paulo")
CANAL = "whatsapp"
LEAD = "5511911115555"
OUTRO_LEAD = "5511911116666"


class _AgendadorEspiao:
    def __init__(self) -> None:
        self.agendados: list[uuid.UUID] = []

    async def agendar(self, agendamento_id: uuid.UUID) -> None:
        self.agendados.append(agendamento_id)


async def _falar(session, texto: str, *, lead: str = LEAD) -> Message:
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=lead,
        recipient_external_id="222222222",
        conversation_key=lead,
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


async def _turno(
    session,
    texto,
    *,
    lead=LEAD,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    agendador_de_confirmacao=None,
):
    entrada = await _falar(session, texto, lead=lead)
    outbound = outbound_fake()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=entrada,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=moderador_fake(),
        agendador=AgendadorNoop(),
        agendador_de_confirmacao=(
            agendador_de_confirmacao
            if agendador_de_confirmacao is not None
            else AgendadorDeConfirmacaoNoop()
        ),
    )
    return resultado, outbound


async def _consultar_propostas(session, lead: str = LEAD) -> list[JanelaProposta]:
    return list(
        (
            await session.scalars(
                select(JanelaProposta)
                .where(JanelaProposta.conversation_key == lead)
                .order_by(JanelaProposta.ordinal)
            )
        ).all()
    )


async def _agendamentos(session, lead: str = LEAD) -> list[Agendamento]:
    return list(
        (
            await session.scalars(select(Agendamento).where(Agendamento.conversation_key == lead))
        ).all()
    )


def _proxima_quinta() -> date:
    hoje = datetime.now(SP).date()
    # 3 = quinta em `weekday()`. Sempre a PROXIMA, nunca hoje: a antecedencia
    # minima de 3 horas tornaria o cenario dependente da hora em que a suite
    # roda.
    return hoje + timedelta(days=((3 - hoje.weekday()) % 7) or 7)


async def test_o_lead_pede_horario_e_recebe_janelas_daquela_quinta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 1, com a fala literal da card (CA-11.1).

    "pode ser quinta de manha?" nao tem verbo de agendamento nem a palavra
    visita -- o que a torna um pedido e o enquadramento mais a data, que e a
    segunda via de `deteccao.py::quer_agendar`. E a resposta tem de ser
    daquela quinta, e nao a grade dos proximos tres dias.
    """
    await _semear_corretor(session)
    resultado, outbound = await _turno(
        session,
        "pode ser quinta de manhã?",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    assert resultado == "agendamento_oferecido"
    (texto,) = outbound.entregues
    numeradas = [linha for linha in texto.splitlines() if linha[:2] in ("1.", "2.", "3.")]
    assert 1 <= len(numeradas) <= 3
    # Cada uma diz o dia da semana, o dia do mes e a hora -- RN-11.3. Nenhuma
    # diz "amanha" nem "que vem".
    for linha in numeradas:
        assert any(dia in linha for dia in DIAS_DA_SEMANA)
        assert " de " in linha
        assert "h" in linha.rsplit("às ", 1)[-1]
    assert "amanhã" not in texto and "que vem" not in texto

    # **Daquela quinta**, e de manha: e o que separa esta resposta de uma
    # grade generica que por acaso comeca hoje.
    quinta = _proxima_quinta()
    inicios = [linha.inicio.astimezone(SP) for linha in await _consultar_propostas(session)]
    assert inicios, "a oferta tem de ter ficado gravada"
    assert all(inicio.date() == quinta for inicio in inicios)
    assert all(9 <= inicio.hour < 12 for inicio in inicios)


async def test_o_pedido_sem_data_oferece_a_grade_dos_proximos_dias(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Sem data na fala, a oferta espalha por dias -- o comportamento da TEC-165."""
    await _semear_corretor(session)
    resultado, outbound = await _turno(
        session,
        "quero agendar uma visita",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    assert resultado == "agendamento_oferecido"
    inicios = [linha.inicio.astimezone(SP) for linha in await _consultar_propostas(session)]
    assert len({inicio.date() for inicio in inicios}) == len(inicios)


async def test_a_escolha_do_lead_vira_agendamento_confirmado(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 2: escolher e confirmar cria o agendamento e enfileira o aviso."""
    await _semear_corretor(session)
    dubles = {
        "classificador_fake": classificador_fake,
        "outbound_fake": outbound_fake,
        "resumidor_fake": resumidor_fake,
        "contador_fake": contador_fake,
        "moderador_fake": moderador_fake,
    }
    await _turno(session, "quero agendar uma visita", **dubles)
    _, outbound_da_escolha = await _turno(session, "a primeira", **dubles)
    # A pergunta de confirmacao repete o horario por extenso antes de gravar.
    assert "Confirmo a visita?" in outbound_da_escolha.entregues[0]

    espiao = _AgendadorEspiao()
    resultado, outbound = await _turno(
        session, "isso, pode marcar", agendador_de_confirmacao=espiao, **dubles
    )

    assert resultado == "agendamento_confirmado"
    linhas = await _agendamentos(session)
    assert [linha.status for linha in linhas] == [StatusDoAgendamento.CONFIRMADO]
    assert espiao.agendados == [linhas[0].id]
    # O aviso e do job da RN-12.1; o turno nao duplica a mensagem.
    assert outbound.entregues == []


async def test_a_reserva_que_vence_nao_deixa_o_lead_sem_resposta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 3: confirmar tarde demais devolve horarios, e nao silencio."""
    await _semear_corretor(session)
    dubles = {
        "classificador_fake": classificador_fake,
        "outbound_fake": outbound_fake,
        "resumidor_fake": resumidor_fake,
        "contador_fake": contador_fake,
        "moderador_fake": moderador_fake,
    }
    await _turno(session, "quero agendar uma visita", **dubles)
    await _turno(session, "a primeira", **dubles)

    await session.execute(
        Agendamento.__table__.update()
        .where(Agendamento.conversation_key == LEAD)
        .values(reservado_ate=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()

    resultado, outbound = await _turno(session, "sim", **dubles)

    assert resultado == "agendamento_oferecido"
    assert "expirou" in outbound.entregues[0]
    assert "1." in outbound.entregues[0]
    assert [linha.status for linha in await _agendamentos(session)] == [
        StatusDoAgendamento.EXPIRADO
    ]


async def test_dois_leads_no_mesmo_slot(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 4 (CA-11.2): um agendamento e criado, o outro recebe alternativas."""
    await _semear_corretor(session)
    dubles = {
        "classificador_fake": classificador_fake,
        "outbound_fake": outbound_fake,
        "resumidor_fake": resumidor_fake,
        "contador_fake": contador_fake,
        "moderador_fake": moderador_fake,
    }
    for lead in (LEAD, OUTRO_LEAD):
        await _turno(session, "quero agendar uma visita", lead=lead, **dubles)

    await _turno(session, "a primeira", lead=LEAD, **dubles)
    await _turno(session, "isso, pode marcar", lead=LEAD, **dubles)

    resultado, outbound = await _turno(session, "a primeira", lead=OUTRO_LEAD, **dubles)

    assert resultado == "agendamento_oferecido"
    assert "preenchido" in outbound.entregues[0]
    # Um agendamento, e so um: o segundo lead nao tem linha nenhuma ainda.
    assert [linha.status for linha in await _agendamentos(session, LEAD)] == [
        StatusDoAgendamento.CONFIRMADO
    ]
    assert await _agendamentos(session, OUTRO_LEAD) == []
    # E o horario perdido nao aparece nas alternativas.
    tomado = (await _agendamentos(session, LEAD))[0].inicio.astimezone(SP)
    hora = f"{tomado.hour}h" if tomado.minute == 0 else f"{tomado.hour}h{tomado.minute:02d}"
    assert f"às {hora}" not in outbound.entregues[0]


async def _semear_corretor(session) -> Corretor:
    """Um corretor de plantao, para a alocacao ter a quem cair.

    Escrito aqui e nao pela fixture `semear_corretor` porque os arquivos de
    `tests/features/` sao autocontidos: eles descrevem o cenario inteiro.
    """
    agora = datetime.now(UTC)
    corretor = Corretor(
        id=uuid.uuid4(),
        nome="Paula M.",
        email="paula@imobiliaria.com.br",
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

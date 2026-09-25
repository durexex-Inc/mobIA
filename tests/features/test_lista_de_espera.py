"""Cenarios Gherkin de TEC-169.

Funcionalidade: Lista de espera por indisponibilidade

Os quatro cenarios da card, cada um num teste, rodando o turno inteiro por
`executar_turno` -- mesmo angulo de `test_agendamento_pela_conversa.py`: as
assertas sao sobre **o que o lead le** e sobre **o que existe no banco**, que
e a linguagem dos criterios de aceite.

**O cenario todo depende de a agenda estar cheia**, e e `_lotar_agenda` que
produz isso: um agendamento por dia cobrindo a jornada inteira do unico
corretor, nos quatro dias que a janela de 72 horas alcanca. Sem corretor
nenhum seria mais facil, e nao serviria -- `_oferecer` cai fora na primeira
linha quando nao ha corretores, e o caminho que esta card constroi nunca
seria exercitado.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agendamento.espera import (
    TEXTO_DA_ESPERA_ACEITA,
    TEXTO_DA_LISTA_DE_ESPERA,
)
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import (
    Agendamento,
    JanelaProposta,
    ListaDeEspera,
    StatusDoAgendamento,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.agente.turno import executar_turno
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, Gatilho
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

SP = ZoneInfo("America/Sao_Paulo")
CANAL = "whatsapp"
LEAD = "5511911117777"


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
        agendador_de_avisos=AgendadorDeAvisosNoop(),
    )
    return resultado, outbound


async def _semear_corretor(session) -> Corretor:
    """Um corretor de plantao, para a alocacao ter a quem cair.

    Escrito aqui e nao pela fixture `semear_corretor` porque os arquivos de
    `tests/features/` sao autocontidos: eles descrevem o cenario inteiro.
    """
    agora = datetime.now(UTC)
    corretor = Corretor(
        id=uuid.uuid4(),
        nome="Paula M.",
        email=f"paula-{uuid.uuid4().hex[:8]}@imobiliaria.com.br",
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


async def _lotar_agenda(session, corretor: Corretor) -> None:
    """Ocupa a jornada inteira dos proximos quatro dias.

    Quatro, e nao tres: `HORIZONTE` sao 72 horas a partir de AGORA, entao a
    janela morde parte do quarto dia quando a suite roda de tarde. Deixar o
    ultimo dia livre faria o teste passar de manha e falhar a noite -- o tipo
    de flake por relogio que `_proxima_quinta` em
    `test_agendamento_pela_conversa.py` tambem evita de proposito.

    Um agendamento por dia cobrindo 9h-18h, e nao varios de uma hora: a
    constraint de exclusao por intervalo da 0044 recusa sobreposicao, e um
    bloco unico por dia e o jeito mais curto de nao esbarrar nela.
    """
    agora = datetime.now(UTC)
    hoje = datetime.now(SP).date()
    for dia in range(4):
        data = hoje + timedelta(days=dia)
        inicio = datetime.combine(data, datetime.min.time(), tzinfo=SP).replace(hour=9)
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


async def _espera(session, lead: str = LEAD) -> ListaDeEspera | None:
    return (
        await session.scalars(select(ListaDeEspera).where(ListaDeEspera.conversation_key == lead))
    ).one_or_none()


async def test_oferecer_lista_quando_nao_ha_vaga_em_72_horas(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 1: o agente oferece a lista e explica a alternativa.

    O criterio da card diz "e explica que o corretor entrara em contato". **O
    texto NAO diz isso**, e a divergencia e deliberada: essa e uma das frases
    que `tests/unit/test_promessa_ao_lead.py` proibe, porque nada garante que
    alguem procure o lead. O que ele afirma e o que e verdade -- que existe
    uma fila de corretor --, e esta asserta prende justamente isso.
    """
    corretor = await _semear_corretor(session)
    await _lotar_agenda(session, corretor)

    resultado, outbound = await _turno(
        session,
        "quero agendar uma visita",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    assert resultado == "espera_oferecida"
    # `endswith` e nao igualdade: este e o primeiro turno da conversa, entao
    # `TEXTO_DA_IDENTIFICACAO` prefixa a resposta (RN-04.1). O que a card pede
    # e que a oferta chegue ao lead, e nao que ela chegue sozinha.
    (entregue,) = outbound.entregues
    assert entregue.endswith(TEXTO_DA_LISTA_DE_ESPERA)
    assert "fila" in entregue
    # A promessa proibida nao aparece, e este e o ponto do cenario.
    assert "entrar em contato" not in entregue

    linha = await _espera(session)
    assert linha is not None, "a oferta tem de ter ficado gravada"
    assert linha.oferecida_em is not None
    # Oferecer NAO poe na fila: so o aceite faz isso (D3).
    assert linha.aceita_em is None
    assert linha.handoff_id is None

    # Nenhuma janela foi gravada -- nao havia o que oferecer.
    assert not (
        await session.scalars(select(JanelaProposta).where(JanelaProposta.conversation_key == LEAD))
    ).all()


async def test_aceitar_a_lista_cria_handoff(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 2: o aceite poe na fila e abre handoff, na mesma transacao."""
    corretor = await _semear_corretor(session)
    await _lotar_agenda(session, corretor)
    await _turno(
        session,
        "quero agendar uma visita",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    resultado, outbound = await _turno(
        session,
        "pode ser, sim",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    assert resultado == "espera_aceita"
    assert outbound.entregues == [TEXTO_DA_ESPERA_ACEITA]

    linha = await _espera(session)
    assert linha is not None
    # "entra na lista com o momento de entrada registrado", literal da card.
    assert linha.aceita_em is not None
    assert linha.handoff_id is not None

    handoff = (await session.scalars(select(Handoff).where(Handoff.id == linha.handoff_id))).one()
    assert handoff.gatilho == Gatilho.SEM_DISPONIBILIDADE.value
    assert handoff.etiqueta == ETIQUETA_DE[Gatilho.SEM_DISPONIBILIDADE]
    assert handoff.conversation_key == LEAD


async def test_lead_pode_preferir_data_mais_distante(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Cenario 4: recusar a fila abre o horizonte, e ele NAO entra na lista.

    A agenda esta lotada so nos quatro primeiros dias, entao o horizonte
    estendido de catorze encontra janela -- e e exatamente essa diferenca que
    o cenario existe para mostrar: as mesmas 72 horas que nao tinham nada.
    """
    corretor = await _semear_corretor(session)
    await _lotar_agenda(session, corretor)
    await _turno(
        session,
        "quero agendar uma visita",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    resultado, outbound = await _turno(
        session,
        "não, prefiro ver horários da semana seguinte",
        classificador_fake=classificador_fake,
        outbound_fake=outbound_fake,
        resumidor_fake=resumidor_fake,
        contador_fake=contador_fake,
        moderador_fake=moderador_fake,
    )

    assert resultado == "agendamento_oferecido"
    linha = await _espera(session)
    assert linha is not None
    # "e ele nao entra na lista", literal da card.
    assert linha.recusada_em is not None
    assert linha.aceita_em is None

    # "janelas alem das 72 horas sao propostas".
    propostas = (
        await session.scalars(select(JanelaProposta).where(JanelaProposta.conversation_key == LEAD))
    ).all()
    assert propostas, "o horizonte estendido tinha de achar janela"
    limite = datetime.now(UTC) + timedelta(hours=72)
    assert all(p.inicio > limite for p in propostas)

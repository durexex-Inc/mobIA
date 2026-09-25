"""O desvio de agendamento dentro do turno. TEC-371, D9.

O que se prova aqui nao e o agendamento em si -- isso e
`test_conversa_de_agendamento.py` -- e sim a POSICAO do desvio na ordem do
turno: abaixo das guardas de silencio, abaixo da moderacao de entrada, acima
da chamada ao modelo. E que o enfileiramento do aviso da RN-12.1 acontece
depois do commit.

Mesma montagem de `executar_turno` que `test_turno_midia.py` usa; os dubles
vem de `tests/conftest.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agendamento.conversa import KIND_DO_AGENDAMENTO, SUBAGENTE_AGENDAMENTO
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agente.turno import executar_turno
from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.repositorio import registrar_optout
from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911114444"


class _AgendadorEspiao:
    """Guarda o que foi enfileirado E o que o banco ja enxergava na hora.

    A segunda metade e o ponto: a card exige que o enfileiramento aconteca
    **depois do commit**, e a unica forma de provar isso e perguntar ao banco,
    por uma sessao propria, no momento exato da chamada. Um job consumido
    antes do commit nao encontraria a linha.
    """

    def __init__(self) -> None:
        self.agendados: list[uuid.UUID] = []
        self.cancelados: list[uuid.UUID] = []
        self.status_no_momento: list[str | None] = []

    async def confirmacao(self, agendamento_id: uuid.UUID) -> None:
        await self._registrar(agendamento_id, self.agendados)

    async def cancelamento(self, agendamento_id: uuid.UUID) -> None:
        await self._registrar(agendamento_id, self.cancelados)

    async def _registrar(self, agendamento_id: uuid.UUID, onde: list[uuid.UUID]) -> None:
        onde.append(agendamento_id)
        async with get_sessionmaker()() as sessao:
            self.status_no_momento.append(
                await sessao.scalar(
                    select(Agendamento.status).where(Agendamento.id == agendamento_id)
                )
            )


async def _gravar(session, texto: str) -> Message:
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=CONVERSA,
        recipient_external_id="222222222",
        conversation_key=CONVERSA,
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


async def _rodar(
    message,
    classificador,
    outbound,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    *,
    moderador=None,
    agendador_de_avisos=None,
):
    return await executar_turno(
        get_sessionmaker(),
        message=message,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=moderador if moderador is not None else moderador_fake(),
        agendador=AgendadorNoop(),
        agendador_de_avisos=(
            agendador_de_avisos if agendador_de_avisos is not None else AgendadorDeAvisosNoop()
        ),
    )


async def _kinds(session, message_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.scalars(
                select(OutboundDispatch.kind).where(OutboundDispatch.message_id == message_id)
            )
        ).all()
    )


async def test_o_pedido_de_visita_nao_chama_o_modelo(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    await semear_corretor(email="a@x.com", plantao=True)
    await session.commit()
    entrada = await _gravar(session, "quero agendar uma visita")
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "agendamento_oferecido"
    assert classificador.chamadas == 0
    assert len(outbound.entregues) == 1
    assert "1." in outbound.entregues[0]
    assert await _kinds(session, entrada.id) == [KIND_DO_AGENDAMENTO]
    subagentes = (await session.scalars(select(MessageTelemetry.subagent))).all()
    assert subagentes == [SUBAGENTE_AGENDAMENTO]


async def test_sem_corretor_o_turno_normal_acontece(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """`NadaAFazer` nao encurta o turno: o modelo responde como sempre."""
    entrada = await _gravar(session, "quero agendar uma visita")
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 1


async def test_optout_vence_o_agendamento(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    await semear_corretor(email="b@x.com", plantao=True)
    await registrar_optout(
        get_sessionmaker(), channel=CANAL, conversation_key=CONVERSA, message_id=uuid.uuid4()
    )
    await session.commit()
    entrada = await _gravar(session, "quero agendar uma visita")
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada, classificador_fake(), outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "silenciado"
    assert outbound.entregues == []


async def test_conversa_assumida_vence_o_agendamento(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    corretor = await semear_corretor(email="c@x.com", plantao=True)
    await assumir(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        corretor_id=corretor.id,
    )
    await session.commit()
    entrada = await _gravar(session, "quero agendar uma visita")
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada, classificador_fake(), outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "atendimento_humano"
    assert outbound.entregues == []


async def test_fala_recusada_na_entrada_nao_marca_visita(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    await semear_corretor(email="d@x.com", plantao=True)
    await session.commit()
    entrada = await _gravar(session, "quero agendar uma visita")
    outbound = outbound_fake()

    await _rodar(
        entrada,
        classificador_fake(),
        outbound,
        resumidor_fake,
        contador_fake,
        moderador_fake,
        moderador=moderador_fake(bloqueia_entrada=True),
    )

    assert KIND_DO_AGENDAMENTO not in await _kinds(session, entrada.id)


async def test_a_confirmacao_enfileira_depois_do_commit(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    """O segundo cenario do Gherkin, na parte que so uma asserta de ordem prova."""
    await semear_corretor(email="e@x.com", plantao=True)
    await session.commit()

    for texto in ("quero agendar uma visita", "a primeira"):
        entrada = await _gravar(session, texto)
        await _rodar(
            entrada,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake,
            contador_fake,
            moderador_fake,
        )

    espiao = _AgendadorEspiao()
    entrada = await _gravar(session, "isso, pode marcar")
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada,
        classificador_fake(),
        outbound,
        resumidor_fake,
        contador_fake,
        moderador_fake,
        agendador_de_avisos=espiao,
    )

    assert resultado == "agendamento_confirmado"
    assert len(espiao.agendados) == 1
    # A linha ja estava commitada quando o job foi enfileirado.
    assert espiao.status_no_momento == [StatusDoAgendamento.CONFIRMADO]
    # O turno nao manda texto: quem manda e o job da RN-12.1 (D6).
    assert outbound.entregues == []


async def test_a_reserva_expira_e_o_lead_recebe_horarios_de_novo(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    """Terceiro cenario do Gherkin, pelo turno inteiro."""
    await semear_corretor(email="f@x.com", plantao=True)
    await session.commit()

    for texto in ("quero agendar uma visita", "a primeira"):
        entrada = await _gravar(session, texto)
        await _rodar(
            entrada,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake,
            contador_fake,
            moderador_fake,
        )

    # Envelhece a reserva em vez de dormir cinco minutos.
    await session.execute(
        Agendamento.__table__.update()
        .where(Agendamento.conversation_key == CONVERSA)
        .values(reservado_ate=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()

    entrada = await _gravar(session, "isso, pode marcar")
    outbound = outbound_fake()
    resultado = await _rodar(
        entrada, classificador_fake(), outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "agendamento_oferecido"
    assert "expirou" in outbound.entregues[0]
    status = (
        await session.scalars(
            select(Agendamento.status).where(Agendamento.conversation_key == CONVERSA)
        )
    ).all()
    assert list(status) == [StatusDoAgendamento.EXPIRADO]


# --- TEC-372: a resposta ao lembrete, pelo turno inteiro ---------------------


async def _agendamento_com_lembrete(session, semear_corretor) -> Agendamento:
    corretor = await semear_corretor(email="lembrete@x.com", plantao=True)
    inicio = datetime.now(UTC) + timedelta(hours=20)
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor.id,
        channel=CANAL,
        conversation_key=CONVERSA,
        imovel_id=None,
        tipo="VISITA_PRESENCIAL",
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        status=StatusDoAgendamento.CONFIRMADO,
        reservado_ate=datetime.now(UTC),
        criado_em=datetime.now(UTC),
        confirmado_em=datetime.now(UTC),
        motivo_da_alocacao="MATCH_EXATO",
        lembrete_24h_em=datetime.now(UTC) - timedelta(minutes=5),
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def test_o_cancelamento_avisa_o_corretor_depois_do_commit(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    agendamento = await _agendamento_com_lembrete(session, semear_corretor)
    espiao = _AgendadorEspiao()
    entrada = await _gravar(session, "preciso cancelar")
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada,
        classificador_fake(),
        outbound,
        resumidor_fake,
        contador_fake,
        moderador_fake,
        agendador_de_avisos=espiao,
    )

    assert resultado == "agendamento_cancelado"
    assert espiao.cancelados == [agendamento.id]
    assert espiao.agendados == []
    # A linha ja estava CANCELADA quando o job foi enfileirado.
    assert espiao.status_no_momento == [StatusDoAgendamento.CANCELADO]
    # E o lead soube na hora: quem fala aqui e o turno, nao o job.
    assert len(outbound.entregues) == 1
    assert "cancelei" in outbound.entregues[0]


async def test_a_presenca_confirmada_nao_enfileira_nada(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    agendamento = await _agendamento_com_lembrete(session, semear_corretor)
    espiao = _AgendadorEspiao()
    entrada = await _gravar(session, "sim, estarei la")
    outbound = outbound_fake()

    resultado = await _rodar(
        entrada,
        classificador_fake(),
        outbound,
        resumidor_fake,
        contador_fake,
        moderador_fake,
        agendador_de_avisos=espiao,
    )

    assert resultado == "presenca_confirmada"
    assert espiao.agendados == [] and espiao.cancelados == []
    assert len(outbound.entregues) == 1
    await session.refresh(agendamento)
    assert agendamento.presenca_confirmada_em is not None

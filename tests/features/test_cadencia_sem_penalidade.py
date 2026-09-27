"""Criterios de aceite da TEC-385. Emenda E-02 a RN-12.4 e a RN-13.1.

O nao comparecimento e marcado pela rota de verdade (TEC-374), e o que se
afirma e o que cada leitor da temperatura ve depois: a varredura de follow-up
(`candidatos_a_followup`) a da cadencia, o SLA do handoff a de sempre.

**O SLA e afirmado na funcao, e nao abrindo um handoff.** `prazo_em_minutos`
recebe `lead_qualification.temperatura` em `notificacao/envio.py`, e o que
esta card garante e que essa coluna continua com a penalidade; abrir um
handoff inteiro so reexercitaria a TEC-177.
"""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import _corretor
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agente.schemas import FormaPagamento, Intencao, TipoImovel, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import registrar_recalculo
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA
from mobia.domain.followup.repositorio import candidatos_a_followup
from mobia.domain.handoff.sla import PRAZO_PADRAO_MINUTOS, prazo_em_minutos
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.usuarios import tokens
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
CONVERSA = "5511922223333"


def _bearer_do_corretor(corretor_id: uuid.UUID) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), "CORRETOR", mfa=False, corretor_id=corretor_id, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _lead_quente(session: AsyncSession) -> None:
    """Um lead qualificado e QUENTE pela faixa, com a ultima fala ha dias.

    As falas existem por dois motivos: o fator de engajamento, sem o qual o
    score nao alcanca 70, e a ancora da cadencia, sem a qual o lead nao e
    candidato a follow-up.
    """
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            tipo_imovel=TipoImovel.APARTAMENTO.value,
            faixa_preco_max_centavos=60_000_000,
            regiao="zona sul",
            urgencia=Urgencia.IMEDIATA.value,
            forma_pagamento=FormaPagamento.A_VISTA.value,
        )
    )
    for _ in range(6):
        identificador = uuid.uuid4()
        session.add(
            Message(
                id=identificador,
                channel=CANAL,
                provider_message_id=f"wamid.{identificador.hex[:12]}",
                sender_external_id=CONVERSA,
                conversation_key=CONVERSA,
                role=MessageRole.LEAD,
                direction=MessageDirection.INBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=encrypt("quero visitar", aad_de(identificador, "text_body")),
                status=MessageStatus.PROCESSED,
                created_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
    await session.commit()
    recalculo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert recalculo is not None
    assert recalculo.temperatura is Temperatura.QUENTE, recalculo.total


async def _no_show(session: AsyncSession, client: AsyncClient) -> None:
    corretor = await _corretor(session)
    inicio = datetime.now(UTC) - timedelta(hours=2)
    agendamento = uuid.uuid4()
    session.add(
        Agendamento(
            id=agendamento,
            corretor_id=corretor,
            channel=CANAL,
            conversation_key=CONVERSA,
            imovel_id=None,
            tipo="VISITA_PRESENCIAL",
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            status=StatusDoAgendamento.CONFIRMADO,
            reservado_ate=inicio,
            criado_em=inicio - timedelta(days=1),
            confirmado_em=inicio - timedelta(days=1),
            motivo_da_alocacao="MATCH_EXATO",
        )
    )
    await session.commit()
    resposta = await client.post(
        f"/api/v1/agendamentos/{agendamento}/nao-comparecimento",
        headers=_bearer_do_corretor(corretor),
    )
    assert resposta.status_code == 200, resposta.text


async def _estado(session: AsyncSession) -> LeadQualification:
    estado = await session.get(LeadQualification, (CANAL, CONVERSA), populate_existing=True)
    assert estado is not None
    return estado


async def test_lead_quente_que_falta_continua_com_a_regua_de_quente(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario: Lead QUENTE que falta continua com a regua de QUENTE.

    A temperatura viva cai (a penalidade vale), e a da cadencia nao: a
    varredura ve o lead como QUENTE, com as 4 tentativas.
    """
    await _lead_quente(session)
    antes = (await _estado(session)).temperatura

    await _no_show(session, client)

    estado = await _estado(session)
    assert antes == Temperatura.QUENTE
    assert estado.penalidade_pontos == 15
    assert estado.temperatura == Temperatura.MORNO
    assert estado.temperatura_da_cadencia == Temperatura.QUENTE

    [candidato] = await candidatos_a_followup(session, agora=datetime.now(UTC))
    assert candidato.temperatura is Temperatura.QUENTE
    assert len(CADENCIA[candidato.temperatura]) == 4


async def test_a_penalidade_continua_valendo_para_o_sla_do_corretor(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario: A penalidade continua valendo para o SLA do corretor."""
    await _lead_quente(session)

    await _no_show(session, client)

    estado = await _estado(session)
    assert prazo_em_minutos(estado.temperatura) == PRAZO_PADRAO_MINUTOS


async def test_lead_sem_nao_comparecimento_nao_muda_nada(
    session: AsyncSession, banco_limpo: None
) -> None:
    """Cenario: Lead sem nao comparecimento nao muda nada."""
    await _lead_quente(session)

    estado = await _estado(session)
    assert estado.temperatura_da_cadencia == estado.temperatura
    [candidato] = await candidatos_a_followup(session, agora=datetime.now(UTC))
    assert candidato.temperatura.value == estado.temperatura

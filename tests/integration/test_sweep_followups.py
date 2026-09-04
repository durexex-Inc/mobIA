"""A varredura da cadencia, ponta a ponta.

TEC-183. Integracao: a decisao mora na funcao pura, mas quem entra na
varredura e o que ela grava so da para verificar contra o banco.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.followup.models import FollowUp
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_followups import sweep_followups

CANAL = "whatsapp"
CONVERSA = "5511944443333"


async def _lead(session, *, temperatura: str | None = "QUENTE", calado_ha: timedelta) -> None:
    """Um lead com temperatura e uma fala de entrada com a idade pedida."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=datetime.now(UTC) - calado_ha,
        )
    )
    await session.commit()


def _ctx() -> dict:
    return {"session_factory": get_sessionmaker()}


async def test_o_quente_calado_ha_duas_horas_recebe_a_primeira(session, caplog) -> None:
    """A CA-13.1, ponta a ponta."""
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5))

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx())

    assert gravadas == 1
    linhas = (await session.scalars(select(FollowUp))).all()
    assert len(linhas) == 1
    assert linhas[0].tentativa_numero == 1
    assert linhas[0].temperatura == "QUENTE"
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 1


async def test_o_lead_com_optout_nao_recebe_nada(session, caplog) -> None:
    """O criterio de aceite do opt-out. `esta_em_optout` e a unica
    implementacao desse fato, e a varredura a consulta em vez de reescrever a
    regra em SQL."""
    await _lead(session, calado_ha=timedelta(days=30))
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            evento=EVENTO_OPT_OUT,
        )
    )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx())

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0


async def test_o_lead_muito_atrasado_recebe_uma_tentativa_so(session) -> None:
    """A guarda contra a rajada: dez dias de silencio dao as quatro do QUENTE
    vencidas, e a varredura grava so a quarta. Rodar de novo nao grava mais
    nada."""
    await _lead(session, calado_ha=timedelta(days=10))

    assert await sweep_followups(_ctx()) == 1
    assert await sweep_followups(_ctx()) == 0

    linhas = (await session.scalars(select(FollowUp))).all()
    assert [linha.tentativa_numero for linha in linhas] == [4]


async def test_a_varredura_e_idempotente_na_mesma_passagem(session) -> None:
    """Duas varreduras concorrentes veriam o mesmo candidato. O UNIQUE absorve,
    e o job nao levanta -- devolve zero na segunda."""
    await _lead(session, calado_ha=timedelta(hours=3))

    assert await sweep_followups(_ctx()) == 1
    assert await sweep_followups(_ctx()) == 0


async def test_o_lead_que_falou_ha_pouco_nao_entra(session) -> None:
    await _lead(session, calado_ha=timedelta(minutes=30))

    assert await sweep_followups(_ctx()) == 0


async def test_o_lead_sem_temperatura_nao_entra(session) -> None:
    """A D3, ponta a ponta."""
    await _lead(session, temperatura=None, calado_ha=timedelta(days=30))

    assert await sweep_followups(_ctx()) == 0

"""A cadencia de reengajamento nao alcanca o canal web. TEC-124, D8."""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.followup.repositorio import candidatos_a_followup, listar_dormentes
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
AGORA = ANCORA + timedelta(days=3)


async def _lead(session, *, canal: str, conversa: str) -> None:
    """Um lead qualificado e quente, com a fala ancora ja velha.

    Mesma forma de `_qualificacao` e `_fala_do_lead` em
    `test_followups_model.py`, com o canal por parametro -- la ele e a
    constante `CANAL` do modulo.
    """
    session.add(
        LeadQualification(
            channel=canal,
            conversation_key=conversa,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura="QUENTE",
        )
    )
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=canal,
            provider_message_id=f"id.{identificador.hex[:10]}",
            sender_external_id=conversa,
            recipient_external_id="222222222",
            conversation_key=conversa,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=ANCORA,
        )
    )
    await session.commit()


async def test_lead_do_web_nao_vira_candidato(session) -> None:
    await _lead(session, canal=CANAL_WHATSAPP, conversa="5511955554444")
    await _lead(session, canal=CANAL_WEB, conversa="8c0f0a3e-0000-4000-8000-0000000000dd")

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    # O do WhatsApp aparecer e o que impede este teste de passar por nao
    # achar ninguem: a asserta e sobre QUEM sai, nao so sobre quem nao sai.
    assert [candidato.channel for candidato in candidatos] == [CANAL_WHATSAPP]


async def test_lead_do_web_tambem_nao_aparece_entre_os_dormentes(session) -> None:
    """A mesma CTE serve as duas consultas -- e este teste e o que prova que o
    filtro ficou na CTE compartilhada e nao so na primeira delas.

    Para ser dormente o lead precisa ter esgotado a cadencia; sem follow-up
    registrado nenhum, os dois leads abaixo NAO sao dormentes, e o teste nao
    provaria nada. Ver `_esgotar`.
    """
    await _lead(session, canal=CANAL_WHATSAPP, conversa="5511955554445")
    await _lead(session, canal=CANAL_WEB, conversa="8c0f0a3e-0000-4000-8000-0000000000de")
    await _esgotar(session, canal=CANAL_WHATSAPP, conversa="5511955554445")
    await _esgotar(session, canal=CANAL_WEB, conversa="8c0f0a3e-0000-4000-8000-0000000000de")

    dormentes = await listar_dormentes(session, agora=AGORA)

    assert [dormente.channel for dormente in dormentes] == [CANAL_WHATSAPP]


async def _esgotar(session, *, canal: str, conversa: str) -> None:
    """Grava todas as tentativas da cadencia QUENTE sob a ancora."""
    from mobia.domain.context.temperatura import Temperatura
    from mobia.domain.followup.cadencia import CADENCIA
    from mobia.domain.followup.models import FollowUp

    for numero in range(1, len(CADENCIA[Temperatura.QUENTE]) + 1):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=canal,
                conversation_key=conversa,
                tentativa_numero=numero,
                temperatura="QUENTE",
                ancora_em=ANCORA,
                devido_em=ANCORA + timedelta(hours=numero),
            )
        )
    await session.commit()

"""A RN-13.5 pelo lado da consulta: quem esgotou a cadencia e ainda da para
segmentar.

TEC-187. Integracao: a pergunta e sobre o que a consulta enxerga.
"""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA
from mobia.domain.followup.models import FollowUp
from mobia.domain.followup.repositorio import listar_dormentes
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
AGORA = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

TETO_MORNO = len(CADENCIA[Temperatura.MORNO])


async def _falar(session, *, conversa: str, em: datetime) -> uuid.UUID:
    """Uma fala de entrada do lead no momento pedido. E ela que ancora."""
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=conversa,
            recipient_external_id="222222222",
            conversation_key=conversa,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=em,
        )
    )
    return identificador


async def _lead_dormente(
    session,
    *,
    conversa: str,
    temperatura: str | None = "MORNO",
    calado_ha: timedelta = timedelta(days=30),
    tentativas: int = TETO_MORNO,
) -> datetime:
    """Um lead calado com `tentativas` follow-ups gravados sob a ancora.

    Devolve a ancora. O `created_at` de cada linha e explicito e crescente
    porque e ele que `adormeceu_em` le -- em producao quem as grava e a
    varredura, uma por passagem, e a ordem sai da mesma monotonicidade.
    """
    ancora = AGORA - calado_ha
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=conversa,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    await _falar(session, conversa=conversa, em=ancora)
    for numero in range(1, tentativas + 1):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=conversa,
                tentativa_numero=numero,
                temperatura=temperatura or "MORNO",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
                created_at=ancora + timedelta(days=numero),
            )
        )
    await session.commit()
    return ancora


async def test_o_lead_que_esgotou_o_morno_aparece(session) -> None:
    """Cenario 1 da card: tres tentativas sem resposta, e ele esta dormente."""
    await _lead_dormente(session, conversa="5511900000001")

    dormentes = await listar_dormentes(session, agora=AGORA)

    assert [d.conversation_key for d in dormentes] == ["5511900000001"]


async def test_uma_tentativa_abaixo_do_teto_nao_aparece(session) -> None:
    """A outra metade da assertiva acima: a consulta nao pode devolver todo
    mundo que tem alguma linha de `followups`."""
    await _lead_dormente(session, conversa="5511900000002", tentativas=TETO_MORNO - 1)

    assert await listar_dormentes(session, agora=AGORA) == []


async def test_a_data_e_a_contagem_da_transicao(session) -> None:
    """Cenario 2 da card.

    Nada disto e gravado por esta card: sai da linha de `followups` de maior
    `tentativa_numero`, que a TEC-183 ja grava.
    """
    ancora = await _lead_dormente(session, conversa="5511900000003")

    (dormente,) = await listar_dormentes(session, agora=AGORA)

    assert dormente.tentativas == TETO_MORNO
    assert dormente.adormeceu_em == ancora + timedelta(days=TETO_MORNO)
    assert dormente.ancora_em == ancora
    assert dormente.temperatura is Temperatura.MORNO


async def test_quem_respondeu_depois_de_esgotar_deixa_de_ser_dormente(session) -> None:
    """Cenario 4 da card, e sem codigo de reativacao nenhum: a fala nova move
    a ancora, e nao ha linha de `followups` sob a ancora nova."""
    await _lead_dormente(session, conversa="5511900000004")
    await _falar(session, conversa="5511900000004", em=AGORA - timedelta(hours=1))
    await session.commit()

    assert await listar_dormentes(session, agora=AGORA) == []


async def test_o_dormente_com_optout_fica_de_fora(session) -> None:
    """A lista alimenta campanha manual, e a RN-14.3 condiciona qualquer novo
    contato de quem pediu opt-out a acao humana com justificativa."""
    await _lead_dormente(session, conversa="5511900000005")
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key="5511900000005",
            evento=EVENTO_OPT_OUT,
        )
    )
    await session.commit()

    assert await listar_dormentes(session, agora=AGORA) == []


async def test_o_lead_sem_temperatura_nao_aparece(session) -> None:
    """Lacuna L3 do desenho, testada para ser verificavel e nao so afirmada.

    Quem escreveu antes da TEC-151 e nunca mais falou nao e candidato NEM
    dormente -- e invisivel as duas consultas, e esta linha e o registro de
    que isso e escolha e nao esquecimento.
    """
    await _lead_dormente(session, conversa="5511900000006", temperatura=None, tentativas=4)

    assert await listar_dormentes(session, agora=AGORA) == []

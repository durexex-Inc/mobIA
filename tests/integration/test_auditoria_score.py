"""A trilha de recalculos de score: tabela, imutabilidade e o gancho no turno.

TEC-152.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from mobia.domain.context.models import LeadScoreAudit
from mobia.domain.context.repositorio import contar_mensagens_do_lead
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def linha(**ajustes: object) -> LeadScoreAudit:
    """Um registro valido, com os cinco fatores somando o total."""
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "total_anterior": None,
        "total_novo": 51,
        "completude": 20,
        "urgencia": 15,
        "catalogo": 0,
        "engajamento": 10,
        "capacidade": 6,
        "causas": ["PRIMEIRO_CALCULO"],
    }
    return LeadScoreAudit(**{**base, **ajustes})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    session.add(linha())
    await session.commit()

    gravado = (await session.scalars(select(LeadScoreAudit))).one()
    assert gravado.total_novo == 51
    assert gravado.total_anterior is None
    assert gravado.causas == ["PRIMEIRO_CALCULO"]
    assert gravado.autor is None
    assert gravado.created_at is not None


async def test_o_check_recusa_um_total_que_nao_soma(session) -> None:
    """O total e denormalizado de proposito -- e por ele que se ordena --, e a
    restricao e o que impede a denormalizacao de mentir."""
    session.add(linha(total_novo=99))

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_update_e_recusado_pela_trigger(session) -> None:
    """Cenario 3 da card: "quando se tenta altera-lo, a operacao e recusada"."""
    session.add(linha())
    await session.commit()

    with pytest.raises(DBAPIError, match="imutavel"):
        await session.execute(text("UPDATE lead_score_audit SET total_novo = 99"))

    # A transacao fica abortada depois da excecao do Postgres; sem isto o
    # teardown da fixture reclama em vez de fechar limpo.
    await session.rollback()


async def test_delete_continua_livre(session) -> None:
    """Imutavel e "nao se altera o que foi registrado". A RNF-18 pede retencao
    de 12 meses, ou seja, pede que apagar seja possivel."""
    session.add(linha())
    await session.commit()

    await session.execute(text("DELETE FROM lead_score_audit"))
    await session.commit()

    assert (await session.scalars(select(LeadScoreAudit))).all() == []


async def _mensagem(
    session,
    *,
    direction: MessageDirection = MessageDirection.INBOUND,
    bloqueada: bool = False,
) -> None:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD if direction is MessageDirection.INBOUND else MessageRole.AGENTE,
            direction=direction,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            bloqueada_em=datetime.now(UTC) if bloqueada else None,
        )
    )
    await session.commit()


async def test_a_contagem_ignora_a_fala_do_agente(session) -> None:
    """Fala do agente nao e engajamento do lead, e contar as duas direcoes
    quase dobra o numero e empurra MORNO para QUENTE de graca."""
    await _mensagem(session)
    await _mensagem(session, direction=MessageDirection.OUTBOUND)

    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key=CONVERSA) == 1


async def test_a_contagem_ignora_a_fala_bloqueada(session) -> None:
    """Um turno que o resto do produto trata como nao-dito nao pode virar ponto
    aqui: `literais_apos` ja filtra `bloqueada_em IS NULL` desde a TEC-236."""
    await _mensagem(session)
    await _mensagem(session, bloqueada=True)

    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key=CONVERSA) == 1


async def test_a_contagem_de_um_lead_sem_mensagem_e_zero(session) -> None:
    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key="ninguem") == 0

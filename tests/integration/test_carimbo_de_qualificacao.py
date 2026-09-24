"""O carimbo da primeira travessia de qualificacao. TEC-190, D2 e D3.

A coluna existe para a metrica RN-17.1, e o comentario de `turno.py` sobre a
reemissao de `lead.qualificado` declarou que a decisao era de quem fosse dono
dessa metrica. E esta card.
"""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import carimbar_qualificacao

CANAL = "whatsapp"
CONVERSA = "5511911112222"
AGORA = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _linha(session) -> None:
    session.add(LeadQualification(channel=CANAL, conversation_key=CONVERSA))
    await session.commit()


async def test_carimba_quando_a_coluna_esta_nula(session) -> None:
    await _linha(session)

    carimbou = await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=CONVERSA, quando=AGORA
    )
    await session.commit()

    assert carimbou is True
    linha = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.qualificado_em == AGORA


async def test_a_segunda_travessia_nao_move_o_carimbo(session) -> None:
    """A ida-e-volta da TEC-148 conta UMA vez. E a D3 do desenho."""
    await _linha(session)
    await carimbar_qualificacao(session, channel=CANAL, conversation_key=CONVERSA, quando=AGORA)
    await session.commit()

    carimbou = await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=CONVERSA, quando=AGORA + timedelta(days=3)
    )
    await session.commit()

    assert carimbou is False
    linha = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.qualificado_em == AGORA


async def test_lead_sem_linha_nao_cria_linha(session) -> None:
    """O UPDATE nao e upsert: sem linha, nao ha o que carimbar."""
    carimbou = await carimbar_qualificacao(
        session, channel=CANAL, conversation_key=f"55119{uuid.uuid4().hex[:8]}", quando=AGORA
    )
    await session.commit()

    assert carimbou is False


async def test_a_coluna_nasce_nula(session) -> None:
    """Sem backfill: `NULL` e "linha anterior a esta card". Lacuna L1."""
    await _linha(session)

    linha = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.qualificado_em is None

"""A trilha de recalculos de score: tabela, imutabilidade e o gancho no turno.

TEC-152.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from mobia.domain.context.models import LeadScoreAudit

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

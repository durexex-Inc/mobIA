"""A trilha de follow-ups, e as duas invariantes que o banco garante.

TEC-183. Integracao: o UNIQUE e o CHECK vivem no banco.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.followup.models import FollowUp

CANAL = "whatsapp"
CONVERSA = "5511955554444"
ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _linha(**campos) -> FollowUp:
    base = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "tentativa_numero": 1,
        "temperatura": "QUENTE",
        "ancora_em": ANCORA,
        "devido_em": ANCORA + timedelta(hours=2),
    }
    return FollowUp(**{**base, **campos})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    linha = _linha()
    session.add(linha)
    await session.commit()

    gravada = await session.get(FollowUp, linha.id)
    assert gravada is not None
    assert gravada.tentativa_numero == 1
    assert gravada.ancora_em == ANCORA
    # `server_default=clock_timestamp()`: o banco carimba, nao o cliente.
    assert gravada.created_at is not None


async def test_o_unique_recusa_a_mesma_tentativa_sob_a_mesma_ancora(session) -> None:
    """A defesa contra duas varredura concorrentes.

    Nao da para usar `FOR UPDATE SKIP LOCKED` sobre a agregacao que produz os
    candidatos, entao a exclusao mora aqui -- mesmo espirito dos CHECK da 0014
    e da 0012: a invariante no banco, e nao na esperanca de que so um worker
    rode.
    """
    session.add(_linha())
    await session.commit()

    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_mesma_tentativa_sob_outra_ancora_e_permitida(session) -> None:
    """O reinicio da RN-13.4: o lead respondeu, a ancora mudou, e a tentativa 1
    volta a ser legitima."""
    session.add(_linha())
    await session.commit()

    session.add(_linha(ancora_em=ANCORA + timedelta(days=1)))
    await session.commit()

    todas = (await session.scalars(select(FollowUp))).all()
    assert len(todas) == 2


async def test_o_check_recusa_tentativa_zero(session) -> None:
    """1-based e contrato, nao convencao: `ja_disparada = 0` significa "nenhuma
    disparou", e uma linha numero 0 tornaria os dois indistinguiveis."""
    session.add(_linha(tentativa_numero=0))
    with pytest.raises(IntegrityError):
        await session.commit()

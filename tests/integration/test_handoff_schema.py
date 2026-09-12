"""O schema de `handoffs`: o que so o Postgres prova."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _linha(status: str = "PENDENTE", conversa: str = CONVERSA) -> Handoff:
    return Handoff(
        id=uuid.uuid4(),
        channel=CANAL,
        conversation_key=conversa,
        gatilho="LEAD_QUENTE",
        etiqueta="lead-quente",
        prioridade="NORMAL",
        status=status,
        criado_em=datetime.now(UTC),
        atualizado_em=datetime.now(UTC),
    )


async def test_a_tabela_aceita_uma_linha_pendente(session: AsyncSession) -> None:
    session.add(_linha())
    await session.commit()
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 1


async def test_dois_pendentes_na_mesma_conversa_sao_recusados_pelo_banco(
    session: AsyncSession,
) -> None:
    """O UNIQUE parcial e a garantia da deduplicacao, nao a consulta.

    Sem ele, dois turnos concorrentes do mesmo lead criam dois handoffs -- e a
    concorrencia e prevista, nao hipotetica: `turno.py` declara que
    `lead.esquentou` reemite para o MESMO lead desde a TEC-148.
    """
    session.add(_linha())
    await session.commit()
    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_um_concluido_nao_bloqueia_um_pendente_novo(session: AsyncSession) -> None:
    """O indice so olha para PENDENTE.

    Um lead atendido meses atras que volta merece handoff novo -- por isso o
    `postgresql_where`, e nao um UNIQUE simples sobre o par.
    """
    session.add(_linha(status="CONCLUIDO"))
    await session.commit()
    session.add(_linha())
    await session.commit()
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 2


async def test_gatilhos_adicionais_nasce_vazio_e_nao_nulo(session: AsyncSession) -> None:
    """`array_append` sobre NULL funciona, mas o default vazio evita a duvida."""
    linha = _linha()
    session.add(linha)
    await session.commit()
    valor = await session.scalar(
        text("SELECT gatilhos_adicionais FROM handoffs WHERE id = :i"), {"i": linha.id}
    )
    assert valor == []

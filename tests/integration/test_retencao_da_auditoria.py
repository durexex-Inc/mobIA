"""A retencao da trilha: 11 meses fica, 13 meses sai. TEC-206, D6.

**Para antedatar, o teste desliga SO o trigger de insercao**, e so dentro da
propria transacao -- o DDL do Postgres e transacional, entao nenhuma outra
sessao ve o trigger desligado. O de UPDATE/DELETE continua ligado o tempo
todo, e e ele que estes testes exercitam: a retencao so passa porque as
linhas tem mais de 12 meses pelo relogio do BANCO.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.retencao import apagar_vencidos
from mobia.workers.jobs.sweep_retencao_auditoria import sweep_retencao_auditoria
from tests.conftest import eventos_de_log


async def _semear(session: AsyncSession, *, meses: int) -> uuid.UUID:
    evento_id = uuid.uuid4()
    await session.execute(
        text("ALTER TABLE eventos_auditoria DISABLE TRIGGER eventos_auditoria_carimbo")
    )
    await session.execute(
        text(
            "INSERT INTO eventos_auditoria (id, criado_em, ator_tipo, acao, entidade, "
            "entidade_id) VALUES (:id, clock_timestamp() - make_interval(months => :meses), "
            "'SISTEMA', 'HANDOFF_CRIADO', 'handoff', 'h')"
        ),
        {"id": evento_id, "meses": meses},
    )
    await session.execute(
        text("ALTER TABLE eventos_auditoria ENABLE TRIGGER eventos_auditoria_carimbo")
    )
    await session.commit()
    return evento_id


async def _ids(session: AsyncSession) -> set[uuid.UUID]:
    return set((await session.execute(select(EventoAuditoria.id))).scalars())


async def test_onze_meses_fica_e_treze_meses_sai(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    onze = await _semear(session, meses=11)
    await _semear(session, meses=13)

    apagadas = await apagar_vencidos(session_factory)

    assert apagadas == 1
    assert await _ids(session) == {onze}


async def test_o_trigger_continua_recusando_a_linha_de_onze_meses(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Prova que a retencao acima nao passou por o trigger estar desligado."""
    onze = await _semear(session, meses=11)

    with pytest.raises(DBAPIError, match="12 meses"):
        await session.execute(text("DELETE FROM eventos_auditoria WHERE id = :id"), {"id": onze})
    await session.rollback()


async def test_mais_vencidas_que_um_lote_saem_todas(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Review Focus 3: o laco de lotes termina e nao deixa vencida para tras."""
    onze = await _semear(session, meses=11)
    for _ in range(3):
        await _semear(session, meses=13)

    apagadas = await apagar_vencidos(session_factory, lote=1)

    assert apagadas == 3
    assert await _ids(session) == {onze}


async def test_lote_menor_que_um_e_recusado(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Com LIMIT 0 o laco nunca terminaria."""
    with pytest.raises(ValueError, match="lote"):
        await apagar_vencidos(session_factory, lote=0)


async def test_o_job_apaga_e_emite_a_contagem(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], caplog: Any
) -> None:
    await _semear(session, meses=13)

    with caplog.at_level("INFO"):
        apagadas = await sweep_retencao_auditoria({"session_factory": session_factory})

    assert apagadas == 1
    ((_, evento),) = eventos_de_log(caplog, "auditoria.retencao_executada")
    assert evento["apagadas"] == 1


async def test_sem_nada_vencido_nao_apaga_nada(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    onze = await _semear(session, meses=11)

    assert await apagar_vencidos(session_factory) == 0
    assert await _ids(session) == {onze}

"""A garantia da trilha no banco. TEC-206, D1, D2 e D3 do desenho.

**SQL cru de proposito** nos testes de UPDATE e DELETE: a regra mora no
trigger, e o que se prova e que ela vale fora do ORM -- para um script, para
uma migration errada, para qualquer caminho da aplicacao.

Tempo comparado sempre pelo relogio do BANCO: medido em 25/09/2026, o
Postgres local estava um ano atras do host.
"""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.registro import Origem, registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Ator, AtorTipo, Entidade

CANAL = "whatsapp"
TELEFONE = "5511911112222"

_INSERIR_CRU = text(
    "INSERT INTO eventos_auditoria (id, criado_em, ator_tipo, ator_id, acao, entidade, "
    "entidade_id) VALUES (:id, clock_timestamp() - interval '2 years', :ator_tipo, :ator_id, "
    ":acao, 'handoff', 'h')"
)


async def _um_evento(session: AsyncSession) -> uuid.UUID:
    evento_id = await registrar_evento(
        session,
        ator=ATOR_SISTEMA,
        acao=Acao.HANDOFF_CRIADO,
        entidade=Entidade.HANDOFF,
        entidade_id=str(uuid.uuid4()),
        lead=(CANAL, TELEFONE),
        detalhes={"gatilho": "LEAD_QUENTE"},
    )
    await session.commit()
    return evento_id


async def _total(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(EventoAuditoria)) or 0


async def test_registrar_nao_commita(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O molde de `registrar_recalculo`: a sessao e emprestada, o commit e de quem chama."""
    await registrar_evento(
        session,
        ator=ATOR_SISTEMA,
        acao=Acao.HANDOFF_CRIADO,
        entidade=Entidade.HANDOFF,
        entidade_id="h",
    )
    async with session_factory() as outra:
        assert await _total(outra) == 0

    await session.rollback()
    assert await _total(session) == 0


async def test_a_linha_guarda_o_lead_ref_e_nao_o_telefone(session: AsyncSession) -> None:
    evento_id = await _um_evento(session)

    linha = (
        (
            await session.execute(
                text("SELECT * FROM eventos_auditoria WHERE id = :id"), {"id": evento_id}
            )
        )
        .mappings()
        .one()
    )

    assert linha["lead_ref"] == lead_ref(
        CANAL, TELEFONE, chave=get_settings().auditoria_chave_do_lead
    )
    assert all(TELEFONE not in str(valor) for valor in linha.values())
    assert linha["detalhes"] == {"gatilho": "LEAD_QUENTE"}
    assert linha["ip"] is None
    assert linha["correlation_id"] is None


async def test_a_origem_vai_para_ip_e_correlation_id(session: AsyncSession) -> None:
    evento_id = await registrar_evento(
        session,
        ator=Ator(AtorTipo.USUARIO, "usuario-1"),
        acao=Acao.ACESSO_NEGADO,
        entidade=Entidade.ROTA,
        entidade_id="/api/v1/corretores",
        origem=Origem(ip="10.0.0.1", correlation_id="req-1"),
    )
    await session.commit()

    linha = (
        await session.execute(
            select(
                EventoAuditoria.ip, EventoAuditoria.correlation_id, EventoAuditoria.ator_id
            ).where(EventoAuditoria.id == evento_id)
        )
    ).one()
    assert str(linha.ip) == "10.0.0.1"
    assert linha.correlation_id == "req-1"
    assert linha.ator_id == "usuario-1"


async def test_update_e_recusado(session: AsyncSession) -> None:
    await _um_evento(session)

    with pytest.raises(DBAPIError, match="imutavel"):
        await session.execute(text("UPDATE eventos_auditoria SET campo = 'resumo'"))
    await session.rollback()


async def test_delete_de_linha_recente_e_recusado_mesmo_por_sql_cru(session: AsyncSession) -> None:
    await _um_evento(session)

    with pytest.raises(DBAPIError, match="12 meses"):
        await session.execute(text("DELETE FROM eventos_auditoria"))
    await session.rollback()

    assert await _total(session) == 1


async def test_criado_em_antedatado_e_sobrescrito_pelo_relogio_do_banco(
    session: AsyncSession,
) -> None:
    """Sem o trigger de insercao, antedatar e apagar em seguida furaria os 12 meses."""
    await session.execute(
        _INSERIR_CRU,
        {"id": uuid.uuid4(), "ator_tipo": "SISTEMA", "ator_id": None, "acao": "HANDOFF_CRIADO"},
    )
    await session.commit()

    recente = await session.scalar(
        text("SELECT criado_em > clock_timestamp() - interval '1 minute' FROM eventos_auditoria")
    )
    assert recente is True


async def test_acao_fora_do_vocabulario_e_recusada(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="ck_eventos_auditoria_acao"):
        await session.execute(
            _INSERIR_CRU,
            {"id": uuid.uuid4(), "ator_tipo": "SISTEMA", "ator_id": None, "acao": "APAGOU_TUDO"},
        )
    await session.rollback()


async def test_usuario_sem_id_e_recusado_pelo_banco(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="ck_eventos_auditoria_ator_id"):
        await session.execute(
            _INSERIR_CRU,
            {"id": uuid.uuid4(), "ator_tipo": "USUARIO", "ator_id": None, "acao": "ACESSO_NEGADO"},
        )
    await session.rollback()


async def test_detalhes_com_chave_livre_nao_chega_ao_banco(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="motivo_livre"):
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REATIVADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id="x",
            detalhes={"motivo_livre": "lead pediu por telefone"},
        )
    assert await _total(session) == 0

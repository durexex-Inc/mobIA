"""Um teste por evento auditado do dominio. TEC-206, D7 do desenho.

A escrita e explicita (D1), e um caminho novo que a esqueca nao e auditado --
e por isso cada escritor tem o seu teste aqui. O acesso ao resumo e a negativa
estao em `test_rota_de_resumo.py` e `test_autorizacao_por_papel.py`.
"""

import asyncio
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.admin.reativar import _executar
from mobia.domain.auditoria.vocabulario import ATOR_AGENTE, ATOR_SISTEMA
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.optout.models import EVENTO_REATIVACAO, OptoutEvent
from mobia.domain.optout.repositorio import reativar, registrar_optout

CANAL = "whatsapp"
TELEFONE = "5511911112222"
MOTIVO = "lead pediu por telefone ao Paulo"


async def _eventos(session: AsyncSession, acao: str) -> list[dict]:
    resultado = await session.execute(
        text("SELECT * FROM eventos_auditoria WHERE acao = :acao ORDER BY criado_em"),
        {"acao": acao},
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_handoff_criado_grava_um_registro(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=TELEFONE,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    (evento,) = await _eventos(session, "HANDOFF_CRIADO")
    assert evento["ator_tipo"] == "AGENTE"
    assert evento["ator_id"] is None
    assert evento["entidade"] == "handoff"
    assert evento["entidade_id"] == str(registro.id)
    assert evento["detalhes"] == {"gatilho": "LEAD_QUENTE"}
    assert evento["lead_ref"] is not None
    assert evento["ip"] is None
    assert evento["correlation_id"] is None


async def test_acumular_gatilho_num_handoff_aberto_nao_grava(session: AsyncSession) -> None:
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=TELEFONE,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    segundo = await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=TELEFONE,
        gatilho=Gatilho.VENDA_IMOVEL,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert segundo.criado is False
    assert len(await _eventos(session, "HANDOFF_CRIADO")) == 1


async def test_rollback_do_handoff_leva_o_registro_junto(session: AsyncSession) -> None:
    """Nao ha registro de handoff desfeito."""
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=TELEFONE,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.rollback()

    assert await session.scalar(text("SELECT count(*) FROM handoffs")) == 0
    assert await _eventos(session, "HANDOFF_CRIADO") == []


async def test_corrida_de_dois_turnos_grava_um_registro_so(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Review Focus 2: quem arbitra e o `ON CONFLICT`, e so o vencedor e criacao."""

    async def escrever(gatilho: Gatilho) -> None:
        async with session_factory() as propria:
            await registrar_handoff(
                propria,
                channel=CANAL,
                conversation_key=TELEFONE,
                gatilho=gatilho,
                ator=ATOR_AGENTE,
            )
            await propria.commit()

    await asyncio.gather(escrever(Gatilho.LEAD_QUENTE), escrever(Gatilho.VENDA_IMOVEL))

    assert len(await _eventos(session, "HANDOFF_CRIADO")) == 1


async def test_optout_grava_o_seu(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=TELEFONE, message_id=uuid.uuid4()
    )

    (evento,) = await _eventos(session, "OPTOUT_REGISTRADO")
    linha = (await session.execute(select(OptoutEvent))).scalar_one()
    assert evento["ator_tipo"] == ATOR_SISTEMA.tipo.value
    assert evento["entidade"] == "optout_event"
    assert evento["entidade_id"] == str(linha.id)
    assert evento["ip"] is None


async def test_reativacao_grava_o_seu_e_nao_copia_o_motivo(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """D5: o motivo digitado fica em `optout_events`, e o registro aponta para ele."""
    await reativar(
        session_factory, channel=CANAL, conversation_key=TELEFONE, autor="Paulo M.", motivo=MOTIVO
    )

    (evento,) = await _eventos(session, "OPTOUT_REATIVADO")
    linha = (
        await session.execute(select(OptoutEvent).where(OptoutEvent.evento == EVENTO_REATIVACAO))
    ).scalar_one()
    assert evento["entidade_id"] == str(linha.id)
    assert evento["ator_tipo"] == "SISTEMA"
    assert all(MOTIVO not in str(valor) and "Paulo" not in str(valor) for valor in evento.values())


async def test_a_reativacao_pela_cli_tambem_grava(session: AsyncSession) -> None:
    await _executar(channel=CANAL, key=TELEFONE, autor="Paulo M.", motivo=MOTIVO)

    assert len(await _eventos(session, "OPTOUT_REATIVADO")) == 1

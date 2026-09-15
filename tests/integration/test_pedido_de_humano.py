"""A transferencia para humano ao pedido do lead, ponta a ponta.

TEC-143.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.repositorio import registrar_handoff, tem_handoff_de_humano_aberto
from mobia.domain.handoff.vocabulario import Gatilho


async def test_sem_handoff_a_conversa_nao_esta_esperando_humano(session: AsyncSession) -> None:
    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110001"
        )
        is False
    )


async def test_handoff_de_pedido_de_humano_deixa_a_conversa_esperando(
    session: AsyncSession,
) -> None:
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110002",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110002"
        )
        is True
    )


async def test_handoff_de_outro_gatilho_nao_cala_o_agente(session: AsyncSession) -> None:
    """Um lead que esquentou tem handoff aberto e continua sendo atendido.

    Calar por qualquer handoff aberto tiraria o agente de toda conversa que
    virou QUENTE -- que e o oposto do que o gatilho QUENTE significa. So o
    pedido explicito do lead cala.
    """
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110003",
        gatilho=Gatilho.LEAD_QUENTE,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110003"
        )
        is False
    )


async def test_pedido_que_chega_depois_do_quente_tambem_cala(session: AsyncSession) -> None:
    """O gatilho pode estar em `gatilhos_adicionais`, e nao na coluna `gatilho`.

    Um lead que esquentou ja tem handoff aberto; quando ele pede uma pessoa,
    `registrar_handoff` ACUMULA o gatilho na linha existente em vez de criar
    outra. Olhar so a coluna `gatilho` perderia exatamente este caso, que e o
    mais comum: quem ja conversou o bastante para esquentar e quem mais se
    cansa de robo.
    """
    for gatilho in (Gatilho.LEAD_QUENTE, Gatilho.PEDIDO_DE_HUMANO):
        await registrar_handoff(
            session,
            channel="whatsapp",
            conversation_key="5511911110005",
            gatilho=gatilho,
        )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(
            session, channel="whatsapp", conversation_key="5511911110005"
        )
        is True
    )


async def test_a_consulta_e_por_conversa_e_por_canal(session: AsyncSession) -> None:
    await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911110004",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()

    assert (
        await tem_handoff_de_humano_aberto(session, channel="web", conversation_key="5511911110004")
        is False
    )

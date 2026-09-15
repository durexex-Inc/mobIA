"""A transferencia para humano ao pedido do lead, ponta a ponta.

TEC-143.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agente import turno as turno_mod
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff, tem_handoff_de_humano_aberto
from mobia.domain.handoff.vocabulario import Gatilho, Prioridade
from mobia.domain.humano.deteccao import (
    TEXTO_DO_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO,
)
from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import esta_em_optout


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


async def _handoff_da_conversa(session: AsyncSession, *, channel: str, conversation_key: str):
    return (
        await session.execute(
            select(Handoff).where(
                Handoff.channel == channel, Handoff.conversation_key == conversation_key
            )
        )
    ).scalar_one_or_none()


async def test_pedido_de_humano_cria_handoff_alta_e_nao_chama_o_modelo(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )

    handoff = await _handoff_da_conversa(
        session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE
    )
    assert handoff is not None
    assert handoff.gatilho == Gatilho.PEDIDO_DE_HUMANO.value
    assert handoff.prioridade == Prioridade.ALTA.value

    assert classificador.chamadas == 0
    assert resultado == "pedido_de_humano"
    assert outbound.entregues != [], "o aviso tem de sair"
    # Fecha a simetria com o teste de fora do horario: aquele confere o texto
    # da outra metade do if/else. Sem esta assercao uma inversao das duas
    # branches passaria despercebida -- "algo foi entregue" e verdade nos dois
    # casos.
    assert TEXTO_DO_PEDIDO_DE_HUMANO in outbound.entregues[-1]
    assert (
        TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
            inicio=get_settings().atendimento_horario_inicio,
            fim=get_settings().atendimento_horario_fim,
        )
        not in outbound.entregues[-1]
    )


async def test_optout_na_mesma_mensagem_vence_o_pedido_de_humano(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Fix de revisao (Critical) em `turno.py`. A guarda de atendimento humano

    -- e, pelo mesmo criterio, o bloco novo do pedido de humano -- so pode
    rodar `if not pedido_de_optout:`. Sem essa ordem, uma mensagem que e AO
    MESMO TEMPO opt-out e pedido de humano registraria o handoff e nunca
    gravaria a saida -- o mesmo defeito de LGPD que o comentario de
    `turno.py:749-758` (guarda de atendimento humano incondicional) descreve
    para o corretor que ja tinha assumido.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="pare de me mandar mensagens, quero falar com uma pessoa",
    )

    assert await esta_em_optout(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE), (
        "o opt-out tem de vencer e ficar gravado"
    )
    assert resultado == "opt_out"
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is None
    ), "o opt-out venceu -- nenhum handoff de pedido de humano nasce desta mensagem"


async def test_depois_do_pedido_o_agente_cala_e_a_mensagem_e_registrada(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    primeiro_resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )
    assert primeiro_resultado == "pedido_de_humano"

    classificador = classificador_fake()
    outbound = outbound_fake()

    segundo_resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="ainda estou esperando",
    )

    assert segundo_resultado == "atendimento_humano"
    assert outbound.entregues == [], "o agente cala -- nenhum envio novo"
    assert classificador.chamadas == 0

    total_do_lead = (
        await session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.role == MessageRole.LEAD, Message.direction == MessageDirection.INBOUND)
        )
    ).scalar_one()
    assert total_do_lead == 2, (
        "as duas falas do lead continuam registradas -- o silencio nao apaga nada"
    )


async def test_fora_do_horario_o_texto_muda_e_o_handoff_e_criado_do_mesmo_jeito(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    monkeypatch: object,
) -> None:
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE

    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: False)

    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="quero falar com uma pessoa",
    )

    assert resultado == "pedido_de_humano"
    assert (
        await _handoff_da_conversa(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE)
        is not None
    )

    settings = get_settings()
    texto_esperado = TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
    )
    assert outbound.entregues != []
    assert texto_esperado in outbound.entregues[-1]
    assert str(settings.atendimento_horario_inicio) in outbound.entregues[-1]
    assert str(settings.atendimento_horario_fim) in outbound.entregues[-1]

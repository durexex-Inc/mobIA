from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO


async def test_recusa_da_moderacao_em_conversa_nova_se_identifica(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O lead cuja PRIMEIRA mensagem caiu na moderacao tambem recebe texto
    nosso. Identificar so na resposta normal deixaria justamente ele sem saber
    de quem e o texto -- o dano que a RN-04.1 existe para evitar.
    """
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_entrada=True),
    )

    assert TEXTO_DA_IDENTIFICACAO in outbound.entregues[-1]


async def test_resposta_normal_em_conversa_nova_se_identifica(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert TEXTO_DA_IDENTIFICACAO in outbound.entregues[-1]


async def test_segundo_turno_da_mesma_conversa_nao_repete(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """Identificar em todo turno viraria assinatura de rodape, e o lead para de
    ler. A regra e uma vez por conversa.
    """
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )
    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert TEXTO_DA_IDENTIFICACAO in outbound.entregues[0]
    assert TEXTO_DA_IDENTIFICACAO not in outbound.entregues[-1]


async def test_conversa_nova_depois_de_31_dias_se_identifica_de_novo(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """A quarta regra da card: conversa nova do mesmo lead se identifica de
    novo. Sem este teste, uma implementacao que identificasse UMA VEZ POR LEAD
    para sempre passaria em todos os outros -- e um lead que volta meses
    depois nunca mais saberia com quem fala.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from mobia.domain.messages.models import Message

    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    # Envelhece tudo que ja existe: o proximo turno passa a ver 31 dias de
    # silencio atras de si.
    antigo = datetime.now(UTC) - timedelta(days=31)
    for linha in (await session.scalars(select(Message))).all():
        linha.created_at = antigo
    await session.commit()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    identificadas = [e for e in outbound.entregues if TEXTO_DA_IDENTIFICACAO in e]
    assert len(identificadas) == 2


async def test_o_recorder_grava_o_texto_com_a_identificacao(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    rodar_turno,
) -> None:
    """O que foi gravado tem de ser o que foi entregue.

    Se a identificacao entrasse DEPOIS da gravacao, a transcricao do lead --
    que e o que o corretor le no handoff e o que alimenta o resumo -- diria uma
    coisa e o WhatsApp do lead outra. A divergencia so apareceria numa
    auditoria manual.
    """
    from sqlalchemy import select

    from mobia.domain.messages.enums import MessageRole
    from mobia.domain.messages.models import Message
    from mobia.infra.crypto import aad_de, decrypt

    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    falada = (
        await session.scalars(select(Message).where(Message.role == MessageRole.AGENTE))
    ).all()[-1]
    gravado = decrypt(falada.text_body, aad_de(falada.id, "text_body"))
    assert TEXTO_DA_IDENTIFICACAO in gravado

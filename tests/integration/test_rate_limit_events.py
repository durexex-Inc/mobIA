"""A tabela append-only de bloqueio por rate limit (TEC-205)."""

import uuid

from sqlalchemy import select

from mobia.domain.limites.models import (
    CHANNEL_HTTP,
    ESCOPO_IP,
    ESCOPO_NUMERO,
    RateLimitEvent,
)


async def test_grava_o_bloqueio_por_numero(session) -> None:
    session.add(
        RateLimitEvent(
            id=uuid.uuid4(),
            escopo=ESCOPO_NUMERO,
            chave="5511999999999",
            channel="whatsapp",
            volume=21,
            limite=20,
            message_id=uuid.uuid4(),
        )
    )
    await session.commit()

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.escopo == ESCOPO_NUMERO
    assert linha.volume == 21
    assert linha.limite == 20
    # `created_at` e do relogio do Postgres, como em `optout_events`: a ORDEM
    # dos eventos e o estado, e relogios de processo divergem.
    assert linha.created_at is not None


async def test_o_escopo_ip_nao_tem_message_id(session) -> None:
    """No escopo IP nao ha mensagem: o bloqueio acontece antes da rota."""
    session.add(
        RateLimitEvent(
            id=uuid.uuid4(),
            escopo=ESCOPO_IP,
            chave="203.0.113.7",
            channel=CHANNEL_HTTP,
            volume=101,
            limite=100,
            message_id=None,
        )
    )
    await session.commit()

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.message_id is None
    assert linha.channel == CHANNEL_HTTP


async def test_o_limite_vigente_fica_na_linha(session) -> None:
    """Sem o limite ao lado, "volume 21" nao diz se houve abuso -- e o limite
    e configuravel, entao o de hoje nao explica o evento de ontem.
    """
    session.add(
        RateLimitEvent(
            id=uuid.uuid4(),
            escopo=ESCOPO_NUMERO,
            chave="5511888888888",
            channel="whatsapp",
            volume=6,
            limite=5,
            message_id=uuid.uuid4(),
        )
    )
    await session.commit()
    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.volume > linha.limite

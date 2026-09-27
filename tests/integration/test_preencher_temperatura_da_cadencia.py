"""TEC-385: o preenchimento dos leads que a 0068 nao soube calcular."""

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.schemas import FormaPagamento, Intencao, TipoImovel, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import preencher_temperaturas_da_cadencia
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"


async def test_so_o_lead_sem_temperatura_da_cadencia_e_recalculado(
    session: AsyncSession, banco_limpo: None
) -> None:
    # O lead com no-show de antes da 0068: temperatura gravada, penalidade,
    # e a coluna nova nula.
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key="5511900000001",
            intencao=Intencao.COMPRA.value,
            tipo_imovel=TipoImovel.APARTAMENTO.value,
            faixa_preco_max_centavos=60_000_000,
            regiao="zona sul",
            urgencia=Urgencia.IMEDIATA.value,
            forma_pagamento=FormaPagamento.A_VISTA.value,
            penalidade_pontos=15,
            temperatura="FRIO",
            temperatura_da_cadencia=None,
        )
    )
    # O que a 0068 ja preencheu, e o que nunca teve temperatura: os dois ficam.
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key="5511900000002",
            temperatura="MORNO",
            temperatura_da_cadencia="MORNO",
        )
    )
    session.add(LeadQualification(channel=CANAL, conversation_key="5511900000003"))
    await session.commit()

    assert await preencher_temperaturas_da_cadencia(get_sessionmaker()) == 1

    recalculado = await session.get(
        LeadQualification, (CANAL, "5511900000001"), populate_existing=True
    )
    intocado = await session.get(
        LeadQualification, (CANAL, "5511900000003"), populate_existing=True
    )
    assert recalculado is not None and recalculado.temperatura_da_cadencia is not None
    assert intocado is not None and intocado.temperatura_da_cadencia is None
    # E de novo nao ha o que fazer.
    assert await preencher_temperaturas_da_cadencia(get_sessionmaker()) == 0

"""Criterios de aceite do TEC-134 como testes executaveis.

O quarto cenario do ticket -- suite de 50 conversas com 90% de acuracia no CI
-- nao esta aqui: ele e a TEC-210, palavra por palavra, e a TEC-210 e bloqueada
pela TEC-161. Ver a secao de escopo do spec.
"""

from decimal import Decimal

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.infra.db import get_sessionmaker


async def test_reconhecer_intencao_de_investimento(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario: Reconhecer intencao de investimento."""
    classificador = classificador_fake(Intencao.INVESTIMENTO, confianca=Decimal("0.88"))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.INVESTIMENTO
    assert gravada.confianca >= Decimal("0.8")


async def test_reconhecer_intencao_de_aluguel(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario: Reconhecer intencao de aluguel."""
    classificador = classificador_fake(Intencao.ALUGUEL, confianca=Decimal("0.85"))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.ALUGUEL
    assert gravada.confianca >= Decimal("0.8")


async def test_intencao_e_confianca_ficam_registradas_na_conversa(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario: Intencao e confianca ficam registradas na conversa."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.91"))
    saida = outbound_fake()

    await rodar_turno(session, classificador, saida, resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA
    assert gravada.confianca == Decimal("0.91")
    assert saida.entregues, "o turno tambem respondeu ao lead"

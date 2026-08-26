"""Criterios de aceite do TEC-134 como testes executaveis.

O que estes testes provam e **persistencia**: a classificacao de um turno real
-- montagem de contexto, gravacao, entrega, tudo sobre SQL de verdade --
chega a `conversation_intent` com intencao e confianca intactas.

O que eles **nao** provam e reconhecimento. O classificador e sempre um duble e
a intencao e argumento de construtor, entao a mensagem semeada nao influencia o
resultado. Isso nao e descuido: a tabela de testes do spec prometia
"quero investir em imoveis para renda" -> INVESTIMENTO enquanto o mesmo spec
exigia que nenhum teste toque a rede e que o classificador seja duble. As duas
regras nao cabem juntas -- e o spec foi corrigido nesta branch. Reconhecimento
de intencao passa a ser verificado pela TEC-210, com as 50 conversas anotadas.

O quarto cenario do ticket -- suite de 50 conversas com 90% de acuracia no CI
-- tambem e a TEC-210, palavra por palavra, e a TEC-210 e bloqueada pela
TEC-161. Ver a secao de escopo do spec.
"""

from decimal import Decimal

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.infra.db import get_sessionmaker


async def test_intencao_de_investimento_persiste_no_turno(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Criterio 1: a classificacao INVESTIMENTO sobrevive ao turno inteiro.

    Persistencia, nao reconhecimento -- a intencao entra por construtor do
    duble. Ver a docstring do modulo.
    """
    classificador = classificador_fake(Intencao.INVESTIMENTO, confianca=Decimal("0.88"))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.INVESTIMENTO
    assert gravada.confianca >= Decimal("0.8")


async def test_intencao_de_aluguel_persiste_no_turno(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Criterio 2: a classificacao ALUGUEL sobrevive ao turno inteiro.

    Persistencia, nao reconhecimento -- ver a docstring do modulo.
    """
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
    """Criterio 3: intencao e confianca ficam registradas na conversa.

    Este e o unico dos tres cujo nome sempre disse o que ele prova: a
    confianca chega com o valor exato e o turno tambem respondeu ao lead.
    """
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.91"))
    saida = outbound_fake()

    await rodar_turno(session, classificador, saida, resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA
    assert gravada.confianca == Decimal("0.91")
    assert saida.entregues, "o turno tambem respondeu ao lead"

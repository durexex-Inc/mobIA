"""Criterios de aceite do TEC-135 como testes executaveis.

O que estes testes provam e **o ramo**: abaixo do limiar o turno chama o
desambiguador e entrega o texto dele; no limiar exato, nao; uma vez por
episodio; e uma classificacao confiante reabre o direito de perguntar.

O que eles **nao** provam e a qualidade da pergunta. O classificador e sempre
um duble e o texto e argumento de construtor, entao nada aqui garante que o
modelo real escreva uma pergunta aberta em vez de um menu numerado. Isso e
medicao de qualidade de saida, e e a TEC-210 que a tem no escopo -- ver a
secao de lacunas do spec.

Dois cenarios do ticket falam em "seguir pela trilha de aluguel" e "conduzir
pela qualificacao generica". Trilha nenhuma existe antes da TEC-137, e a
escolha da pergunta de qualificacao e a TEC-145. O observavel aqui e a
intencao persistida e a volta da resposta normal.
"""

from decimal import Decimal

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"
VAGA = Decimal("0.45")


async def test_mensagem_vaga_gera_pergunta_aberta(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 1: confianca 0,45 vira pergunta, e nenhuma intencao e assumida."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=VAGA)
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    # `in` e nao `==` desde a TEC-139: em conversa nova a entrega carrega o
    # prefixo de identificacao antes da pergunta.
    assert len(outbound.entregues) == 1
    assert classificador.pergunta in outbound.entregues[-1]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.INDEFINIDA, "nenhuma das duas intencoes foi assumida"


async def test_confianca_exatamente_no_limite_nao_desambigua(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 2: 0,6 segue com a intencao classificada, sem perguntar."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.60"))
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 0
    # `in` e nao `==` desde a TEC-139: em conversa nova a entrega carrega o
    # prefixo de identificacao antes da resposta normal.
    assert len(outbound.entregues) == 1
    assert "Ola! Em qual regiao voce procura?" in outbound.entregues[-1]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.COMPRA


async def test_resposta_a_desambiguacao_reclassifica_a_intencao(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 3: o lead respondeu "e para alugar mesmo".

    O turno seguinte classifica com confianca alta, a intencao efetiva passa a
    ALUGUEL e o agente volta a responder em vez de perguntar. "Seguir pela
    trilha de aluguel" e a TEC-137.
    """
    outbound = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, confianca=VAGA),
        outbound,
        resumidor_fake(),
        contador_fake(),
    )

    depois = classificador_fake(Intencao.ALUGUEL, confianca=Decimal("0.88"))
    await rodar_turno(session, depois, outbound, resumidor_fake(), contador_fake())

    assert depois.desambiguacoes == 0

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.ALUGUEL


async def test_ambiguidade_persistente_nao_vira_insistencia(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario 4: a resposta continuou ambigua, e o agente nao repete a pergunta."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=VAGA)
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())
    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1
    assert outbound.entregues[1] != classificador.pergunta

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.efetiva is Intencao.INDEFINIDA

"""Criterio de aceite da TEC-159: p95 da busca abaixo de 400 ms com 10.000
imoveis (RN-09.5, RNF-03).

Marcado `perf` e fora do run padrao: a medicao depende da maquina, e o
`CLAUDE.md` registra que medir p95 em runner compartilhado seria flake e nao
sinal. Rode com `python -m pytest -m perf`.

**A fronteira medida e o BANCO** (D4 do desenho). A ida ao provedor de
embedding fica fora, com embedador local: e chamada de rede que nenhum
REINDEX melhora, e a unica alavanca desta card e o indice. O preco disso
esta na lacuna L1 -- o orcamento real em producao e este numero MAIS o
provedor.

## Evidencia medida

(preencher na Task 3, com data e maquina)
"""

import random
import statistics
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import Operacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca
from mobia.domain.texto import dobrar
from mobia.infra.db import get_sessionmaker

IMOVEIS = 10_000
BUSCAS = 100
P95_MAXIMO_MS = 400.0
DIMENSOES = 1536
LOTE = 500

# Semente fixa: duas execucoes na mesma maquina tem de ser comparaveis, senao
# o numero no docstring nao forma serie.
SEMENTE = 20260909

# Vetores CLUSTERIZADOS e nao uniformes (D2). Em 1536 dimensoes, vetores
# uniformes sofrem concentracao de medida -- ficam todos aproximadamente
# equidistantes --, e o IVFFlat particiona por proximidade. Sobre dados sem
# aglomeracao o benchmark mediria varredura, nao o indice que a card precisa
# calibrar.
CENTROIDES = 50
RUIDO = 0.15

BAIRROS = [f"Bairro {n:02d}" for n in range(20)]


class _EmbedadorDoBenchmark:
    """Devolve o vetor que o laco acabou de escolher, sem tocar a rede.

    Classe e nao funcao aninhada de proposito: um `async def` dentro do laco
    fechando sobre `vetor` e exatamente o B023 do flake8-bugbear ("function
    definition does not bind loop variable"), e o ruff deste repo tem `B` no
    select -- reprovaria o gate.

    E nao e o `EmbedadorFake` do conftest porque aquele devolve
    `[valor] * 1536`: todas as dimensoes iguais, um vetor degenerado na
    diagonal. Contra dados clusterizados ele cairia sempre na mesma regiao e
    falsearia a selecao de particao do IVFFlat, que e justamente o que este
    benchmark existe para medir.
    """

    def __init__(self) -> None:
        self.vetor: list[float] = []

    async def __call__(self, textos: list[str]) -> list[list[float]]:
        return [self.vetor for _ in textos]


def _centroides(rng: random.Random) -> list[list[float]]:
    return [[rng.uniform(-1.0, 1.0) for _ in range(DIMENSOES)] for _ in range(CENTROIDES)]


def _vetor_perto_de(centro: list[float], rng: random.Random) -> list[float]:
    return [c + rng.gauss(0.0, RUIDO) for c in centro]


def _linha(indice: int, centro: list[float], rng: random.Random) -> dict[str, object]:
    bairro = BAIRROS[indice % len(BAIRROS)]
    return {
        "id": uuid.uuid4(),
        "codigo": f"BENCH-{indice:05d}",
        "titulo": f"Imovel de benchmark {indice}",
        "descricao": "Linha sintetica do benchmark da TEC-159.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        # Faixa larga o bastante para o filtro de preco ter o que descartar.
        "preco_venda": 20_000_000 + (indice % 800) * 100_000,
        "condominio": 50_000,
        "bairro": bairro,
        # Escrita a mao porque a coluna e derivada e nao GENERATED -- ver o
        # comentario dela em catalogo/models.py.
        "bairro_busca": dobrar(bairro),
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 40 + (indice % 120),
        "quartos": 1 + (indice % 4),
        "suites": indice % 3,
        "banheiros": 1 + (indice % 3),
        "vagas": indice % 3,
        "caracteristicas": ["churrasqueira", "piscina"],
        "fotos": [f"https://exemplo.com/bench-{indice}.jpg"],
        "status": "DISPONIVEL",
        "embedding": _vetor_perto_de(centro, rng),
    }


async def _semear(rng: random.Random) -> None:
    """Insere IMOVEIS linhas em lotes, e reconstroi o indice depois.

    Em lotes porque 10.000 vetores de 1536 floats de uma vez sao ~600 MB de
    objetos Python. E com REINDEX no fim porque IVFFlat treina na CONSTRUCAO
    do indice: depois do TRUNCATE do `banco_limpo`, o indice existente foi
    construido sobre zero linhas, e inserir 10.000 nao o treina.
    """
    centros = _centroides(rng)
    async with get_sessionmaker()() as sessao:
        for comeco in range(0, IMOVEIS, LOTE):
            lote = [
                _linha(indice, centros[indice % CENTROIDES], rng)
                for indice in range(comeco, min(comeco + LOTE, IMOVEIS))
            ]
            await sessao.execute(Imovel.__table__.insert(), lote)
            await sessao.commit()

        await sessao.execute(text("REINDEX INDEX ix_imoveis_embedding"))
        await sessao.commit()


def _consulta(indice: int, centros: list[list[float]], rng: random.Random):
    """Um filtro DIFERENTE por iteracao, e o vetor de consulta perto de um
    centroide.

    Cem buscas iguais mediriam o cache quente do Postgres e o mesmo caminho de
    particao -- p95 otimista que nao descreve atendimento nenhum.
    """
    filtro = FiltroDeBusca(
        operacao=Operacao.VENDA,
        preco_max_centavos=30_000_000 + (indice % 20) * 5_000_000,
        quartos_min=1 + (indice % 4),
        regioes=(BAIRROS[indice % len(BAIRROS)],),
    )
    vetor = _vetor_perto_de(centros[indice % CENTROIDES], rng)
    return filtro, vetor


@pytest.mark.perf
async def test_p95_da_busca_fica_abaixo_de_400ms(session: Any) -> None:
    rng = random.Random(SEMENTE)
    await _semear(rng)

    centros = _centroides(random.Random(SEMENTE))
    latencias_ms: list[float] = []
    embedador = _EmbedadorDoBenchmark()

    async with get_sessionmaker()() as sessao:
        for indice in range(BUSCAS):
            filtro, embedador.vetor = _consulta(indice, centros, rng)

            inicio = time.perf_counter()
            resultado = await buscar(
                sessao,
                filtro,
                consulta_texto="apartamento com varanda perto do metro",
                embedador=embedador,
            )
            latencias_ms.append((time.perf_counter() - inicio) * 1000)

            assert resultado.consulta_vetorizada is True

    quantis = statistics.quantiles(latencias_ms, n=100)
    p95 = quantis[94]

    print(
        f"\nimoveis={IMOVEIS} buscas={BUSCAS} "
        f"p50={statistics.median(latencias_ms):.1f}ms "
        f"p95={p95:.1f}ms p99={quantis[98]:.1f}ms"
    )
    # So o p95 e criterio de aceite da RN-09.5. p50 e p99 ficam no print como
    # observacao, sem virar orcamento que a historia nunca definiu -- mesmo
    # criterio do `test_ingest_latency.py`.
    assert p95 < P95_MAXIMO_MS, f"p95 de {p95:.1f}ms estourou o orcamento de {P95_MAXIMO_MS}ms"

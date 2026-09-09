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

**Dois grupos, nunca uma media.** `regioes=(bairro,)` e o formato do
Gherkin, mas `regioes=()` -- "sem filtro de regiao" em `schemas.py` -- e
formato legal e comum: e o lead que da faixa de preco mas nao bairro, e e
exatamente quem paga o custo pleno de 10.000 vetores. Com bairro,
`ix_imoveis_bairro_busca` reduz o candidato a uma fatia (22 a 500 linhas
dos 10.000); sem bairro, a consulta varre o catalogo inteiro. Sao caminhos
de custo diferentes -- uma media dos dois esconderia qual dos dois estoura
o orcamento.

## Evidencia medida

- 2026-09-09, maquina de desenvolvimento Windows rodando Postgres via docker
  compose: p50=68.9ms p95=144.9ms p99=255.8ms com 10.000 imoveis e
  `lists = 1`. Passa o teto de 400 ms, com cerca de 2.8x de margem.
  **Nota da revisao, mesmo dia:** esta execucao filtrava por bairro em toda
  consulta -- o candidato nunca passava de 500 linhas, nunca os 10.000. Nao
  media o caminho de custo pleno que a `0017` supunha medido. Ver a linha
  seguinte.
- 2026-09-09, mesma maquina, apos a correcao (dois grupos de 50 buscas cada,
  `ANALYZE imoveis` apos o `REINDEX`): grupo "com bairro"
  p50=66.3ms p95=155.0ms p99=209.6ms (candidatos entre 22 e 500); grupo
  "sem bairro" p50=88.4ms p95=232.9ms p99=318.4ms (candidatos entre 437 e
  10.000, confirmando que este grupo varre o catalogo inteiro). Os dois
  PASSAM o teto de 400 ms -- "com bairro" com cerca de 2.6x de margem,
  "sem bairro" (o pior caso, o caminho de custo pleno) com cerca de 1.7x.
"""

import random
import statistics
import time
import uuid
from dataclasses import dataclass
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
BUSCAS_POR_GRUPO = 50
P95_MAXIMO_MS = 400.0
DIMENSOES = 1536
LOTE = 500

# Semente fixa: duas execucoes na mesma maquina tem de ser comparaveis, senao
# o numero no docstring nao forma serie.
SEMENTE = 20260909

# Vetores CLUSTERIZADOS e nao uniformes (D2). Em 1536 dimensoes, vetores
# uniformes sofrem concentracao de medida -- ficam todos aproximadamente
# equidistantes. Mantidos mesmo sabendo que, com `lists = 1`, nao ha
# particao nenhuma para o agrupamento influenciar -- uma lista so contem
# tudo, e a consulta varre a lista inteira nao importa a geometria dos
# vetores, porque o `ORDER BY` computado de `buscar()` fecha o caminho ANN de
# qualquer jeito (ver a nota de 2026-09-09 em
# `alembic/versions/0017_indexacao_vetorial.py`, que nomeia os dois bloqueios
# estruturais). Ficam por comparabilidade futura: se `lists` um dia subir, a
# mesma base clusterizada serve para medir de novo sem reescrever o gerador.
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
    diagonal, fora da nuvem dos centroides sinteticos. Isto NAO e para
    preservar selecao de particao do IVFFlat -- com `lists = 1` nao ha
    particao nenhuma para selecionar, ver o comentario de `CENTROIDES` acima
    -- e sim para que o vetor de consulta continue plausivel dentro da
    geometria que o benchmark constroi.
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
        # Modulo 3, e nao 4: 4 divide 20 (o modulo do bairro), entao um
        # modulo 4 aqui fazia toda linha de um mesmo bairro cair no MESMO
        # valor de quartos (20 % 4 == 0). Um filtro `quartos_min` sobre um
        # bairro cujo unico valor fosse menor zerava o grupo "com bairro"
        # inteiro -- a mesma classe de correlacao acidental que a revisao
        # achou em `_consulta`, so que do lado da linha em vez do lado do
        # filtro. Modulo 3 e coprimo com 20: cada bairro passa a ter linha
        # dos tres valores possiveis.
        "quartos": 1 + (indice % 3),
        "suites": indice % 3,
        "banheiros": 1 + (indice % 3),
        "vagas": indice % 3,
        "caracteristicas": ["churrasqueira", "piscina"],
        "fotos": [f"https://exemplo.com/bench-{indice}.jpg"],
        "status": "DISPONIVEL",
        "embedding": _vetor_perto_de(centro, rng),
    }


async def _semear(rng: random.Random) -> None:
    """Insere IMOVEIS linhas em lotes, e reconstroi indice e estatisticas depois.

    Em lotes porque 10.000 vetores de 1536 floats de uma vez sao ~600 MB de
    objetos Python. Com REINDEX no fim porque IVFFlat treina na CONSTRUCAO
    do indice: depois do TRUNCATE do `banco_limpo`, o indice existente foi
    construido sobre zero linhas, e inserir 10.000 nao o treina. Com ANALYZE
    logo depois pelo mesmo motivo do outro lado do planner: o TRUNCATE zera
    `pg_class.reltuples`, e sem ANALYZE a primeira consulta do benchmark
    correria sobre estatisticas de tabela vazia -- um plano que producao,
    com a tabela cheia e analisada, nunca usa.
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
        await sessao.execute(text("ANALYZE imoveis"))
        await sessao.commit()


def _consulta(
    indice: int, centros: list[list[float]], rng: random.Random, *, com_bairro: bool
) -> tuple[FiltroDeBusca, list[float]]:
    """Um filtro DIFERENTE por iteracao, com bairro so quando `com_bairro`.

    Moduli par a par coprimos -- bairro em 20, preco em 17, quartos em 3 --
    para que os seis filtros combinados (100 consultas no total, entre os
    dois grupos) nao repitam: o periodo combinado e 1020, acima das 100
    consultas que o benchmark faz. Antes desta correcao, bairro e preco
    repetiam a cada 20 iteracoes -- 100 consultas eram 20 filtros distintos
    vezes 5 -- e `quartos_min` usava modulo 4: como `20 % 4 == 0`, o
    `quartos_min` de toda consulta contra um bairro coincidia exatamente com
    o (unico) valor de quartos das linhas daquele bairro, e o predicado
    nunca descartava nada.
    """
    filtro = FiltroDeBusca(
        operacao=Operacao.VENDA,
        preco_max_centavos=30_000_000 + (indice % 17) * 5_000_000,
        quartos_min=1 + (indice % 3),
        regioes=(BAIRROS[indice % len(BAIRROS)],) if com_bairro else (),
    )
    vetor = _vetor_perto_de(centros[indice % CENTROIDES], rng)
    return filtro, vetor


@dataclass(frozen=True, slots=True)
class _MetricasDoGrupo:
    """p50/p95/p99 e o piso/teto de `total_candidatos` de um grupo de buscas."""

    nome: str
    p50: float
    p95: float
    p99: float
    candidatos_min: int
    candidatos_max: int


async def _medir_grupo(
    sessao: Any,
    nome: str,
    *,
    com_bairro: bool,
    indice_inicial: int,
    centros: list[list[float]],
    rng: random.Random,
    embedador: _EmbedadorDoBenchmark,
) -> _MetricasDoGrupo:
    latencias_ms: list[float] = []
    candidatos: list[int] = []

    for offset in range(BUSCAS_POR_GRUPO):
        indice = indice_inicial + offset
        filtro, embedador.vetor = _consulta(indice, centros, rng, com_bairro=com_bairro)

        inicio = time.perf_counter()
        resultado = await buscar(
            sessao,
            filtro,
            consulta_texto="apartamento com varanda perto do metro",
            embedador=embedador,
        )
        latencias_ms.append((time.perf_counter() - inicio) * 1000)

        assert resultado.consulta_vetorizada is True
        # Sem isto, 50 resultados vazios passariam: o criterio de aceite e
        # sobre uma busca que ACHA candidato e mede o custo disso, nao sobre
        # uma que so devolve rapido porque nao achou nada.
        assert resultado.total_candidatos > 0, (
            f"grupo {nome}, indice {indice}: total_candidatos veio zero"
        )
        candidatos.append(resultado.total_candidatos)

    quantis = statistics.quantiles(latencias_ms, n=100)
    return _MetricasDoGrupo(
        nome=nome,
        p50=statistics.median(latencias_ms),
        p95=quantis[94],
        p99=quantis[98],
        candidatos_min=min(candidatos),
        candidatos_max=max(candidatos),
    )


@pytest.mark.perf
async def test_p95_da_busca_fica_abaixo_de_400ms(session: Any) -> None:
    """`session` nao aparece no corpo do teste, e nao e sobra: e o parametro
    que traz a cadeia de fixture `banco_limpo` -> `migrar_banco`, e e
    `banco_limpo` quem trunca `imoveis` antes deste teste rodar (D3 do
    desenho). Um tidy-up futuro que apagasse este parametro por parecer
    nao-usado faria o benchmark parar de truncar -- a segunda execucao
    mediria 20.000 linhas e a terceira 30.000, em silencio, sem nenhum erro
    para avisar.
    """
    rng = random.Random(SEMENTE)
    await _semear(rng)

    centros = _centroides(random.Random(SEMENTE))
    embedador = _EmbedadorDoBenchmark()

    async with get_sessionmaker()() as sessao:
        metrica_com_bairro = await _medir_grupo(
            sessao,
            "com bairro",
            com_bairro=True,
            indice_inicial=0,
            centros=centros,
            rng=rng,
            embedador=embedador,
        )
        metrica_sem_bairro = await _medir_grupo(
            sessao,
            "sem bairro",
            com_bairro=False,
            indice_inicial=BUSCAS_POR_GRUPO,
            centros=centros,
            rng=rng,
            embedador=embedador,
        )

    for metrica in (metrica_com_bairro, metrica_sem_bairro):
        print(
            f"\ngrupo={metrica.nome} imoveis={IMOVEIS} buscas={BUSCAS_POR_GRUPO} "
            f"p50={metrica.p50:.1f}ms p95={metrica.p95:.1f}ms p99={metrica.p99:.1f}ms "
            f"candidatos_min={metrica.candidatos_min} candidatos_max={metrica.candidatos_max}"
        )

    # So o p95 e criterio de aceite da RN-09.5, e por grupo: os dois grupos
    # sao caminhos de custo diferentes (docstring do modulo), e uma media
    # esconderia qual dos dois estoura o orcamento.
    assert metrica_com_bairro.p95 < P95_MAXIMO_MS, (
        f"grupo com bairro: p95 de {metrica_com_bairro.p95:.1f}ms estourou "
        f"o orcamento de {P95_MAXIMO_MS}ms"
    )
    assert metrica_sem_bairro.p95 < P95_MAXIMO_MS, (
        f"grupo sem bairro: p95 de {metrica_sem_bairro.p95:.1f}ms estourou "
        f"o orcamento de {P95_MAXIMO_MS}ms"
    )

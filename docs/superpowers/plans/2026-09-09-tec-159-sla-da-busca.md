# TEC-159 — SLA de 400 ms na busca: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Descobrir, com número medido, se a busca cumpre 400 ms no p95 com 10.000 imóveis — e corrigir o índice se, e somente se, o número exigir.

**Architecture:** Um benchmark em `tests/perf/`, marcado `perf` e fora do run padrão, que gera 10.000 imóveis com vetores clusterizados, reconstrói o índice IVFFlat, e mede 100 buscas diferentes de semente fixa. A evidência vira docstring versionado. O terceiro cenário do Gherkin já é verdade desde a TEC-158 e ganha só um teste de verificação.

**Tech Stack:** Python 3.13, SQLAlchemy async, pgvector (IVFFlat), pytest, ruff, mypy. Postgres e Redis por `docker compose`.

**Spec:** [docs/superpowers/specs/2026-09-09-tec-159-sla-da-busca-design.md](../specs/2026-09-09-tec-159-sla-da-busca-design.md)

## Global Constraints

- **Os três gates estáticos, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals`
  `./.venv/Scripts/python.exe -m mypy`
  O formatador é gate separado do linter.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Comentar o porquê, nunca o quê.** Comentário desatualizado é defeito.
- ruff line-length 100; lint select `["E", "F", "I", "UP", "B"]`.
- **Basenames de teste únicos entre `tests/unit/`, `tests/integration/` e `tests/perf/`.** Colisão aborta a coleta da suíte inteira e não aparece em execução isolada.
- **O benchmark NÃO entra no run padrão.** `pyproject.toml` tem `addopts = "-m 'not perf'"`. Não mexa nisso.
- **Nunca use `run_in_background` nem redirecionamento para pytest.** Rode em primeiro plano com timeout generoso. O pytest deste repo não imprime nada até terminar; silêncio é normal.
- **Baseline da suíte padrão:** 1371 passed, 0 failed (23 min). A Task 1 acrescenta testes ao run padrão; a Task 2 não.
- **Mensagem de commit:** `tipo(TEC-159): o que passou a ser verdade`, português sem acento no assunto.

---

### Task 1: A degradação sem vetor, verificada

**Files:**
- Create: `tests/integration/test_busca_sem_vetor.py`

**Interfaces:**
- Consumes: `buscar(session, filtro, consulta_texto=None, limite=10, embedador=None) -> ResultadoDaBusca` de `mobia.domain.catalogo.busca`; `FiltroDeBusca(operacao, preco_min_centavos=None, preco_max_centavos=None, tipo=None, quartos_min=None, vagas_min=None, regioes=())` e `Operacao.VENDA` de `mobia.domain.catalogo`.
- Produces: nada que outra tarefa consuma.

**Contexto:** o terceiro cenário do Gherkin (*"Sem índice vetorial o sistema degrada em vez de falhar"*) **já é verdade** desde a TEC-158 — `busca.py` devolve `consulta_vetorizada=False` e o docstring de `_vetor_da_consulta` diz *"o vetor da consulta, ou None -- e None nunca e erro"*. Esta tarefa escreve o teste que afirma isso, e é teste normal e não `perf`, porque é asserção de comportamento e não medição.

- [ ] **Step 1: Escreva os testes**

Crie `tests/integration/test_busca_sem_vetor.py`:

```python
"""A busca degrada para filtro SQL quando nao ha vetor. TEC-159, RNF-32.

O comportamento e da TEC-158; esta card so o fixa em teste, porque e um dos
tres cenarios do Gherkin da TEC-159. Basename distinto de tudo em
`tests/unit/` e `tests/perf/`.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import Operacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 50000000,
        "bairro": "Vila Mariana",
        "bairro_busca": "vila mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_sem_embedador_a_busca_devolve_por_filtro_sql(session: Any) -> None:
    """RNF-32: o atendimento continua funcionando sem indice vetorial.

    `embedador=None` e o caminho que a TEC-158 declarou nao ser erro. O que
    esta assercao protege e o desfecho: resultado devolvido, nao excecao.
    """
    identificador = await _imovel(session, "AP-001")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=None,
    )

    assert resultado.consulta_vetorizada is False
    assert [c.imovel_id for c in resultado.candidatos] == [identificador]


async def test_imovel_sem_embedding_ainda_e_candidato(session: Any) -> None:
    """Imovel indexado e imovel nao indexado convivem no mesmo resultado.

    A degradacao da RNF-32 nao e so "a consulta sem vetor funciona" -- e
    tambem "a linha sem vetor nao some da busca". Sem esta assercao, um
    INNER JOIN acidental no futuro passaria despercebido: o outro teste
    continuaria verde porque nenhum imovel dele tem embedding.
    """
    sem_vetor = await _imovel(session, "AP-001")
    com_vetor = await _imovel(session, "AP-002", embedding=[0.1] * 1536)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    encontrados = {c.imovel_id for c in resultado.candidatos}
    assert encontrados == {sem_vetor, com_vetor}


async def test_a_busca_sem_texto_nem_vetor_ainda_filtra(session: Any) -> None:
    """Sem `consulta_texto` nao ha o que vetorizar, e o filtro duro vale."""
    barato = await _imovel(session, "AP-001", preco_venda=30000000)
    await _imovel(session, "AP-002", preco_venda=90000000)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=50000000),
    )

    assert [c.imovel_id for c in resultado.candidatos] == [barato]
```

- [ ] **Step 2: Rode para ver o estado real**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_sem_vetor.py -v --tb=short
```

Esperado: **os três passam de primeira.** Isto não é TDD com RED — o comportamento já existe e esta tarefa o fixa. Se algum reprovar, você encontrou um defeito real na TEC-158: **pare e reporte**, não conserte o teste para acomodar.

Se aparecer `ConnectionResetError [WinError 64]` na negociação SSL, é o flake documentado no `CLAUDE.md` (~5% dos connects, em rajada). Retente o mesmo comando.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/integration/test_busca_sem_vetor.py
git commit -m "test(TEC-159): a degradacao sem vetor deixa de depender de ninguem lembrar dela"
```

---

### Task 2: O benchmark no volume alvo

**Files:**
- Create: `tests/perf/test_busca_latency.py`

**Interfaces:**
- Consumes: `buscar`, `FiltroDeBusca`, `Operacao`, `Imovel`, `dobrar` de `mobia.domain.texto`, `get_sessionmaker` de `mobia.infra.db`.
- Produces: o número de p95 que a Task 3 registra.

**Quatro armadilhas desta tarefa, todas verificadas no código:**

1. **`banco_limpo` é autouse e trunca `imoveis` antes de cada teste** (`tests/conftest.py:464`), e `tests/perf/` não tem conftest próprio. A base tem de nascer dentro do teste. Não crie um conftest para desligar isso — a D3 do desenho recusa esse caminho.
2. **IVFFlat treina na construção do índice, não na inserção.** Depois do TRUNCATE, `ix_imoveis_embedding` está treinado sobre zero linhas. `REINDEX` depois da carga é obrigatório (D5), sempre — não só quando `lists` mudar.
3. **Não gere os 10.000 vetores de uma vez.** 10.000 × 1536 floats Python são ~600 MB de objetos. Gere e insira em lotes de 500; cada lote são ~30 MB que o interpretador libera em seguida.
4. **Não use o `EmbedadorFake` do conftest para a consulta.** Ele devolve `[valor] * 1536` — todas as dimensões iguais, um vetor degenerado na diagonal. Contra dados clusterizados ele cairia sempre na mesma região e falsearia a seleção de partição do IVFFlat. Este arquivo tem o seu próprio, que amostra da mesma distribuição dos dados.

- [ ] **Step 1: Escreva o benchmark**

Crie `tests/perf/test_busca_latency.py`:

```python
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
```

- [ ] **Step 2: Rode o benchmark, em primeiro plano**

```bash
./.venv/Scripts/python.exe -m pytest tests/perf/test_busca_latency.py -m perf -v -s --tb=short
```

`-m perf` é obrigatório: sem ele o `addopts` do `pyproject.toml` deseleciona o teste e você verá `1 deselected` em vez de uma medição. `-s` é o que deixa o print aparecer.

Espere alguns minutos: são 10.000 inserções mais o REINDEX antes de a primeira medição acontecer. Use timeout de pelo menos 600000 ms.

**Anote o número, passando ou reprovando.** É o produto desta tarefa.

- [ ] **Step 3: Confirme que o benchmark NÃO entra no run padrão**

```bash
./.venv/Scripts/python.exe -m pytest tests/perf/test_busca_latency.py --collect-only -q
```

Esperado: `1 deselected` (ou equivalente), zero testes selecionados. Se ele for coletado para execução, o marcador não está aplicado e a suíte padrão passaria a levar minutos a mais.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/perf/test_busca_latency.py
git commit -m "test(TEC-159): o benchmark mede a busca no volume que a 0017 disse que expira"
```

---

### Task 3: A evidência, e a correção se o número exigir

**Files:**
- Modify: `tests/perf/test_busca_latency.py` (o docstring)
- Modify: `alembic/versions/0017_indexacao_vetorial.py` (o comentário) **— apenas no caminho A**
- Create: `alembic/versions/00NN_lists_do_ivfflat.py` **— apenas no caminho B**

**Interfaces:**
- Consumes: o p95 medido na Task 2.
- Produces: nada que outra tarefa consuma.

**Esta tarefa tem dois caminhos, e o número da Task 2 escolhe qual.** Não faça os dois.

- [ ] **Step 1: Registre a evidência no docstring — os dois caminhos fazem isto**

Substitua a seção `## Evidencia medida` do docstring pelo medido. Formato, no molde do histórico que `test_config.py` mantém para o teto do orçamento:

```
## Evidencia medida

- 2026-09-09, <cpu/maquina em uma linha>: p50=<x>ms p95=<y>ms p99=<z>ms com
  10.000 imoveis e `lists = 1`. <"Passa" ou "Estoura"> o teto de 400 ms.
```

Uma linha por medição, acrescentando e nunca substituindo: é o que faz a série existir para quem vier depois.

- [ ] **Step 2A: SE O P95 PASSOU — troque a estimativa da `0017` pelo número**

A migration `0017` diz hoje: *"Esta frase vence por volta de 10.000 imoveis, e o numero esta escrito aqui para que ninguem a leia como atemporal."* Esse número era estimativa. Acrescente o medido logo abaixo, sem apagar o argumento original:

```
**Medido pela TEC-159 em 2026-09-09:** com 10.000 imoveis e `lists = 1`, o
p95 da busca ficou em <y> ms contra o teto de 400 ms da RNF-03. A estimativa
acima estava <certa/errada> na direcao: a lista unica <ainda resolve / ja nao
resolve> neste volume. O proximo volume a checar e <o que voce concluir>, e
`tests/perf/test_busca_latency.py` e o comando que responde.
```

Escreva o que o número diz, não o que seria conveniente. Se o p95 passou com folga grande, diga que passou com folga grande.

- [ ] **Step 3A: Gates e commit (caminho A)**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/perf/test_busca_latency.py alembic/versions/0017_indexacao_vetorial.py
git commit -m "docs(TEC-159): a estimativa da 0017 vira numero medido"
```

- [ ] **Step 2B: SE O P95 ESTOUROU — suba `lists` com REINDEX**

Descubra o número da última migration (`ls alembic/versions/`) e crie a seguinte. `lists` vai para `IMOVEIS / 1000` arredondado, seguindo a orientação do pgvector — com 10.000, isso é 10.

```python
"""o `lists` do IVFFlat sobe para o volume alvo

TEC-159. A `0017` escolheu `lists = 1` com um argumento datado e nomeou esta
card como herdeira. O argumento expirou por medicao e nao por calendario: o
benchmark de `tests/perf/test_busca_latency.py` mediu p95 de <y> ms com
10.000 imoveis, contra o teto de 400 ms da RNF-03.

**O preco desta mudanca recai sobre o catalogo de HOJE.** Com 520 imoveis
reais, `lists = 10` poe ~52 vetores por particao e a busca varre uma delas --
recall menor do que a lista unica dava. A troca e deliberada: latencia num
volume que chega contra recall num volume que ja passou.

`REINDEX` e obrigatorio e nao cosmetico: IVFFlat treina na construcao do
indice, entao mudar `lists` sem reconstruir deixa o indice antigo em uso.

Revision ID: 00NN
Revises: 00MM
"""

from alembic import op

revision = "00NN"
down_revision = "00MM"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_imoveis_embedding")
    op.execute(
        "CREATE INDEX ix_imoveis_embedding ON imoveis "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_imoveis_embedding")
    op.execute(
        "CREATE INDEX ix_imoveis_embedding ON imoveis "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)"
    )
```

- [ ] **Step 3B: Rode o benchmark de novo e registre as duas medições**

```bash
./.venv/Scripts/python.exe -m pytest tests/perf/test_busca_latency.py -m perf -v -s --tb=short
```

O docstring passa a ter **duas linhas**: a de `lists = 1` e a de `lists = 10`. É a comparação antes-e-depois que justifica a migration, e sem as duas a mudança de índice fica sem evidência própria.

Se o p95 continuar acima de 400 ms mesmo com `lists = 10`, **pare e reporte**. A alternativa é HNSW, que o desenho colocou fora de escopo, e a decisão é de quem lê o número.

- [ ] **Step 4B: Rode a migration e a suíte de migrations**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py tests/integration/test_migracao_vetorial.py -v --tb=short
```

Se o `alembic upgrade head` reprovar com `ConnectionResetError [WinError 64]`, espere e retente: o `CLAUDE.md` documenta que o banco demora mais que o healthcheck diz.

- [ ] **Step 5B: Gates e commit (caminho B)**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/perf/test_busca_latency.py alembic/versions/
git commit -m "fix(TEC-159): o lists do ivfflat sobe porque o p95 estourou"
```

---

### Task 4: A suíte padrão, contra o baseline

**Files:** nenhum. Esta tarefa produz evidência.

- [ ] **Step 1: A suíte inteira**

```bash
git rev-parse --short HEAD
./.venv/Scripts/python.exe -u -m pytest --tb=short
```

São ~23 minutos com a máquina ociosa, mais sob carga. Saída vazia por dez minutos é normal.

**Baseline: 1371 passed, 0 failed, 0 errors.** Esta card acrescenta os 3 testes da Task 1 ao run padrão e nenhum da Task 2 — espere **1374 passed**. Se o total subir mais que isso, o marcador `perf` não está sendo respeitado.

Falha nova fora da família WinError 64 (`ConnectionResetError`, `OSError`, `redis.exceptions.ConnectionError`) é regressão. Rode o arquivo isolado antes de concluir qualquer coisa.

- [ ] **Step 2: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 3: Comentário no Jira e PR**

Comentário na [TEC-159](https://eduardodurieuxlopes.atlassian.net/browse/TEC-159) com o p95 medido, qual caminho da Task 3 foi tomado, e a lacuna L1 (a latência do provedor de embedding não entra no número).

```bash
git push -u origin feat/tec-159-sla-da-busca
gh pr create --base main --title "test(TEC-159): o SLA da busca deixa de ser estimativa" --body "<resumo com o p95 medido>"
```

---

## Auto-revisão deste plano

**Cobertura do desenho:** D1 → Task 3, com os dois caminhos escritos. D2 → Task 2 (`_centroides`, `_vetor_perto_de`). D3 → Task 2 (`_semear` dentro do teste). D4 → Task 2 (embedador local). D5 → Task 2 (`REINDEX` em `_semear`). D6 → Task 3 Step 1. D7 → Task 1.

**Lacunas do desenho:** L1 aparece no docstring do benchmark e no comentário do Jira. L2, L3 e L4 não geram tarefa — são consequências aceitas.

**Cenários do Gherkin:** cenário 1 (SLA no volume alvo) → Task 2. Cenário 2 (benchmark registrado como evidência) → Task 3 Step 1. Cenário 3 (degradação) → Task 1.

**Duas correções feitas aqui, ambas verificadas por execução e não por leitura:**

- O desenho dizia usar o `EmbedadorFake` do conftest. Não serve — ele devolve `[valor] * 1536`, vetor degenerado na diagonal, que contra dados clusterizados cairia sempre na mesma região e falsearia a seleção de partição. A Task 2 tem embedador próprio.
- A primeira versão deste plano definia esse embedador como `async def` **dentro do laço**, fechando sobre `vetor`. Rodei o ruff sobre esse padrão: `B023 Function definition does not bind loop variable`. O gate teria reprovado o código que eu mesmo mandei escrever. Virou classe chamável definida fora do laço, e essa versão passa `ruff check` e `ruff format --check`.

# TEC-160 — Relaxamento de critério: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a busca do catálogo devolve zero resultados, executar **um** relaxamento automático (faixa de preço em até 10% e bairros adjacentes), avisar o lead em que dimensão o critério foi ampliado, e dar desfecho quando nem ampliando aparece algo.

**Architecture:** `buscar()` continua sendo uma passagem única de SQL. Um módulo novo, `domain/catalogo/relaxamento.py`, chama `buscar()` até duas vezes: a segunda com um filtro alargado por `alargar()`, que amplia o `WHERE` **sem mover a âncora da ordenação**. O estado do relaxamento é um tri-estado no domínio e vira booleano só nas bordas (`tool_result` e `POST` da seção 6.3). O aviso ao lead é mensagem determinística nossa, com kind próprio.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x async (Core), Alembic, Postgres 16 + pgvector, pytest-asyncio, structlog, mypy, ruff.

**Spec:** [`docs/superpowers/specs/2026-09-11-tec-160-relaxamento-de-criterio-design.md`](../specs/2026-09-11-tec-160-relaxamento-de-criterio-design.md) (commit `7ca3550`). Leia o desenho antes de começar: cada task abaixo cita a decisão (D1–D14) que a justifica, e o desenho é onde mora o **porquê**.

**Card:** [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) — História, Should, prioridade High, épico TEC-155. Os quatro cenários do Gherkin da card estão mapeados nas Tasks 6, 7 e 9.

**Branch:** `feat/tec-160-relaxamento-de-criterio` (já criada, já contém o desenho).

---

## Global Constraints

Estas valem para **toda** task. Não são opcionais e não estão repetidas dentro de cada uma.

- **Os três gates estáticos, com o escopo exato do CI.** Rode os três antes de cada commit. Passar no linter não é evidência sobre o formatador — são gates separados:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Convenção do repo, não checada por linter nenhum. Prosa em `docs/`: com acento.
- **Todo texto que sai para o lead é ASCII sem acento** (`Condominio`, `m2`, separador `-`). É a disciplina de `apresentacao.py` e de `TEXTO_DA_BUSCA_INCONCLUSIVA`.
- **Comentário não mente.** Este repo comenta o *porquê*, não o *quê*, e trata comentário desatualizado como defeito. Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-160): o que passou a ser verdade`. Termine com:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```
- **Basenames de teste são únicos entre `tests/unit/` e `tests/integration/`.** Colisão aborta a coleta da suíte inteira e **não** aparece em execução isolada. Os nomes desta card já estão escolhidos: `test_relaxamento_alargar.py` (unit) e `test_relaxamento_busca.py` (integração).
- **Não acrescente `bairros_adjacentes` a `TABELAS` em `tests/conftest.py`.** É dado de referência que nasce na migration; incluí-la paga um `TRUNCATE ... CASCADE` por teste numa suíte de 1200+ e ainda apaga a adjacência que os testes precisam ter (D7).
- **`ConnectionResetError [WinError 64]` na negociação SSL é flake conhecido desta máquina** (~5% dos connects, em rajada). Uma falha isolada com esse traceback **não autoriza conclusão nenhuma**. Rode o arquivo isolado antes de culpar sua mudança; se precisar de evidência, rode a versão ANTIGA o mesmo número de vezes.
- **A suíte inteira leva ~22 minutos** em máquina ociosa e muito mais sob carga. Rode só os arquivos da task durante o desenvolvimento; a suíte completa é a Task 11.

---

## Estrutura de arquivos

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/catalogo/relaxamento.py` | A política da RN-09.3: decidir se relaxa, alargar o filtro, repetir a busca |
| `alembic/versions/0021_bairros_adjacentes.py` | Schema e carga da tabela de adjacência |
| `tests/unit/test_relaxamento_alargar.py` | `alargar`, o tri-estado e a escolha da variante do aviso |
| `tests/integration/test_relaxamento_busca.py` | Os dois passes contra banco, e os cenários do Gherkin |

**Modificados:**

| Arquivo | O quê |
|---|---|
| `src/mobia/domain/catalogo/enums.py` | `EstadoDoRelaxamento` |
| `src/mobia/domain/catalogo/models.py` | Modelo `BairroAdjacente` |
| `src/mobia/domain/catalogo/schemas.py` | `FiltroDeBusca.relaxado`, `ResultadoDaBusca.relaxamento` |
| `src/mobia/domain/catalogo/busca.py` | `MARGEM_DO_RELAXAMENTO_PCT`, o `WHERE` com folga, o parâmetro `vetor` |
| `src/mobia/domain/agente/ferramenta_de_busca.py` | Chama `buscar_com_relaxamento`, serializa os dois booleanos |
| `src/mobia/domain/agente/classificador.py` | `SISTEMA_DO_AGENTE` ganha a frase; `_relaxamento_de` extrai o estado do `tool_result` |
| `src/mobia/domain/agente/schemas.py` | Dois campos no resultado do agente |
| `src/mobia/domain/agente/turno.py` | Os textos, o kind, o envio do aviso e o desfecho |
| `src/mobia/api/routes/imoveis.py` | Chama `buscar_com_relaxamento`, devolve `relaxamentoAplicado` |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | As duas emendas e as duas linhas do índice |

---

## Task 1: O tri-estado e o campo do filtro

Formas puras. Nenhuma consulta muda ainda.

**Files:**
- Modify: `src/mobia/domain/catalogo/enums.py`
- Modify: `src/mobia/domain/catalogo/schemas.py`
- Test: `tests/unit/test_relaxamento_alargar.py` (arquivo novo)

**Interfaces:**
- Consumes: nada.
- Produces: `EstadoDoRelaxamento` (`NAO_HOUVE` / `APLICADO` / `SEM_RESULTADO`); `FiltroDeBusca.relaxado: bool = False`; `ResultadoDaBusca.relaxamento: EstadoDoRelaxamento = EstadoDoRelaxamento.NAO_HOUVE`; `ResultadoDaBusca.relaxou_preco: bool = False`; `ResultadoDaBusca.relaxou_bairro: bool = False`.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_relaxamento_alargar.py`:

```python
"""As formas puras do relaxamento da RN-09.3.

TEC-160. Basename distinto de tudo em `tests/integration/`.
"""

from mobia.domain.catalogo.enums import EstadoDoRelaxamento, Operacao
from mobia.domain.catalogo.schemas import FiltroDeBusca, ResultadoDaBusca


def test_o_filtro_nasce_nao_relaxado() -> None:
    """D2: o campo existe e o default e o passe duro."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA)

    assert filtro.relaxado is False


def test_o_resultado_nasce_sem_relaxamento() -> None:
    """D6: `buscar` nunca afirma relaxamento -- ela e um passe."""
    resultado = ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)

    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE


def test_os_tres_estados_sao_distintos() -> None:
    """Um booleano colapsaria os dois ultimos, e a regra 4 da card precisa
    dos tres separados: "nao relaxei" e "relaxei e nao achei" pedem mensagens
    diferentes ao lead."""
    assert len(set(EstadoDoRelaxamento)) == 3


def test_o_resultado_diz_quais_dimensoes_alargou() -> None:
    """D11. O aviso precisa saber EM QUE ampliou, e o estado nao carrega isso:
    `APLICADO` vale tanto para "so preco" quanto para "preco e bairro"."""
    resultado = ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)

    assert resultado.relaxou_preco is False
    assert resultado.relaxou_bairro is False
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_relaxamento_alargar.py -v`
Expected: FAIL com `ImportError: cannot import name 'EstadoDoRelaxamento'`.

- [ ] **Step 3: Acrescente o enum**

No fim de `src/mobia/domain/catalogo/enums.py`:

```python
class EstadoDoRelaxamento(StrEnum):
    """O que aconteceu com o relaxamento da RN-09.3 nesta busca. TEC-160, D6.

    **Tres estados e nao um booleano, e a regra 4 da card e quem exige.** Ela
    manda que, sem resultado mesmo depois de relaxar, o agente informe e
    ofereca o corretor. O turno precisa entao separar "nao relaxei" de
    "relaxei e nao achei" -- as duas mensagens ao lead sao diferentes, e um
    `relaxamento_aplicado: false` colapsa as duas num valor so.

    Com o enum, o estado impossivel ("nao tentei, mas apliquei") deixa de ser
    representavel. As bordas (tool_result e o POST da secao 6.3) continuam
    expondo booleano, derivado num lugar so.
    """

    NAO_HOUVE = "NAO_HOUVE"
    APLICADO = "APLICADO"
    SEM_RESULTADO = "SEM_RESULTADO"
```

- [ ] **Step 4: Acrescente os dois campos**

Em `src/mobia/domain/catalogo/schemas.py`, importe o enum novo junto dos outros (`from mobia.domain.catalogo.enums import (...)`), e acrescente a `FiltroDeBusca`, **depois** de `regioes`:

```python
    # TEC-160, D2. Este filtro e o segundo passe da RN-09.3: o WHERE de preco
    # ganha a folga de `MARGEM_DO_RELAXAMENTO_PCT`, e a ancora da ordenacao
    # NAO se move -- `_aderencia` continua recebendo `preco_max_centavos` cru.
    #
    # **A divergencia mora aqui e nao num parametro de `buscar()`** porque um
    # `ancora_de_preco: int | None = None` teria default indistinguivel do
    # caso real: `None` ja significa "o lead nao deu teto" (aderencia
    # constante 1), e o default precisaria de sentinela. Com o campo no
    # filtro, os dois fatos ficam visiveis na mesma funcao.
    relaxado: bool = False
```

E a `ResultadoDaBusca`, depois de `consulta_vetorizada`:

```python
    # TEC-160, D6. `buscar` devolve SEMPRE NAO_HOUVE -- ela e um passe e nao
    # sabe se e o primeiro ou o segundo. Quem afirma outra coisa e
    # `buscar_com_relaxamento`, por `dataclasses.replace`.
    relaxamento: EstadoDoRelaxamento = EstadoDoRelaxamento.NAO_HOUVE

    # TEC-160, D11. QUAIS dimensoes o passe relaxado alargou -- que o estado
    # nao carrega, porque `APLICADO` vale tanto para "so preco" quanto para
    # "preco e bairro". O aviso ao lead tem tres variantes e escolhe por estes
    # dois: uma constante fixa dizendo sempre "valor e bairros vizinhos"
    # mentiria para todo lead que nao deu regiao.
    relaxou_preco: bool = False
    relaxou_bairro: bool = False
```

- [ ] **Step 5: Rode para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_relaxamento_alargar.py -v`
Expected: 3 passed.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/catalogo/enums.py src/mobia/domain/catalogo/schemas.py tests/unit/test_relaxamento_alargar.py
git commit -m "feat(TEC-160): o filtro sabe dizer que e o passe relaxado, e o resultado tem tres estados"
```

---

## Task 2: `buscar()` honra `relaxado` no `WHERE` sem mover a âncora

**Esta é a task que a TEC-158 encomendou por escrito**, e o teste do passo 1 é a dívida que ela deixou nomeada.

**Files:**
- Modify: `src/mobia/domain/catalogo/busca.py`
- Test: `tests/integration/test_relaxamento_busca.py` (arquivo novo)

**Interfaces:**
- Consumes: `FiltroDeBusca.relaxado` (Task 1).
- Produces: `MARGEM_DO_RELAXAMENTO_PCT = 10` em `busca.py`; `buscar()` com o mesmo nome e a mesma assinatura de hoje, mas honrando `filtro.relaxado`.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_relaxamento_busca.py`. O helper `_imovel` é copiado de `test_busca_hibrida.py` **de propósito** — o plano não pede import cruzado entre arquivos de teste, e o molde já é replicado assim entre `test_busca_hibrida.py` e `test_indexacao_do_catalogo.py`.

```python
"""O relaxamento da RN-09.3 contra o banco.

TEC-160. Os quatro cenarios do Gherkin da card, mais a divida que a TEC-158
deixou nomeada: o clamp em 0 da aderencia e o decaimento para 0,9, que so sao
alcancaveis quando o filtro deixa de ser duro.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca
from mobia.domain.catalogo.enums import Operacao
from mobia.domain.texto import dobrar

TETO = 40000000  # R$ 400.000,00 em centavos -- o numero do cenario 1 da card


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `test_busca_hibrida.py`.
    """
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Trindade",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 35000000,
        "bairro": "Trindade",
        "cidade": "Florianopolis",
        "uf": "SC",
        "zona": "CENTRO",
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
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_o_filtro_relaxado_admite_dez_por_cento_acima_do_teto(session: Any) -> None:
    """D3. O `WHERE` cede; e o numero do cenario 1 da card (400 -> 440 mil)."""
    acima = await _imovel(session, "AP-201", preco_venda=44000000)

    duro = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO))
    relaxado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, relaxado=True),
    )

    assert duro.candidatos == ()
    assert [candidato.imovel_id for candidato in relaxado.candidatos] == [acima]


async def test_a_ancora_da_ordenacao_nao_se_move_com_o_where(session: Any) -> None:
    """D2, e a divida que o plano da TEC-158 deixou para esta card.

    A emenda E-01 da RN-09.6 promete que "10% acima do teto sai com 0,9". Isso
    so vale se `_aderencia` continuar ancorada no teto ORIGINAL. Se a ancora
    viajasse junto com o `WHERE`, este imovel sairia com 1,0 -- e a ordenacao
    passaria a favorecer o mais caro do conjunto AMPLIADO, que e a direcao em
    que um erro de calibragem vira upsell.

    Sem vetor de consulta a similaridade vale 0 para todos, entao o score e
    `0,4 * aderencia` -- e 0,4 * 0,9 = 0,36.
    """
    await _imovel(session, "AP-202", preco_venda=44000000)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, relaxado=True),
    )

    assert resultado.candidatos[0].score == 0.36


async def test_o_piso_tambem_cede_no_passe_relaxado(session: Any) -> None:
    """D3: "faixa de preco em ate 10%" e sobre o intervalo, nao so o teto."""
    abaixo = await _imovel(session, "AP-203", preco_venda=19000000)

    duro = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000)
    )
    relaxado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000, relaxado=True),
    )

    assert duro.candidatos == ()
    assert [candidato.imovel_id for candidato in relaxado.candidatos] == [abaixo]


async def test_relaxado_sem_teto_nem_piso_nao_muda_nada(session: Any) -> None:
    """A folga se aplica ao que existe; `None` continua sendo "sem essa ponta"."""
    dentro = await _imovel(session, "AP-204")

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, relaxado=True)
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short`
Expected: os dois primeiros FAIL (nenhum candidato relaxado; o `score` sai `0.4` porque o `WHERE` ignorou `relaxado` e o imóvel de 44 milhões ficou fora — na verdade `IndexError`), o terceiro FAIL, o quarto PASS.

> Se você vir `ConnectionResetError [WinError 64]` na fixture: espere e rode de novo. Ver as Global Constraints.

- [ ] **Step 3: Implemente a folga**

Em `src/mobia/domain/catalogo/busca.py`, acrescente a constante logo depois de `MAX_CANDIDATOS`:

```python
# RN-09.3. A folga que o segundo passe da TEC-160 aplica as duas pontas da
# faixa. Pontos percentuais inteiros de proposito: `* 1.10` em float produz
# tetos que variam no ultimo centavo, e num catalogo de precos densos isso
# vira desempate invisivel numa suite que ja flakeia sob carga.
MARGEM_DO_RELAXAMENTO_PCT = 10
```

E acrescente a função auxiliar, logo acima de `buscar`:

```python
def _com_folga(valor: int, sinal: int) -> int:
    """O limite de preco do passe relaxado. `sinal` e +1 para o teto, -1 para o piso.

    Aritmetica inteira sobre centavos, sem ponto flutuante entrando no SQL.
    """
    return valor * (100 + sinal * MARGEM_DO_RELAXAMENTO_PCT) // 100
```

Dentro de `buscar`, substitua os dois `if` de preço por:

```python
    # TEC-160, D2 e D3. O `WHERE` cede quando este e o passe relaxado; a
    # ANCORA de `_aderencia`, logo abaixo, NAO -- ela continua recebendo
    # `filtro.preco_max_centavos` cru. Os dois fatos estao nesta funcao de
    # proposito: separa-los faria a promessa da emenda E-01 da RN-09.6 ("10%
    # acima do teto sai com 0,9") depender de dois campos coincidirem.
    if filtro.preco_max_centavos is not None:
        teto = filtro.preco_max_centavos
        condicoes.append(preco <= (_com_folga(teto, +1) if filtro.relaxado else teto))
    if filtro.preco_min_centavos is not None:
        piso = filtro.preco_min_centavos
        condicoes.append(preco >= (_com_folga(piso, -1) if filtro.relaxado else piso))
```

- [ ] **Step 4: Rode para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short`
Expected: 4 passed.

- [ ] **Step 5: Confirme que a TEC-158 não quebrou**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_busca_hibrida.py -q --tb=short`
Expected: todos passam. `relaxado` tem default `False`, então nenhum teste de lá muda de comportamento.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/catalogo/busca.py tests/integration/test_relaxamento_busca.py
git commit -m "feat(TEC-160): o passe relaxado alarga a faixa e a ancora da ordenacao fica onde estava"
```

---

## Task 3: `buscar()` aceita um vetor pronto

Sem isto o passe 2 chama o embedador uma segunda vez, para o mesmo texto, em todo turno relaxado — segunda chamada paga e segunda latência (D9).

**Files:**
- Modify: `src/mobia/domain/catalogo/busca.py`
- Test: `tests/integration/test_relaxamento_busca.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `buscar(session, filtro, *, consulta_texto=None, vetor=None, limite=MAX_CANDIDATOS, embedador=None)` — `vetor: list[float] | None`.

- [ ] **Step 1: Escreva o teste que falha**

Acrescente ao fim de `tests/integration/test_relaxamento_busca.py`:

```python
async def test_vetor_pronto_dispensa_o_embedador(session: Any) -> None:
    """D9. Com o vetor na mao, `buscar` nao chama o provedor.

    O embedador injetado aqui EXPLODE se chamado: o teste falha por excecao,
    e nao por asserção sobre contagem, porque o que importa e que a segunda
    chamada nao aconteca -- nao que ela aconteca N vezes.
    """
    await _imovel(session, "AP-205")

    async def embedador_proibido(textos: list[str]) -> list[list[float]]:
        raise AssertionError("o embedador nao devia ser chamado com vetor pronto")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        vetor=[0.0] * 1536,
        embedador=embedador_proibido,
    )

    assert resultado.consulta_vetorizada is True
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py::test_vetor_pronto_dispensa_o_embedador -v --tb=short`
Expected: FAIL com `TypeError: buscar() got an unexpected keyword argument 'vetor'`.

- [ ] **Step 3: Implemente**

Na assinatura de `buscar`, acrescente o parâmetro depois de `consulta_texto`:

```python
async def buscar(
    session: AsyncSession,
    filtro: FiltroDeBusca,
    consulta_texto: str | None = None,
    limite: int = MAX_CANDIDATOS,
    embedador: Embedador | None = None,
    vetor: list[float] | None = None,
) -> ResultadoDaBusca:
```

Acrescente ao docstring dela:

```
    `vetor` presente manda, e `consulta_texto`/`embedador` sao ignorados.
    Ausente (ou `None`), deriva como sempre. Nao precisa de sentinela porque
    "passei None" e "nao passei" querem a mesma coisa: derive se puder. Quem
    usa isto e `buscar_com_relaxamento`, que vetoriza UMA vez e entrega o
    mesmo vetor aos dois passes -- sem isso, todo turno relaxado pagaria duas
    chamadas ao provedor pelo mesmo texto. Ver D9.
```

E troque a linha que calcula o vetor:

```python
    vetor = vetor if vetor is not None else await _vetor_da_consulta(consulta_texto, embedador)
```

- [ ] **Step 4: Rode para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short`
Expected: 5 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/catalogo/busca.py tests/integration/test_relaxamento_busca.py
git commit -m "feat(TEC-160): a busca aceita vetor pronto, e o segundo passe para de pagar embedding duas vezes"
```

---

## Task 4: A tabela de adjacência

**Files:**
- Create: `alembic/versions/0021_bairros_adjacentes.py`
- Modify: `src/mobia/domain/catalogo/models.py`
- Test: `tests/integration/test_relaxamento_busca.py`

**Interfaces:**
- Consumes: nada.
- Produces: tabela `bairros_adjacentes` com colunas `bairro_busca` e `adjacente_busca` (PK composta), e o modelo `BairroAdjacente` em `models.py`.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/integration/test_relaxamento_busca.py`:

```python
from sqlalchemy import select

from mobia.domain.catalogo.models import BairroAdjacente


async def test_a_adjacencia_e_simetrica(session: Any) -> None:
    """D8. As duas direcoes sao gravadas, e a simetria e teste e nao convencao.

    Sem isto, a consulta seria um OR sobre duas colunas -- e o caminho e
    quente, com o p95 de 400 ms da TEC-159 a cumprir.
    """
    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()
    pares = {(linha.bairro_busca, linha.adjacente_busca) for linha in linhas}

    assert pares, "a migration 0021 devia ter semeado a tabela"
    faltando = {(b, a) for (a, b) in pares if (b, a) not in pares}
    assert faltando == set()


async def test_todo_nome_da_adjacencia_existe_no_catalogo_seed(session: Any) -> None:
    """D8. Sem FK -- nao existe entidade de bairro para referenciar --, entao a
    integridade e este teste. Nome errado na tabela falharia em silencio: o
    bairro nunca ampliaria, e ninguem veria erro nenhum.

    Os nomes esperados sao os 12 bairros do catalogo simulado
    (`data/seed/imoveis.csv`), na forma dobrada.
    """
    esperados = {
        dobrar(nome)
        for nome in (
            "Agronomica",
            "Balneario",
            "Campeche",
            "Canasvieiras",
            "Centro",
            "Coqueiros",
            "Estreito",
            "Itacorubi",
            "Jurere",
            "Lagoa da Conceicao",
            "Santo Antonio de Lisboa",
            "Trindade",
        )
    }

    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()
    nomes = {linha.bairro_busca for linha in linhas} | {
        linha.adjacente_busca for linha in linhas
    }

    assert nomes <= esperados


async def test_a_adjacencia_guarda_os_quinze_pares(session: Any) -> None:
    """30 linhas: 15 pares nao ordenados, cada um nas duas direcoes."""
    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()

    assert len(linhas) == 30
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short -k adjacencia`
Expected: FAIL com `ImportError: cannot import name 'BairroAdjacente'`.

- [ ] **Step 3: Acrescente o modelo**

No fim de `src/mobia/domain/catalogo/models.py`:

```python
class BairroAdjacente(Base):
    """A tabela de adjacencia pre-carregada da RN-09.3. TEC-160, D8.

    **Chaveada pelo bairro DOBRADO, nunca pelo nome bonito.** `regioes` chega
    dobrada a `buscar` e `Imovel.bairro_busca` e a coluna que o WHERE compara;
    guardar "Lagoa da Conceicao" com acento obrigaria a dobrar em tempo de
    consulta e faria um acento divergente no seed nunca casar, calado.

    **As duas direcoes sao gravadas.** Adjacencia e simetrica no mundo, mas
    guardar um lado so obrigaria a consulta a ser um OR sobre duas colunas com
    uniao -- e o caminho e quente (p95 de 400 ms, TEC-159). Com as duas, a
    consulta e um IN simples que a PK serve direto. A simetria e afirmada por
    `test_a_adjacencia_e_simetrica`, nao por convencao.

    **Sem FK, porque nao ha entidade de bairro**: `bairro_busca` e coluna
    desnormalizada de `imoveis`. Consequencia: linha que nomeie bairro
    inexistente e inerte, e erro de digitacao do lado esquerdo faz aquele
    bairro nunca ampliar -- as duas falham em silencio. A integridade que o
    schema nao da e `test_todo_nome_da_adjacencia_existe_no_catalogo_seed`.
    """

    __tablename__ = "bairros_adjacentes"

    bairro_busca: Mapped[str] = mapped_column(Text, primary_key=True)
    adjacente_busca: Mapped[str] = mapped_column(Text, primary_key=True)
```

- [ ] **Step 4: Escreva a migration**

Crie `alembic/versions/0021_bairros_adjacentes.py`:

```python
"""a tabela de adjacencia de bairros, com a carga junto

TEC-160, RN-09.3. O relaxamento amplia para "bairros adjacentes (tabela de
adjacencia pre-carregada)", e esta e a tabela.

**A carga vem NESTA revisao, e nao de um seed a parte.** Sao duas
consequencias. A boa: a tabela fica FORA de `TABELAS` no `tests/conftest.py`,
sobrevive ao TRUNCATE que a fixture autouse `banco_limpo` da a cada teste, e
todo teste de integracao a tem sem semear -- numa suite de 1200+ testes,
inclui-la em `TABELAS` custaria mais de mil TRUNCATE a mais, e a contencao de
lock que isso produz e a causa conhecida dos flakes de ConnectionResetError.
A contrapartida: mudar a adjacencia passa a exigir migration nova.

A alternativa de criar vazia e semear depois foi recusada porque um ambiente
recem-migrado teria a tabela vazia, e a RN-09.3 silenciosamente nao ampliaria
bairro nenhum -- falha que nao levanta erro e se parece com "nada e
adjacente". Ver D7 do desenho.

**Os nomes sao gravados dobrados, chamando a mesma `dobrar()` do caminho
normal** -- mesmo padrao da `0019`, e e por isso que `alembic` esta no escopo
do `ruff`. Uma segunda definicao da dobra aqui divergiria da de producao e o
sintoma seria bairro que o lead nomeia e a busca nao amplia.

O criterio dos pares e "contiguos ou ligados por via direta", sobre os 12
bairros de Florianopolis do catalogo simulado. Duas escolhas que alguem vai
questionar: Campeche tem um vizinho so, e Centro-Estreito atravessa a baia
(incluido porque a ponte os liga e um lead de Florianopolis os trata como
vizinhos).

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa

from alembic import op
from mobia.domain.texto import dobrar

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# Os 15 pares nao ordenados. A migration grava as DUAS direcoes de cada um --
# escrever so um lado aqui e derivar o outro mantem esta lista curta e torna
# impossivel gravar um par assimetrico por engano.
PARES = (
    ("Centro", "Agronomica"),
    ("Centro", "Trindade"),
    ("Centro", "Estreito"),
    ("Agronomica", "Trindade"),
    ("Agronomica", "Itacorubi"),
    ("Trindade", "Itacorubi"),
    ("Itacorubi", "Lagoa da Conceicao"),
    ("Itacorubi", "Santo Antonio de Lisboa"),
    ("Lagoa da Conceicao", "Campeche"),
    ("Estreito", "Balneario"),
    ("Estreito", "Coqueiros"),
    ("Balneario", "Coqueiros"),
    ("Canasvieiras", "Jurere"),
    ("Canasvieiras", "Santo Antonio de Lisboa"),
    ("Jurere", "Santo Antonio de Lisboa"),
)


def upgrade() -> None:
    op.create_table(
        "bairros_adjacentes",
        sa.Column("bairro_busca", sa.Text(), nullable=False),
        sa.Column("adjacente_busca", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bairro_busca", "adjacente_busca", name="pk_bairros_adjacentes"
        ),
    )

    linhas = [
        {"bairro_busca": dobrar(esquerda), "adjacente_busca": dobrar(direita)}
        for par in PARES
        for esquerda, direita in (par, (par[1], par[0]))
    ]
    op.bulk_insert(
        sa.table(
            "bairros_adjacentes",
            sa.column("bairro_busca", sa.Text),
            sa.column("adjacente_busca", sa.Text),
        ),
        linhas,
    )


def downgrade() -> None:
    op.drop_table("bairros_adjacentes")
```

- [ ] **Step 5: Aplique a migration e rode**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short
```
Expected: 8 passed.

> Se o `alembic upgrade head` reprovar com `ConnectionResetError [WinError 64]` na negociação SSL, **espere e retente** — o banco demora mais que o healthcheck diz, mesmo com o container marcado `healthy`.

- [ ] **Step 6: Confirme o downgrade**

```bash
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: os dois sem erro. Uma migration que não desce é uma migration que ninguém consegue reverter em produção.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0021_bairros_adjacentes.py src/mobia/domain/catalogo/models.py tests/integration/test_relaxamento_busca.py
git commit -m "feat(TEC-160): os bairros vizinhos de Florianopolis nascem com o schema"
```

---

## Task 5: `alargar()` — o filtro do segundo passe

Função pura. Não toca banco.

**Files:**
- Create: `src/mobia/domain/catalogo/relaxamento.py`
- Test: `tests/unit/test_relaxamento_alargar.py`

**Interfaces:**
- Consumes: `FiltroDeBusca.relaxado` (Task 1).
- Produces: `alargar(filtro: FiltroDeBusca, adjacentes: Sequence[str]) -> FiltroDeBusca`; `e_relaxavel(filtro: FiltroDeBusca) -> bool`.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/unit/test_relaxamento_alargar.py`:

```python
from mobia.domain.catalogo.relaxamento import alargar, e_relaxavel


def test_alargar_marca_o_filtro_e_une_as_regioes() -> None:
    """D8 e a leitura do cenario 4 da card: regioes UNIAO adjacentes.

    "Apenas bairros marcados como adjacentes entram na busca" limita de ONDE
    vem os novos, e nao quem sai. O bairro pedido continua dentro: o passe 1
    nao achou nada nele sob o filtro original, mas com o preco relaxado pode
    haver ali um imovel elegivel, e descarta-lo seria devolver o vizinho e
    esconder o bairro que o lead pediu.
    """
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, regioes=("trindade",))

    alargado = alargar(filtro, ("centro", "agronomica", "itacorubi"))

    assert alargado.relaxado is True
    assert set(alargado.regioes) == {"trindade", "centro", "agronomica", "itacorubi"}


def test_alargar_preserva_o_teto_original() -> None:
    """D2. A folga e do `WHERE`, dentro de `buscar`; o campo nao se mexe aqui.

    Se `alargar` escrevesse `preco_max_centavos = teto * 1,10`, a ancora da
    ordenacao viajaria junto e a promessa da emenda E-01 da RN-09.6 morreria.
    """
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=40000000)

    alargado = alargar(filtro, ())

    assert alargado.preco_max_centavos == 40000000


def test_alargar_sem_adjacentes_mantem_as_regioes() -> None:
    """Bairro sem linha na tabela nao e erro -- e lista vazia (D13)."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, regioes=("campeche",))

    alargado = alargar(filtro, ())

    assert alargado.regioes == ("campeche",)


def test_alargar_nao_duplica_regiao_que_ja_estava() -> None:
    """Duplicata viraria `IN` com o mesmo valor duas vezes: ruido no plano."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, regioes=("centro",))

    alargado = alargar(filtro, ("centro", "trindade"))

    assert sorted(alargado.regioes) == ["centro", "trindade"]


def test_sem_teto_e_sem_regiao_nada_e_relaxavel() -> None:
    """D5. O zero veio de tipo, quartos ou vagas -- nenhum deles a RN-09.3
    relaxa. A segunda consulta seria byte a byte igual a primeira."""
    assert e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, quartos_min=4)) is False


def test_teto_sozinho_ja_torna_relaxavel() -> None:
    assert (
        e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=40000000)) is True
    )


def test_regiao_sozinha_ja_torna_relaxavel() -> None:
    assert e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, regioes=("trindade",))) is True


def test_piso_sozinho_ja_torna_relaxavel() -> None:
    """A faixa cede nas duas pontas (D3), entao o piso tambem e relaxavel."""
    assert (
        e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000)) is True
    )
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_relaxamento_alargar.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.catalogo.relaxamento'`.

- [ ] **Step 3: Crie o módulo com as duas funções puras**

Crie `src/mobia/domain/catalogo/relaxamento.py`:

```python
"""A politica de zero-resultado da RN-09.3: relaxar uma vez, e so uma.

TEC-160. **Modulo proprio, e nao dentro de `busca.py`**, por duas razoes (D1).
A docstring de `busca.py` afirma que "nao precisa de CTE nem de duas viagens ao
banco" e deriva dali a garantia de latencia; uma funcao que faz duas viagens
sob esse texto o torna falso, e este repo trata comentario desatualizado como
defeito. E montar a consulta e decidir a politica de zero-resultado sao
responsabilidades diferentes -- separa-las da a RN-09.3 um nome proprio nos
testes.

A seta aponta num sentido so: este modulo importa `busca`, nunca o contrario.
"""

from collections.abc import Sequence
from dataclasses import replace

from mobia.domain.catalogo.schemas import FiltroDeBusca


def e_relaxavel(filtro: FiltroDeBusca) -> bool:
    """Se ha alguma dimensao que a RN-09.3 saiba relaxar. D5.

    Sem teto, sem piso e sem regiao, o zero veio de tipo, quartos ou vagas --
    e a regra nao relaxa nenhum dos tres. A segunda consulta seria byte a byte
    igual a primeira: paga-se latencia contra o p95 de 400 ms da TEC-159 para
    receber o mesmo zero.

    E tambem a lacuna que o desenho da TEC-262 nomeou -- "relaxaria preco e
    bairro de uma busca que nunca teve chance". Ela fechou o caso do tipo;
    quartos e vagas seguem abertos (L3).
    """
    return (
        filtro.preco_max_centavos is not None
        or filtro.preco_min_centavos is not None
        or bool(filtro.regioes)
    )


def alargar(filtro: FiltroDeBusca, adjacentes: Sequence[str]) -> FiltroDeBusca:
    """O filtro do segundo passe: regioes UNIAO adjacentes, e `relaxado=True`.

    **O teto e o piso NAO se mexem aqui, de proposito.** A folga de preco e do
    `WHERE`, e mora dentro de `buscar` (D2 e D3). Escrever
    `preco_max_centavos = teto * 1,10` neste ponto faria a ancora de
    `_aderencia` viajar junto, e a promessa da emenda E-01 da RN-09.6 -- "10%
    acima do teto sai com 0,9" -- viraria falsa em silencio, com a ordenacao
    passando a favorecer o mais caro do conjunto AMPLIADO.

    **Uniao, e nao substituicao.** O cenario 4 do Gherkin diz "apenas bairros
    marcados como adjacentes a Trindade entram na busca"; ao pe da letra isso
    excluiria a propria Trindade, e esconderia o imovel que o preco relaxado
    acabou de tornar elegivel nela. "Apenas" limita de onde vem os novos, nao
    quem sai -- e o cenario 1 confirma ao dizer "preco ate R$ 440.000 E
    bairros adjacentes", nao "em vez de".

    Ordenado para que o `IN` gerado seja estavel entre execucoes: `set` nao tem
    ordem, e um IN que muda de ordem muda o SQL e invalida plano em cache sem
    motivo. E o mesmo argumento de `zonas_de`, em `busca.py`.
    """
    return replace(
        filtro,
        relaxado=True,
        regioes=tuple(sorted(set(filtro.regioes) | set(adjacentes))),
    )
```

- [ ] **Step 4: Rode para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_relaxamento_alargar.py -v`
Expected: 11 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/catalogo/relaxamento.py tests/unit/test_relaxamento_alargar.py
git commit -m "feat(TEC-160): o filtro do segundo passe sabe se alargar sem levar a ancora junto"
```

---

## Task 6: `buscar_com_relaxamento()` — os dois passes

Aqui os quatro cenários do Gherkin da card ficam travados.

**Files:**
- Modify: `src/mobia/domain/catalogo/relaxamento.py`
- Test: `tests/integration/test_relaxamento_busca.py`

**Interfaces:**
- Consumes: `alargar`, `e_relaxavel` (Task 5); `buscar` com `vetor` (Task 3) e com `relaxado` (Task 2); `BairroAdjacente` (Task 4); `EstadoDoRelaxamento` (Task 1).
- Produces: `adjacentes_de(session, regioes) -> tuple[str, ...]`; `buscar_com_relaxamento(session, filtro, *, consulta_texto=None, limite=MAX_CANDIDATOS, embedador=None) -> ResultadoDaBusca`.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/integration/test_relaxamento_busca.py`:

```python
from mobia.domain.catalogo.enums import EstadoDoRelaxamento
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento


async def test_cenario_1_amplia_faixa_e_bairro_quando_nao_ha_resultado(session: Any) -> None:
    """Cenario 1 do Gherkin, com os numeros da card.

    "Dado o filtro de 3 quartos ate R$ 400.000 na Trindade, sem nenhum
    resultado, quando o relaxamento e aplicado, entao a busca e refeita com
    preco ate R$ 440.000 e bairros adjacentes."
    """
    vizinho = await _imovel(
        session, "AP-301", preco_venda=43000000, bairro="Agronomica", zona="CENTRO"
    )

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            quartos_min=3,
            regioes=("trindade",),
        ),
    )

    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
    assert [candidato.imovel_id for candidato in resultado.candidatos] == [vizinho]
    # As duas dimensoes cederam: o aviso vai ser a variante que diz as duas.
    assert (resultado.relaxou_preco, resultado.relaxou_bairro) == (True, True)


async def test_cenario_2_relaxamento_acontece_uma_unica_vez(session: Any) -> None:
    """Cenario 2: continua sem resultado depois de relaxar, e nao tenta de novo.

    A contagem de chamadas e a afirmacao: DUAS, nunca tres. A RN-09.3 poe "um"
    em negrito, e uma escada custaria ate tres consultas contra o p95 da
    TEC-159.
    """
    await _imovel(session, "AP-302", preco_venda=90000000, bairro="Jurere", zona="NORTE")

    chamadas = 0
    from mobia.domain.catalogo import busca as modulo_de_busca

    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)
        ),
        buscar=contando,
    )

    assert chamadas == 2
    assert resultado.relaxamento is EstadoDoRelaxamento.SEM_RESULTADO
    assert resultado.candidatos == ()


async def test_cenario_3_busca_com_resultado_nao_e_relaxada(session: Any) -> None:
    """Cenario 3: quatro imoveis no filtro original, nenhum relaxamento."""
    for numero in range(4):
        await _imovel(session, f"AP-31{numero}", preco_venda=35000000)

    chamadas = 0
    from mobia.domain.catalogo import busca as modulo_de_busca

    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
        buscar=contando,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE
    assert len(resultado.candidatos) == 4


async def test_cenario_4_so_bairro_marcado_adjacente_entra(session: Any) -> None:
    """Cenario 4: a ampliacao se limita a tabela.

    Campeche NAO e adjacente a Trindade; Itacorubi e. O de Campeche fica fora
    mesmo cabendo no preco relaxado -- e o que separa "ampliar" de "desistir
    do filtro de regiao".
    """
    dentro = await _imovel(
        session, "AP-320", preco_venda=43000000, bairro="Itacorubi", zona="NORTE"
    )
    await _imovel(session, "AP-321", preco_venda=43000000, bairro="Campeche", zona="SUL")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]


async def test_o_bairro_pedido_continua_na_busca_relaxada(session: Any) -> None:
    """A leitura do "apenas" do cenario 4: uniao, nao substituicao.

    O imovel da Trindade nao cabia no teto duro e cabe no relaxado. Exclui-lo
    seria devolver o vizinho e esconder o bairro que o lead pediu.
    """
    na_trindade = await _imovel(session, "AP-322", preco_venda=43000000, bairro="Trindade")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [na_trindade]


async def test_nada_relaxavel_nao_faz_segunda_consulta(session: Any) -> None:
    """D5. Sem teto, sem piso e sem regiao, a segunda consulta seria identica."""
    await _imovel(session, "AP-330", quartos=2)

    chamadas = 0
    from mobia.domain.catalogo import busca as modulo_de_busca

    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, quartos_min=4),
        buscar=contando,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE


async def test_busca_por_zona_relaxa_preco_e_nao_amplia_bairro(session: Any) -> None:
    """L2. "zona sul" nao e nome de bairro e nao casa linha nenhuma da tabela.

    E a decisao correta -- a zona ja e o agregado de bairros --, mas e
    comportamento que alguem vai encontrar e achar que e bug.
    """
    no_sul = await _imovel(
        session, "AP-340", preco_venda=43000000, bairro="Campeche", zona="SUL"
    )
    await _imovel(session, "AP-341", preco_venda=43000000, bairro="Centro", zona="CENTRO")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("zona sul",)
        ),
    )

    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
    assert [candidato.imovel_id for candidato in resultado.candidatos] == [no_sul]
    # So o preco cedeu -- e por isso o aviso nao pode ser uma constante fixa
    # que diga "inclui bairros vizinhos" (D11).
    assert (resultado.relaxou_preco, resultado.relaxou_bairro) == (True, False)


async def test_o_vetor_e_calculado_uma_vez_para_os_dois_passes(session: Any) -> None:
    """D9. Sem isto, todo turno relaxado paga duas chamadas ao provedor."""
    await _imovel(session, "AP-350", preco_venda=43000000, bairro="Agronomica", zona="CENTRO")

    chamadas = 0

    async def embedador(textos: list[str]) -> list[list[float]]:
        nonlocal chamadas
        chamadas += 1
        return [[0.0] * 1536]

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
        consulta_texto="apartamento com varanda",
        embedador=embedador,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short -k cenario`
Expected: FAIL com `ImportError: cannot import name 'buscar_com_relaxamento'`.

- [ ] **Step 3: Implemente**

Acrescente a `src/mobia/domain/catalogo/relaxamento.py` — os imports novos no topo e as duas funções no fim:

```python
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.busca import MAX_CANDIDATOS, _vetor_da_consulta
from mobia.domain.catalogo.busca import buscar as buscar_de_verdade
from mobia.domain.catalogo.enums import EstadoDoRelaxamento
from mobia.domain.catalogo.models import BairroAdjacente
from mobia.domain.catalogo.schemas import Embedador, ResultadoDaBusca

log = structlog.get_logger(__name__)
```

```python
async def adjacentes_de(session: AsyncSession, regioes: Sequence[str]) -> tuple[str, ...]:
    """Os bairros vizinhos dos que o lead pediu, na forma dobrada. D8.

    Um `IN` simples sobre a PK: a tabela guarda as duas direcoes justamente
    para que esta consulta nao precise ser um OR sobre duas colunas com uniao.

    Regiao que nao e nome de bairro -- "zona sul", por exemplo -- simplesmente
    nao casa linha nenhuma, e o resultado e vazio. Nao e erro: e a L2, e o
    passe relaxa so o preco.
    """
    if not regioes:
        return ()

    linhas = await session.execute(
        select(BairroAdjacente.adjacente_busca).where(
            BairroAdjacente.bairro_busca.in_(tuple(regioes))
        )
    )
    return tuple(sorted({linha[0] for linha in linhas}))


async def buscar_com_relaxamento(
    session: AsyncSession,
    filtro: FiltroDeBusca,
    consulta_texto: str | None = None,
    limite: int = MAX_CANDIDATOS,
    embedador: Embedador | None = None,
    buscar: Any = None,
) -> ResultadoDaBusca:
    """A busca da RN-09.1 com a politica de zero-resultado da RN-09.3.

    **Um passe a mais, no maximo, e nunca uma cascata.** A regra poe "um" em
    negrito e a card repete: "nunca uma cascata de tentativas". Uma escada
    (relaxa preco, se ainda zero amplia bairro) devolveria resultado mais
    proximo do pedido, mas custaria ate tres consultas contra o p95 de 400 ms
    que a TEC-159 mede. Ver D4.

    `buscar` e injetavel para o teste contar chamadas sem banco falso -- mesmo
    molde do `buscar` injetavel de `porta_de_busca`.
    """
    executar = buscar or buscar_de_verdade

    # D9: UMA vez, e o mesmo vetor vai para os dois passes. Sem isto, o passe 2
    # recebe `consulta_texto` de novo e chama o embedador outra vez -- segunda
    # chamada paga ao provedor e segunda latencia, para o mesmo texto, em todo
    # turno relaxado.
    vetor = await _vetor_da_consulta(consulta_texto, embedador)

    resultado = await executar(session, filtro, vetor=vetor, limite=limite)
    if resultado.candidatos or not e_relaxavel(filtro):
        return resultado

    # D13: falha aqui derruba a DIMENSAO, nao a busca -- e o molde de
    # `_vetor_da_consulta` e da D6 da TEC-265. `Exception` ampla de proposito:
    # timeout, conexao caida e resposta malformada tem a mesma consequencia
    # aqui, e distinguir a causa nao muda o que o relaxamento faz.
    try:
        adjacentes = await adjacentes_de(session, filtro.regioes)
    except Exception as erro:
        log.warning(
            "busca.adjacencia_indisponivel",
            tipo=type(erro).__name__,
            detalhe="o relaxamento segue so na faixa de preco",
        )
        adjacentes = ()

    relaxado = await executar(session, alargar(filtro, adjacentes), vetor=vetor, limite=limite)

    # D6: `APLICADO` significa "o que voce esta vendo veio do passe relaxado".
    # Relaxou e continuou zero e `SEM_RESULTADO`, e nao `APLICADO` com lista
    # vazia -- senao o aviso ao lead anunciaria "ampliei o criterio" seguido de
    # nada, e o turno nao teria como oferecer o desfecho que a regra 4 da card
    # exige.
    return replace(
        relaxado,
        relaxamento=(
            EstadoDoRelaxamento.APLICADO
            if relaxado.candidatos
            else EstadoDoRelaxamento.SEM_RESULTADO
        ),
        # D11: o aviso tem tres variantes e escolhe por estes dois. Afirmar
        # "inclui bairros vizinhos" quando `adjacentes` veio vazio seria o
        # aviso mentindo -- e e o caso de todo lead que nao deu regiao, e de
        # toda busca por zona (L2).
        relaxou_preco=(
            filtro.preco_max_centavos is not None or filtro.preco_min_centavos is not None
        ),
        relaxou_bairro=bool(adjacentes),
    )
```

> **Sobre importar `_vetor_da_consulta`, que é privada.** É import dentro do mesmo pacote (`domain/catalogo`), e a alternativa — duplicar o `try/except` do provedor — criaria uma segunda política de degradação para a mesma falha. Se o revisor preferir, renomeie para `vetor_da_consulta` em `busca.py` e atualize as duas referências; o comportamento não muda.

- [ ] **Step 4: Rode para ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short`
Expected: 16 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/catalogo/relaxamento.py tests/integration/test_relaxamento_busca.py
git commit -m "feat(TEC-160): busca sem resultado tenta uma segunda vez, com a faixa e os vizinhos"
```

---

## Task 7: O contrato HTTP

**Files:**
- Modify: `src/mobia/api/routes/imoveis.py`
- Test: `tests/integration/test_relaxamento_busca.py`

**Interfaces:**
- Consumes: `buscar_com_relaxamento` (Task 6).
- Produces: `relaxamentoAplicado` no corpo do `POST /api/v1/imoveis/busca`.

- [ ] **Step 1: Encontre o molde do teste HTTP**

Run: `grep -rn "imoveis/busca" tests/integration/*.py | head -5`

Use o mesmo cliente e o mesmo cabeçalho de admin que os testes existentes daquele endpoint usam. **Não invente um fixture novo** — se o endpoint já é exercitado em `tests/integration/`, copie a montagem de lá.

- [ ] **Step 2: Escreva o teste que falha**

No arquivo que a busca já usa para testes HTTP (o mesmo que o passo 1 encontrou), acrescente:

```python
async def test_o_contrato_da_secao_6_3_devolve_relaxamento_aplicado(...) -> None:
    """Secao 6.3 do SRS: `relaxamentoAplicado` esta no exemplo de resposta.

    Busca que acha no filtro duro devolve `false` -- e o valor que o exemplo
    do SRS escreve.
    """
    # ... monte um imovel que casa o filtro, no molde do arquivo ...
    resposta = await cliente.post("/api/v1/imoveis/busca", json={...}, headers={...})

    assert resposta.status_code == 200
    assert resposta.json()["relaxamentoAplicado"] is False
```

- [ ] **Step 3: Rode para ver falhar**

Expected: `KeyError: 'relaxamentoAplicado'`.

- [ ] **Step 4: Implemente**

Em `src/mobia/api/routes/imoveis.py`, troque o import:

```python
from mobia.domain.catalogo.busca import MAX_CANDIDATOS
from mobia.domain.catalogo.enums import EstadoDoRelaxamento
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
```

Troque a chamada:

```python
        resultado = await buscar_com_relaxamento(
            session, filtro, consulta_texto=pedido.consulta_texto, limite=pedido.limite
        )
```

E acrescente ao dict de retorno, depois de `"totalCandidatos"`:

```python
        # RN-09.3, e o campo que o exemplo da secao 6.3 ja escrevia. Booleano
        # na borda, tri-estado no dominio: `SEM_RESULTADO` sai como `false`
        # aqui porque, do ponto de vista do chamador HTTP, nao ha nada
        # relaxado para ver. Quem precisa dos tres estados e o turno (D6).
        "relaxamentoAplicado": resultado.relaxamento is EstadoDoRelaxamento.APLICADO,
```

Atualize a docstring de `busca`: a frase sobre o embedador não injetado continua verdadeira, mas acrescente que a rota agora relaxa.

- [ ] **Step 5: Rode para ver passar, e confirme que os testes existentes da rota não quebraram**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/ -q --tb=short -k "busca or imoveis"
```
Expected: todos passam.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/routes/imoveis.py tests/integration/
git commit -m "feat(TEC-160): o POST de busca relaxa e diz que relaxou"
```

---

## Task 8: O `tool_result` e a frase do prompt

**Atenção: esta é a única task que gasta o orçamento do prompt.**

**Files:**
- Modify: `src/mobia/domain/agente/ferramenta_de_busca.py`
- Modify: `src/mobia/domain/agente/classificador.py`
- Test: o arquivo unitário que já exercita `porta_de_busca` (encontre com `grep -rln "porta_de_busca" tests/unit/`)

**Interfaces:**
- Consumes: `buscar_com_relaxamento` (Task 6), `EstadoDoRelaxamento` (Task 1).
- Produces: `relaxamento_aplicado: bool` e `relaxamento_sem_resultado: bool` no dict do `tool_result`.

- [ ] **Step 1: Meça o orçamento ANTES de escrever qualquer coisa**

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

Anote a margem que ele imprime. **Não transcreva o teto para lugar nenhum** — ele vive uma vez só, no corpo daquele teste, e uma segunda cópia envelhece sozinha.

- [ ] **Step 2: Escreva os testes que falham**

No arquivo unitário de `porta_de_busca`:

```python
async def test_o_tool_result_diz_que_relaxou() -> None:
    """D6 e D12. O modelo precisa saber, senao afirma ao lead que achou o
    pedido exato sobre um imovel 10% acima do orcamento em bairro vizinho."""

    async def buscar_falso(*args: Any, **kwargs: Any) -> ResultadoDaBusca:
        return ResultadoDaBusca(
            candidatos=(),
            total_candidatos=0,
            consulta_vetorizada=False,
            relaxamento=EstadoDoRelaxamento.APLICADO,
        )

    porta = porta_de_busca(_session_factory_falsa(), buscar=buscar_falso)

    saida = await porta({"operacao": "VENDA"})

    assert saida["relaxamento_aplicado"] is True
    assert saida["relaxamento_sem_resultado"] is False


async def test_o_tool_result_distingue_relaxou_e_nao_achou() -> None:
    """Regra 4 da card: o turno precisa dos tres estados, e dois booleanos
    derivados de um enum os carregam sem permitir o estado impossivel."""

    async def buscar_falso(*args: Any, **kwargs: Any) -> ResultadoDaBusca:
        return ResultadoDaBusca(
            candidatos=(),
            total_candidatos=0,
            consulta_vetorizada=False,
            relaxamento=EstadoDoRelaxamento.SEM_RESULTADO,
        )

    porta = porta_de_busca(_session_factory_falsa(), buscar=buscar_falso)

    saida = await porta({"operacao": "VENDA"})

    assert saida["relaxamento_aplicado"] is False
    assert saida["relaxamento_sem_resultado"] is True
```

> `_session_factory_falsa()` é o helper que o arquivo já usa para os testes existentes de `porta_de_busca`. **Reúse o que estiver lá**, não crie outro.

- [ ] **Step 3: Rode para ver falhar**

Expected: `KeyError: 'relaxamento_aplicado'`.

- [ ] **Step 4: Implemente no `tool_result`**

Em `ferramenta_de_busca.py`, troque o import de `buscar` por `buscar_com_relaxamento` (e `executar = buscar or buscar_com_relaxamento`), e acrescente ao dict devolvido pela porta:

```python
        return {
            "candidatos": [_candidato_serializavel(c) for c in resultado.candidatos],
            # RN-09.2: o agente precisa saber que ve 10 de 40.
            "total_candidatos": resultado.total_candidatos,
            # RN-09.3, D6. Booleanos derivados do tri-estado do dominio, num
            # lugar so. O primeiro e explicado ao modelo no prompt; o segundo
            # NAO e, de proposito -- ele e consumido pelo nosso codigo no
            # turno, e no caminho em que ele e verdadeiro a prosa do modelo e
            # substituida de qualquer jeito (D14). Explica-lo custaria
            # orcamento de prompt para mudar nada.
            "relaxamento_aplicado": resultado.relaxamento is EstadoDoRelaxamento.APLICADO,
            "relaxamento_sem_resultado": (
                resultado.relaxamento is EstadoDoRelaxamento.SEM_RESULTADO
            ),
            # D11. QUAIS dimensoes cederam, para o turno escolher a variante do
            # aviso. Tambem nao sao explicados ao modelo: ele nao redige o
            # aviso, nos redigimos.
            "relaxamento_de_preco": resultado.relaxou_preco,
            "relaxamento_de_bairro": resultado.relaxou_bairro,
        }
```

- [ ] **Step 5: Acrescente a frase ao prompt**

Em `SISTEMA_DO_AGENTE`, em `classificador.py`, acrescente ao bloco que já fala sobre não inventar informação de imóveis:

```python
    "relaxamento_aplicado true: os imoveis passam do pedido; nao diga que "
    "atendem.\n\n"
```

- [ ] **Step 6: Meça de novo**

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

**Se passar:** siga. **Se reprovar:** a pergunta é *"o que sai do prompt para o novo texto entrar?"*, não *"quanto subo o número?"*. Subir é resposta legítima, mas só depois da primeira pergunta — e antes de subir o teto fixo, calcule o derivado de `test_diferenca_entre_o_contado_e_o_enviado` (`subcontagem < contexto_headroom_de_tokens * 0,75`) e confirme que ele continua maior; passar o fixo do derivado torna o fixo decorativo. Registre no docstring daquele teste o que esta card gastou, como as cards anteriores fizeram.

- [ ] **Step 7: Rode os dois testes de orçamento e os unitários da porta**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py -q --tb=short
./.venv/Scripts/python.exe -m pytest tests/unit/ -q --tb=short -k "ferramenta or porta_de_busca"
```

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ferramenta_de_busca.py src/mobia/domain/agente/classificador.py tests/unit/
git commit -m "feat(TEC-160): o agente sabe que os imoveis vieram do criterio ampliado"
```

---

## Task 9: O aviso ao lead

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py` (extrair o estado dos `tool_result`)
- Modify: `src/mobia/domain/agente/schemas.py` (dois campos no resultado)
- Modify: `src/mobia/domain/agente/turno.py`
- Test: o arquivo de testes de turno que já cobre a apresentação (encontre com `grep -rln "KINDS_DAS_FICHAS\|TEXTO_DA_IDENTIFICACAO" tests/`)

**Interfaces:**
- Consumes: os dois booleanos do `tool_result` (Task 8).
- Produces: `TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO`, `TEXTO_DO_CRITERIO_AMPLIADO_PRECO`, `TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO`, `KIND_DO_CRITERIO_AMPLIADO`, e `aviso_de_ampliacao(relaxou_preco, relaxou_bairro) -> str`.

- [ ] **Step 1: Escreva o teste unitário da variante**

Em `tests/unit/test_relaxamento_alargar.py`:

```python
from mobia.domain.agente.turno import (
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    aviso_de_ampliacao,
)


def test_a_variante_do_aviso_corresponde_ao_que_mudou() -> None:
    """D11. A card exige "avisado ... e EM QUE".

    Uma constante fixa que dissesse sempre as duas coisas seria o aviso
    mentindo: o lead que nao deu regiao teve so o preco relaxado, e ouvir
    "inclui bairros vizinhos" e informacao falsa sobre o que o sistema fez --
    num aviso cujo proposito inteiro e ser explicito.
    """
    assert aviso_de_ampliacao(True, True) == TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO
    assert aviso_de_ampliacao(True, False) == TEXTO_DO_CRITERIO_AMPLIADO_PRECO
    assert aviso_de_ampliacao(False, True) == TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO


def test_o_aviso_nao_cita_valor() -> None:
    """D11. O numero ampliado e conta nossa, nao fato do banco.

    E o que mantem o aviso fora da discussao da TEC-161: texto nosso nao passa
    por `divergencias_de`, mas um texto nosso que cita valor convida o proximo
    leitor a achar que passa.
    """
    for texto in (
        TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
        TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
        TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    ):
        assert not any(caractere.isdigit() for caractere in texto)


def test_os_textos_do_aviso_sao_ascii() -> None:
    """Todo texto que sai para o lead e ASCII sem acento -- a disciplina de
    `apresentacao.py` e de `TEXTO_DA_BUSCA_INCONCLUSIVA`."""
    for texto in (
        TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
        TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
        TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    ):
        assert texto.isascii()
```

- [ ] **Step 2: Rode para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_relaxamento_alargar.py -v -k aviso`
Expected: `ImportError`.

- [ ] **Step 3: Acrescente os textos, o kind e a função em `turno.py`**

Ao lado de `TEXTO_DA_BUSCA_INCONCLUSIVA`:

```python
# RN-09.3 / CA-09.3, e a regra "avisado ... e EM QUE" da card. TEC-160, D11.
#
# Tres variantes e nao uma constante: quando so o preco foi relaxado (o lead
# nao deu regiao), dizer "inclui bairros vizinhos" e informacao falsa sobre o
# que o sistema fez -- num aviso cujo proposito inteiro e ser explicito.
#
# Nenhum numero, de proposito: o teto ampliado e conta nossa, e nao fato do
# banco. Os nomes dos bairros tambem ficam de fora, e essa e a escolha mais
# discutivel -- nome de bairro E fato do catalogo. Ficam fora porque a lista e
# variavel (a Trindade amplia para tres, o Itacorubi para quatro) e uma
# mensagem que cresce com o grau do no e uma mensagem cujo pior caso ninguem
# mediu. O lead ve o bairro na ficha, que e onde ele importa.
_ABERTURA_DA_AMPLIACAO = "Nao achei nada exatamente no que voce pediu, entao "

TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco a busca: valor um pouco acima e "
    "bairros vizinhos. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_PRECO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco o valor. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}inclui bairros vizinhos. Veja se algum destes serve."
)

# Kind proprio e OBRIGATORIO, nao preferencia: `outbound_dispatches` tem
# UNIQUE (message_id, kind) -- a constraint `uq_outbound_message_kind`, criada
# na `0002` e nomeada em `outbound/port.py` --, e no caminho de apresentacao a
# identificacao ja envia com KIND_DA_RESPOSTA. Duas mensagens com o mesmo kind
# no mesmo message_id colidiriam na reserva, e a segunda seria descartada como
# se fosse reprocessamento. E o mesmo motivo que deu `reply_2` a segunda
# mensagem de texto da TEC-140.
#
# String fixa, sem id dentro, pelo argumento de idempotencia que o comentario
# de KINDS_DAS_FICHAS registra: kind que muda entre retentativas perde a dedup
# justamente quando ela importa. A coluna e String(32); isto tem 17.
KIND_DO_CRITERIO_AMPLIADO = "criterio_ampliado"


def aviso_de_ampliacao(relaxou_preco: bool, relaxou_bairro: bool) -> str:
    """A variante que corresponde ao que de fato foi relaxado. D11."""
    if relaxou_preco and relaxou_bairro:
        return TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO
    return TEXTO_DO_CRITERIO_AMPLIADO_PRECO if relaxou_preco else TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO
```

- [ ] **Step 4: Leve o estado do `tool_result` até o turno**

Em `classificador.py`, ao lado de `_candidatos_de`:

```python
# As quatro chaves de relaxamento do `tool_result`, na ordem em que
# `_relaxamento_de` as devolve. Uma tupla e nao quatro variaveis soltas: os
# quatro sao o MESMO tipo de fato lido do MESMO lugar, e a lista evita que
# acrescentar um quinto vire um quinto `or` copiado a mao.
_CHAVES_DO_RELAXAMENTO = (
    "relaxamento_aplicado",
    "relaxamento_sem_resultado",
    "relaxamento_de_preco",
    "relaxamento_de_bairro",
)


def _relaxamento_de(blocos: list[dict[str, Any]]) -> tuple[bool, bool, bool, bool]:
    """O que o relaxamento fez neste turno, na ordem de `_CHAVES_DO_RELAXAMENTO`.

    **Qualquer bloco basta**, e nao o ultimo: se algum dos candidatos que o
    modelo viu veio de um passe relaxado, o lead tem de ser avisado -- a card
    diz "sempre avisado". O laco de tool use pode chamar a busca mais de uma
    vez, e `_candidatos_de` ja concatena todos pelo mesmo raciocinio.
    """
    encontrados = [False] * len(_CHAVES_DO_RELAXAMENTO)
    for bloco in blocos:
        if bloco.get("is_error"):
            continue
        conteudo = json.loads(bloco["content"])
        for indice, chave in enumerate(_CHAVES_DO_RELAXAMENTO):
            encontrados[indice] = encontrados[indice] or bool(conteudo.get(chave))
    aplicado, sem_resultado, de_preco, de_bairro = encontrados
    return aplicado, sem_resultado, de_preco, de_bairro
```

Propague pelo mesmo caminho que `candidatos` já percorre: `_chamar` devolve a tupla (acrescente os dois booleanos), e o construtor do resultado do agente (em `schemas.py`, perto de `candidatos: list[dict[str, Any]]`) ganha:

```python
    # TEC-160. Os fatos que o turno precisa e que `candidatos` nao carrega.
    #
    # Os dois primeiros decidem QUAL mensagem sai: se o que o modelo viu veio
    # do passe relaxado (aviso da CA-09.3), e se relaxamos e continuamos sem
    # nada (o desfecho da regra 4 da card). Um booleano so colapsaria o
    # segundo com "nao relaxei", e as duas situacoes pedem mensagens
    # diferentes ao lead.
    #
    # Os dois ultimos decidem QUAL VARIANTE do aviso: `relaxou_e_achou` vale
    # tanto para "so preco" quanto para "preco e bairro", e um texto fixo que
    # dissesse sempre os dois mentiria para todo lead que nao deu regiao.
    relaxou_e_achou: bool = False
    relaxou_sem_resultado: bool = False
    relaxou_preco: bool = False
    relaxou_bairro: bool = False
```

- [ ] **Step 5: Envie o aviso no caminho de apresentação**

Em `turno.py`, dentro do `if apresentando:`, **depois** do bloco que envia `TEXTO_DA_IDENTIFICACAO` e **antes** da chamada a `_apresentar`:

```python
            if gerada.relaxou_e_achou:
                # CA-09.3. Mensagem propria, e NAO prefixo da legenda: no
                # caminho de apresentacao `legenda_de` corta o PREFIXO antes da
                # ficha, e `_prosa_que_cabe` devolve string vazia quando nao
                # sobra espaco. A TEC-139 ja pagou para descobrir isso com a
                # identificacao -- "ela sairia truncada ou nao sairia nenhuma,
                # em silencio". Um aviso que some em silencio quebra a CA-09.3
                # exatamente no turno em que ela existe para valer.
                #
                # Cabe na RN-04.2 sem emenda: a E-02 da TEC-162 separou os
                # tetos em ate 2 mensagens de TEXTO e ate 3 de APRESENTACAO, e
                # isto e identificacao + aviso + ate 3 fichas. **Depois desta
                # card nao sobra folga de texto** -- a proxima trilha que
                # quiser mensagem propria precisa de emenda.
                await outbound.send(
                    message.id,
                    KIND_DO_CRITERIO_AMPLIADO,
                    {
                        "para": message.conversation_key,
                        "de": message.recipient_external_id,
                        "texto": aviso_de_ampliacao(
                            gerada.relaxou_preco, gerada.relaxou_bairro
                        ),
                    },
                )
```

> `gerada.relaxou_preco` e `gerada.relaxou_bairro` chegam pelo mesmo caminho que `relaxou_e_achou` — ver o passo 4. Os dois nascem em `ResultadoDaBusca` (Task 1), são preenchidos por `buscar_com_relaxamento` (Task 6) e serializados no `tool_result` (Task 8).

- [ ] **Step 6: Escreva o teste de turno**

No arquivo de testes de turno, no molde dos testes de identificação da TEC-139:

```python
async def test_o_aviso_de_ampliacao_sai_como_mensagem_propria(...) -> None:
    """CA-09.3. Kind proprio, antes das fichas, nunca prefixo de legenda."""
    # ... monte um turno com candidatos e relaxou_e_achou=True ...
    kinds = [chamada.kind for chamada in outbound_falso.enviados]
    assert KIND_DO_CRITERIO_AMPLIADO in kinds
    assert kinds.index(KIND_DO_CRITERIO_AMPLIADO) < kinds.index("ficha_1")


async def test_o_aviso_nao_sai_quando_o_modelo_perguntou(...) -> None:
    """D10. Pergunta adia as fichas, e avisar "ampliei o criterio" sem mostrar
    alternativa e aviso sobre nada. A CA-09.3 diz "o lead recebe alternativas
    COM aviso": os dois andam juntos ou nenhum anda."""
    # ... turno com candidatos, relaxou_e_achou=True, e `perguntou` preenchido ...
    assert KIND_DO_CRITERIO_AMPLIADO not in [c.kind for c in outbound_falso.enviados]


async def test_busca_sem_relaxamento_nao_avisa(...) -> None:
    """Cenario 3 do Gherkin: "nenhum aviso de ampliacao e enviado"."""
    # ... turno com candidatos e relaxou_e_achou=False ...
    assert KIND_DO_CRITERIO_AMPLIADO not in [c.kind for c in outbound_falso.enviados]
```

- [ ] **Step 7: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_relaxamento_alargar.py -q --tb=short
./.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -k turno
```

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ tests/
git commit -m "feat(TEC-160): o lead sabe que o criterio foi ampliado, e em que dimensao"
```

---

## Task 10: O desfecho quando nem ampliando aparece algo

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Test: o mesmo arquivo de testes de turno da Task 9

**Interfaces:**
- Consumes: `gerada.relaxou_sem_resultado` (Task 9).
- Produces: `TEXTO_SEM_RESULTADO_APOS_AMPLIAR`.

- [ ] **Step 1: Escreva o teste que falha**

```python
async def test_relaxou_e_nao_achou_oferece_o_corretor(...) -> None:
    """Cenario 2 do Gherkin e regra 4 da card: "informa e oferece a lista de
    espera ou conversa com o corretor". A lista de espera esta fora de escopo
    (E5), entao o desfecho oferece o corretor."""
    # ... turno sem candidatos e com relaxou_sem_resultado=True ...
    assert enviado.texto == TEXTO_SEM_RESULTADO_APOS_AMPLIAR


async def test_zero_de_nada_relaxavel_mantem_a_prosa_do_modelo(...) -> None:
    """D14. O card so legisla sobre o zero POS-relaxamento. No outro, o modelo
    ainda pode fazer algo util que nos nao sabemos fazer -- perguntar se o lead
    aceita dois quartos, por exemplo -- e cala-lo custaria mais do que
    padroniza."""
    # ... turno sem candidatos e com relaxou_sem_resultado=False ...
    assert enviado.texto == prosa_do_modelo


async def test_citacao_bloqueada_vence_o_desfecho(...) -> None:
    """Se o modelo inventou imovel, a mensagem da TEC-161 e a que importa: ela
    e sobre um defeito nosso, e o desfecho e sobre o catalogo."""
    # ... turno sem candidatos, relaxou_sem_resultado=True, prosa com citacao invalida ...
    assert enviado.texto == TEXTO_DA_BUSCA_INCONCLUSIVA
```

- [ ] **Step 2: Rode para ver falhar**

Expected: `ImportError: cannot import name 'TEXTO_SEM_RESULTADO_APOS_AMPLIAR'`.

- [ ] **Step 3: Acrescente o texto**

Ao lado de `TEXTO_DA_BUSCA_INCONCLUSIVA`:

```python
# Regra 4 da card e cenario 2 do Gherkin. TEC-160, D14.
#
# **Constante nova, e nao reuso de TEXTO_DA_BUSCA_INCONCLUSIVA.** Aquele
# promete "ja te retorno com as opcoes", e aqui nao ha opcao nenhuma para
# retornar -- seria o sistema prometendo o que sabe que nao tem. O laco
# excedido e a citacao bloqueada podem prometer porque nos dois casos os
# imoveis existem e o problema e nosso.
#
# A card manda oferecer "a lista de espera ou o corretor", e poe a lista de
# espera fora de escopo (E5). Este texto entrega a metade disponivel; quando o
# E5 existir, e aqui que se volta.
TEXTO_SEM_RESULTADO_APOS_AMPLIAR = (
    "Procurei tambem um pouco alem do que voce pediu e mesmo assim nao achei "
    "nada que valha a pena te mostrar agora. Quer que um corretor olhe isso "
    "com voce?"
)
```

- [ ] **Step 4: Substitua o texto no caminho de não-apresentação**

Em `turno.py`, **depois** do bloco `if citacao_bloqueada:` e **antes** do `identificar = ...`:

```python
    # D14. Relaxou e continuou zero tem desfecho nosso, e nao prosa do modelo:
    # e o cenario 2 do Gherkin. `not citacao_bloqueada` porque, se o modelo
    # inventou imovel, a mensagem da TEC-161 e a que importa -- ela fala de um
    # defeito nosso, e este texto fala do catalogo.
    #
    # So no zero POS-relaxamento. O zero de "nada relaxavel" (D5) segue com a
    # prosa do modelo: ali ele ainda pode perguntar algo util que nos nao
    # sabemos perguntar, e cala-lo custaria mais do que padroniza.
    if gerada.relaxou_sem_resultado and not citacao_bloqueada:
        texto = TEXTO_SEM_RESULTADO_APOS_AMPLIAR
```

> Confira que este ponto fica **antes** da moderação de saída do texto constante — o comentário existente diz que aquele ponto "fica DEPOIS das duas reatribuicoes de `texto` acima, e por isso cobre tres trilhas". Agora são quatro. **Atualize esse comentário**: ele conta trilhas, e um comentário que conta errado é o defeito que o `CLAUDE.md` descreve.

- [ ] **Step 5: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -k turno
```

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/
git commit -m "feat(TEC-160): sem resultado nem ampliando, o lead recebe o corretor e nao o silencio"
```

---

## Task 11: As emendas ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1: Acrescente as duas linhas ao índice de emendas**

Depois da última linha da tabela (por volta da linha 25), no mesmo formato:

```
> | E-01 | RN-09.3 | [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) | 11/09/2026 |
> | E-01 | CA-09.1 | [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160) | 11/09/2026 |
```

- [ ] **Step 2: Escreva a emenda da RN-09.3**

Como item **aninhado** logo abaixo da RN-09.3 (linha ~269), **sem reescrever** o texto de 22/08/2026. Os oito pontos estão na seção "As emendas ao SRS" do desenho — copie-os de lá, em prosa, no molde das emendas existentes (elas explicam o *porquê*, não só o *quê*, e terminam apontando a decisão do desenho: "Ver a Dn do desenho").

- [ ] **Step 3: Escreva a emenda da CA-09.1**

Como item aninhado abaixo da CA-09.1 (linha ~277). O conteúdo está no desenho. O ponto que não pode faltar: **a metade dos quartos não se mexe** — a RN-09.3 relaxa preço e bairro, nunca quartos, tipo ou vagas, então *"menos de 2 quartos"* segue valendo sem ressalva nos dois passes.

- [ ] **Step 4: Confira que nenhum texto original foi reescrito**

```bash
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md
```
Expected: só **adições**. Qualquer linha removida que não seja o fim da tabela do índice é erro — as emendas nunca reescrevem o texto de 22/08/2026.

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-160): a RN-09.3 diz o que o codigo teria de decidir sozinho, e a CA-09.1 admite o passe relaxado"
```

---

## Task 12: Verificação final

- [ ] **Step 1: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 2: A suíte inteira, com diagnóstico**

```bash
git rev-parse --short HEAD
./.venv/Scripts/python.exe -u -m pytest -v --tb=short > suite.txt 2>&1
```

**Guarde o hash junto com o resultado.** A evidência que fecha o argumento é a mesma árvore duas vezes — na TEC-156, `b35069d` passou 1236/1236 e, na execução seguinte sobre árvore idêntica e limpa, falhou 1.

Leva ~22 minutos em máquina ociosa, e muito mais sob carga. Arquivo de saída crescendo devagar é normal; `-u -m pytest -v` existe para você ver progresso.

- [ ] **Step 3: Triagem de qualquer falha**

Antes de atribuir uma falha à sua mudança:
1. Se o traceback for `ConnectionResetError [WinError 64]` ou erro de Redis, **rode o arquivo sozinho**. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` falham sob carga e passam 100% isolados.
2. Se passar isolado e você ainda suspeitar, rode a versão **antiga** o mesmo número de vezes antes de concluir qualquer coisa.

- [ ] **Step 4: Confirme os quatro cenários da card, um a um**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_relaxamento_busca.py -v --tb=short -k cenario
```
Expected: os quatro passam, e os nomes dos testes dizem qual cenário é qual.

- [ ] **Step 5: Abra o PR**

```bash
git push -u origin feat/tec-160-relaxamento-de-criterio
gh pr create --base main --title "TEC-160: relaxar o criterio quando a busca nao devolve nada"
```

O corpo do PR deve citar o desenho, os quatro cenários do Gherkin, as duas emendas ao SRS, e — se a Task 8 tiver mexido no teto do orçamento — quanto custou e o que saiu para caber. Termine com:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Auto-revisão deste plano

**Cobertura do desenho:** D1→Task 5; D2→Tasks 1 e 2; D3→Task 2; D4→Task 6; D5→Tasks 5 e 6; D6→Tasks 1, 6, 7, 8; D7→Task 4; D8→Tasks 4 e 6; D9→Tasks 3 e 6; D10→Task 9; D11→Task 9; D12→Task 8; D13→Task 6; D14→Task 10. Emendas→Task 11. L2→Task 6. Os quatro cenários do Gherkin→Task 6 (e 9 para o "nenhum aviso" do cenário 3, 10 para a oferta do corretor do cenário 2).

**Dois pontos em que o plano manda você descobrir em vez de dar o código pronto**, e o motivo: os testes HTTP (Task 7) e os testes de turno (Tasks 9 e 10) dependem de fixtures e de um dublê de `outbound` que já existem nos arquivos daquelas áreas, e inventar um molde novo aqui produziria um segundo jeito de montar o mesmo teste. Os passos dizem exatamente o que procurar (`grep`) e o que afirmar.

**Consistência de tipos:** `relaxamento` é `EstadoDoRelaxamento` em todo o domínio e vira booleano só em dois pontos, ambos escritos por extenso (Task 7 para o HTTP, Task 8 para o `tool_result`). `relaxou_preco`/`relaxou_bairro` nascem em `ResultadoDaBusca` (Task 1), são preenchidos em `buscar_com_relaxamento` (Task 6), serializados como `relaxamento_de_preco`/`relaxamento_de_bairro` no `tool_result` (Task 8) e lidos como `gerada.relaxou_preco`/`gerada.relaxou_bairro` no turno (Task 9). O nome muda de camada uma vez, na serialização, e está escrito nos dois lados.

**Ordem das tasks é linear.** Nenhuma task exige voltar a uma anterior: as Tasks 1→6 constroem o domínio de baixo para cima, a 7 e a 8 são as duas bordas, a 9 e a 10 são o turno, e a 11 é o SRS. As Tasks 7 e 8 são independentes entre si e podem trocar de ordem.

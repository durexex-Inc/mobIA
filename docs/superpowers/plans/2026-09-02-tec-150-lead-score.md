# TEC-150 — Lead score determinístico: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calcular, em código e sem o modelo, um score de 0 a 95 para o lead, com a contribuição de cada um dos cinco fatores exposta separadamente.

**Architecture:** Uma função pura em módulo novo. Quatro fatores leem `LeadQualification`; os dois que precisam de dados fora dela — contagem de mensagens e imóveis compatíveis — entram por parâmetro, como `recusados` entrou na TEC-147. A definição de "campo obrigatório preenchido" é importada de `qualificacao.py`, nunca reimplementada. O retorno é o detalhamento, não o total.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (só para os tipos do modelo), pytest, ruff, mypy. Sem migração, sem I/O, sem chamada ao modelo.

**Spec:** [`docs/superpowers/specs/2026-09-02-tec-150-lead-score-design.md`](../specs/2026-09-02-tec-150-lead-score-design.md)

## Global Constraints

- **Python ≥3.13.** `X | None`, nunca `typing.Optional`.
- **Os três gates que o CI roda**, todos, antes de cada commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
  Escopo `src tests alembic evals`, não `src tests`. **`ruff check` passar não diz nada sobre `ruff format`.**
- **Comentários e docstrings em português sem acento.** Prosa em `docs/` leva acento; código não. Comentário explica o *porquê*.
- **`calcular_score` é pura e nunca levanta.** Sem I/O, sem banco, sem modelo. `estado is None` devolve `Score` zerado.
- **Não há migração nesta card, e nada é gravado.** Se você se pegar escrevendo uma coluna de score, pare e releia o Fluxo da spec: onde o recálculo mora é decisão da TEC-151 e da TEC-152.
- **Nada reimplementa a lista de campos obrigatórios.** Ela vive em `qualificacao.py` desde a TEC-147, e a Task 1 expõe exatamente o que o score precisa.
- **A suíte é lenta:** `tests/unit` ~7 min, completa ~10. Não é travamento. Use `python -u -m pytest -v` para ver progresso.
- **Cada teste verificado por mutação.** Trocar uma faixa por outra tem de deixar vermelho o teste daquela faixa. Nas duas cards anteriores, *toda* rodada de revisão perdida foi teste que passava com o código certo ou errado — nunca implementação errada.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/context/qualificacao.py` *(modificar)* | Ganha uma função pública que conta obrigatórios preenchidos. `_preenchido` continua privada. |
| `src/mobia/domain/context/score.py` *(criar)* | O `Score` e os cinco fatores. Único lugar que sabe pesos e faixas. |

---

## Task 1: `qualificacao.py` expõe a contagem, não o interno

**Files:**
- Modify: `src/mobia/domain/context/qualificacao.py`
- Test: `tests/unit/test_qualificacao.py`

**Interfaces:**
- Consumes: `CAMPOS_OBRIGATORIOS`, `_preenchido` (ambos já existem no arquivo).
- Produces: `campos_obrigatorios_preenchidos(estado: LeadQualification | None) -> int`. A Task 2 consome.

**Por que uma função e não tornar `_preenchido` pública:** o score precisa de *quantos* obrigatórios estão preenchidos, não de decidir campo a campo. Expor `_preenchido` publicaria a forma interna da regra e convidaria o próximo módulo a iterar `CAMPOS_OBRIGATORIOS` por conta própria — que é meio caminho para a segunda cópia da lista. Uma função que responde a pergunta inteira não deixa esse espaço.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/unit/test_qualificacao.py`:

```python
from mobia.domain.context.qualificacao import (
    CAMPOS_OBRIGATORIOS,
    campos_obrigatorios_preenchidos,
)


def test_contagem_com_todos_preenchidos():
    assert campos_obrigatorios_preenchidos(_estado()) == len(CAMPOS_OBRIGATORIOS)


def test_contagem_de_estado_inexistente_e_zero():
    assert campos_obrigatorios_preenchidos(None) == 0


@pytest.mark.parametrize("faltando", ["intencao", "regiao", "urgencia"])
def test_cada_campo_faltando_tira_um(faltando):
    assert campos_obrigatorios_preenchidos(_estado(**{faltando: None})) == 3


def test_faixa_aberta_ainda_conta_como_um_campo():
    """A mesma regra do `esta_qualificado`: sao duas colunas, e qualquer
    extremo basta. A contagem nao pode discordar da qualificacao sobre o que
    e um campo preenchido -- e o motivo de esta funcao morar aqui e nao no
    modulo de score."""
    obtido = campos_obrigatorios_preenchidos(
        _estado(faixa_preco_min_centavos=None, faixa_preco_max_centavos=50_000_000)
    )
    assert obtido == len(CAMPOS_OBRIGATORIOS)


def test_sem_nenhum_extremo_de_preco_tira_um():
    obtido = campos_obrigatorios_preenchidos(
        _estado(faixa_preco_min_centavos=None, faixa_preco_max_centavos=None)
    )
    assert obtido == 3


def test_intencao_nao_qualificavel_nao_conta():
    """VENDER_IMOVEL preenche a coluna e nao conta como intencao (RN-03.4),
    exatamente como em `esta_qualificado`."""
    obtido = campos_obrigatorios_preenchidos(_estado(intencao=Intencao.VENDER_IMOVEL.value))
    assert obtido == 3
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_qualificacao.py -v`
Expected: FAIL com `ImportError: cannot import name 'campos_obrigatorios_preenchidos'`

- [ ] **Step 3: Implementar**

Acrescente a `src/mobia/domain/context/qualificacao.py`:

```python
def campos_obrigatorios_preenchidos(estado: LeadQualification | None) -> int:
    """Quantos dos obrigatorios da RN-05.3 este lead ja informou.

    Existe para o score da TEC-150, que pontua completude a 5 pontos por
    campo. Devolve a contagem, e nao expoe `_preenchido`: o score precisa da
    resposta inteira, e publicar o passo a passo convidaria o proximo modulo
    a iterar `CAMPOS_OBRIGATORIOS` por conta propria -- meio caminho para uma
    segunda copia da lista, que e o defeito que a TEC-146 gastou uma card
    inteira para consertar.
    """
    if estado is None:
        return 0
    return sum(1 for campo in CAMPOS_OBRIGATORIOS if _preenchido(estado, campo))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_qualificacao.py -v`
Expected: PASS. Os testes anteriores da TEC-147 seguem verdes e **não podem ser modificados**.

- [ ] **Step 5: Verificar por mutação**

Troque o `sum(...)` por `len(CAMPOS_OBRIGATORIOS)` fixo e confirme que os testes de campo faltando ficam vermelhos. Reverta. Registre a saída no relatório.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/qualificacao.py tests/unit/test_qualificacao.py
git commit -m "feat(TEC-150): a contagem de obrigatorios sai de onde a lista mora"
```

---

## Task 2: `score.py` — os cinco fatores e o total

**Files:**
- Create: `src/mobia/domain/context/score.py`
- Test: `tests/unit/test_score.py`

**Interfaces:**
- Consumes: `campos_obrigatorios_preenchidos` (Task 1); `Urgencia` e `FormaPagamento` de `mobia.domain.agente.schemas`; `LeadQualification`.
- Produces: `Score` (dataclass congelada com `completude`, `urgencia`, `catalogo`, `engajamento`, `capacidade` e a property `total`) e `calcular_score(estado, mensagens_do_lead=0, imoveis_compativeis=0) -> Score`. A Task 3 consome as duas.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_score.py`:

```python
import pytest

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.score import Score, calcular_score


def _estado(**campos) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste tirar."""
    base = {
        "channel": "whatsapp",
        "conversation_key": "5511999999999",
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 60_000_000,
        "regiao": "zona sul",
        "urgencia": Urgencia.IMEDIATA.value,
    }
    return LeadQualification(**{**base, **campos})


def test_estado_inexistente_zera_tudo():
    obtido = calcular_score(None)
    assert obtido == Score(completude=0, urgencia=0, catalogo=0, engajamento=0, capacidade=0)
    assert obtido.total == 0


@pytest.mark.parametrize(
    ("preenchidos", "pontos"),
    [(4, 20), (3, 15), (2, 10), (1, 5), (0, 0)],
)
def test_completude_e_cinco_por_campo(preenchidos, pontos):
    ausentes = ["urgencia", "regiao", "faixa_preco_max_centavos", "intencao"][: 4 - preenchidos]
    obtido = calcular_score(_estado(**dict.fromkeys(ausentes)))
    assert obtido.completude == pontos


@pytest.mark.parametrize(
    ("urgencia", "pontos"),
    [
        (Urgencia.IMEDIATA, 25),
        (Urgencia.ATE_3_MESES, 15),
        (Urgencia.ATE_6_MESES, 8),
        (Urgencia.SEM_PRESSA, 0),
    ],
)
def test_urgencia_por_faixa(urgencia, pontos):
    assert calcular_score(_estado(urgencia=urgencia.value)).urgencia == pontos


def test_urgencia_ausente_nao_pontua():
    assert calcular_score(_estado(urgencia=None)).urgencia == 0


@pytest.mark.parametrize(
    ("imoveis", "pontos"),
    [(9, 20), (5, 20), (4, 12), (1, 12), (0, 0)],
)
def test_catalogo_por_faixa(imoveis, pontos):
    assert calcular_score(_estado(), imoveis_compativeis=imoveis).catalogo == pontos


def test_catalogo_e_zero_por_default():
    """Enquanto a TEC-158 nao existir, ninguem passa o parametro e o fator
    contribui zero -- que e o que a card prescreve."""
    assert calcular_score(_estado()).catalogo == 0


@pytest.mark.parametrize(
    ("mensagens", "pontos"),
    [(10, 15), (6, 15), (5, 10), (3, 10), (2, 5), (1, 5), (0, 0)],
)
def test_engajamento_por_faixa(mensagens, pontos):
    assert calcular_score(_estado(), mensagens_do_lead=mensagens).engajamento == pontos


@pytest.mark.parametrize(
    ("forma", "pontos"),
    [
        (FormaPagamento.A_VISTA, 15),
        (FormaPagamento.FINANCIAMENTO, 12),
        (FormaPagamento.CONSORCIO, 12),
        (FormaPagamento.FGTS, 12),
        (FormaPagamento.INDEFINIDA, 6),
    ],
)
def test_capacidade_por_forma_de_pagamento(forma, pontos):
    assert calcular_score(_estado(forma_pagamento=forma.value)).capacidade == pontos


def test_capacidade_ausente_vale_a_avaliar():
    """Coluna nula e INDEFINIDA significam a mesma coisa para este fator: o
    lead nao disse como pagaria, entao e "a avaliar"."""
    assert calcular_score(_estado(forma_pagamento=None)).capacidade == 6
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_score.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.context.score'`

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/context/score.py`:

```python
"""O lead score deterministico da RN-06.1.

TEC-150. Puro de proposito: sem I/O, sem banco, sem chamada ao modelo -- a
card exige "calculado em codigo, nunca pelo LLM". Os dois fatores que
dependem de dados fora de `LeadQualification` entram por parametro, e nao por
consulta aqui dentro: quem chama consulta, e a regra continua testavel sem
banco. Mesma forma que `recusados` tem em `esta_qualificado`.

**O teto e 95, nao 100**, e 75 enquanto a TEC-158 nao existir. Ver D3 do
desenho: a RN-06.1 da ao fator de completude peso 25 e o criterio "5 pontos
por campo obrigatorio", e a RN-05.3 lista quatro obrigatorios. As duas
afirmacoes nao fecham, e vale a regra operavel.
"""

from dataclasses import dataclass

from mobia.domain.agente.schemas import FormaPagamento, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import campos_obrigatorios_preenchidos

PONTOS_POR_CAMPO_OBRIGATORIO = 5

# Constantes de modulo, e nao configuracao. A card pede pesos alteraveis sem
# deploy e a CA-19.1 pede sem reiniciar a aplicacao -- isso e um subsistema
# (persistir, autorizar, invalidar cache) e pertence ao epico de configuracao,
# nao ao de scoring. Lacuna declarada no desenho.
_PONTOS_POR_URGENCIA = {
    Urgencia.IMEDIATA.value: 25,
    Urgencia.ATE_3_MESES.value: 15,
    Urgencia.ATE_6_MESES.value: 8,
    Urgencia.SEM_PRESSA.value: 0,
}

# A RN-06.1 pontua tres categorias -- a vista, financiamento pre-aprovado, a
# avaliar -- e o enum tem cinco valores.
#
# Pre-aprovacao nao existe como dado neste repo, entao FINANCIAMENTO recebe os
# 12 do pre-aprovado: quem menciona financiar pontua como quem tem carta. E
# generoso, e esta declarado.
#
# CONSORCIO e FGTS nao tem nota no SRS. Recebem 12 por serem, como o
# financiamento, caminho de pagamento definido e nao "a avaliar". Inventar
# hierarquia mais fina entre os tres seria criar regra que o SRS nao contem.
_PONTOS_POR_CAPACIDADE = {
    FormaPagamento.A_VISTA.value: 15,
    FormaPagamento.FINANCIAMENTO.value: 12,
    FormaPagamento.CONSORCIO.value: 12,
    FormaPagamento.FGTS.value: 12,
    FormaPagamento.INDEFINIDA.value: 6,
}

# Coluna nula significa o mesmo que INDEFINIDA aqui: o lead nao disse como
# pagaria, e isso e "a avaliar", nao ausencia de capacidade.
_PONTOS_SEM_FORMA_DE_PAGAMENTO = 6


@dataclass(frozen=True)
class Score:
    """O score e a contribuicao de cada fator.

    A card exige que "cada fator devolve sua contribuicao, nao so o total":
    a TEC-152 grava "score anterior, novo, fatores e timestamp", e uma
    auditoria que precisasse recalcular os fatores para audita-los nao
    auditaria nada.
    """

    completude: int
    urgencia: int
    catalogo: int
    engajamento: int
    capacidade: int

    @property
    def total(self) -> int:
        return (
            self.completude
            + self.urgencia
            + self.catalogo
            + self.engajamento
            + self.capacidade
        )


def calcular_score(
    estado: LeadQualification | None,
    mensagens_do_lead: int = 0,
    imoveis_compativeis: int = 0,
) -> Score:
    """O score da RN-06.1. Nunca levanta.

    `imoveis_compativeis` tem default zero porque a busca de imoveis
    (TEC-158) nao existe, e a card prescreve que ate la o fator contribua
    zero. Quando ela existir, o chamador passa o numero real e nenhuma linha
    daqui muda.
    """
    if estado is None:
        return Score(completude=0, urgencia=0, catalogo=0, engajamento=0, capacidade=0)

    return Score(
        completude=campos_obrigatorios_preenchidos(estado) * PONTOS_POR_CAMPO_OBRIGATORIO,
        urgencia=_PONTOS_POR_URGENCIA.get(estado.urgencia or "", 0),
        catalogo=_pontos_do_catalogo(imoveis_compativeis),
        engajamento=_pontos_do_engajamento(mensagens_do_lead),
        capacidade=_PONTOS_POR_CAPACIDADE.get(
            estado.forma_pagamento or "", _PONTOS_SEM_FORMA_DE_PAGAMENTO
        ),
    )


def _pontos_do_catalogo(imoveis: int) -> int:
    if imoveis >= 5:
        return 20
    return 12 if imoveis >= 1 else 0


def _pontos_do_engajamento(mensagens: int) -> int:
    """Faixas arbitradas, e o criterio de aceite foi o unico guia.

    A RN-06.1 diz apenas "por numero de mensagens do lead e tempo medio de
    resposta" -- e o unico dos cinco fatores sem faixas. O cenario de aceite
    pede >=70 para um lead com os quatro obrigatorios, prazo de 20 dias e
    pagamento a vista: isso soma 60 sem catalogo, entao engajamento precisa
    render >=10 para o criterio da propria card fechar. Um lead que informou
    quatro campos mandou, por construcao, ao menos tres mensagens.

    Tempo medio de resposta fica fora, declarado como lacuna no desenho.
    """
    if mensagens >= 6:
        return 15
    if mensagens >= 3:
        return 10
    return 5 if mensagens >= 1 else 0
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_score.py -v`
Expected: PASS, **30 testes** (1 + 5 + 4 + 1 + 5 + 1 + 7 + 5 + 1, contando as expansões de `parametrize`). Siga a lista de testes, não o número — se divergir, a lista manda.

- [ ] **Step 5: Verificar por mutação**

Três mutações, e registre a saída de cada uma no relatório:

1. Troque `Urgencia.IMEDIATA.value: 25` por `20` — só o teste daquela faixa fica vermelho.
2. Troque `if imoveis >= 5` por `>= 4` — o caso `(4, 12)` fica vermelho.
3. Troque `_PONTOS_SEM_FORMA_DE_PAGAMENTO` por `0` — `test_capacidade_ausente_vale_a_avaliar` fica vermelho.

Reverta as três.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/score.py tests/unit/test_score.py
git commit -m "feat(TEC-150): os cinco fatores do score, com a contribuicao de cada um exposta"
```

---

## Task 3: As propriedades que o cálculo inteiro tem de ter

**Files:**
- Test: `tests/unit/test_score.py`

**Interfaces:**
- Consumes: `Score`, `calcular_score` (Task 2); `CAMPOS_OBRIGATORIOS` e `campos_obrigatorios_preenchidos` (Task 1).
- Produces: nada em código.

**O que esta task é:** os testes que a Task 2 não escreveu porque não são sobre um fator, e sim sobre o cálculo inteiro — o critério de aceite da card, o teto, o determinismo, e o teste que impede a completude de divergir da lista de obrigatórios.

- [ ] **Step 1: Escrever os testes que falham ou passam por acidente**

Acrescente a `tests/unit/test_score.py`:

```python
from mobia.domain.context.qualificacao import CAMPOS_OBRIGATORIOS
from mobia.domain.context.score import PONTOS_POR_CAMPO_OBRIGATORIO


def test_o_cenario_de_aceite_da_card():
    """Quatro obrigatorios, prazo de 20 dias, seis imoveis compativeis,
    pagamento a vista -> pelo menos 70.

    Com catalogo, como a card escreveu o cenario.
    """
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=4,
        imoveis_compativeis=6,
    )
    assert obtido.total >= 70


def test_o_mesmo_cenario_sem_catalogo_ainda_fecha():
    """A diferenca que a TEC-158 fara, pinada desde ja. Sem o catalogo o
    mesmo lead perde 20 pontos e ainda precisa alcancar 70 -- e o que forcou
    a calibragem das faixas de engajamento."""
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=4,
    )
    assert obtido.total >= 70


def test_a_completude_maxima_acompanha_a_lista_de_obrigatorios():
    """Impede a divergencia que a TEC-146 gastou uma card consertando: se
    alguem acrescentar um quinto obrigatorio na RN-05.3, este teste quebra e
    obriga a decidir o peso, em vez de o score simplesmente pontuar a menos
    em silencio."""
    maximo = calcular_score(_estado(), mensagens_do_lead=99, imoveis_compativeis=99).completude
    assert maximo == len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO


def test_o_total_e_a_soma_dos_cinco():
    """Quebraria se um fator fosse esquecido na soma -- que e o defeito mais
    facil de introduzir num dataclass que cresce."""
    s = calcular_score(
        _estado(forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=6,
        imoveis_compativeis=6,
    )
    assert s.total == s.completude + s.urgencia + s.catalogo + s.engajamento + s.capacidade


def test_o_teto_com_catalogo_e_95():
    """Nao 100. Ver D3: 5 pontos por campo com quatro obrigatorios da 20, e o
    peso 25 da tabela da RN-06.1 nao fecha com a lista da RN-05.3."""
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=99,
        imoveis_compativeis=99,
    )
    assert obtido.total == 95


def test_o_teto_sem_catalogo_e_75():
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=99,
    )
    assert obtido.total == 75


def test_o_calculo_e_deterministico():
    """A igualdade do dataclass compara os cinco fatores, nao so o total --
    entao dois calculos que somassem igual por caminhos diferentes seriam
    pegos aqui."""
    estado = _estado(forma_pagamento=FormaPagamento.FINANCIAMENTO.value)
    assert calcular_score(estado, 4, 3) == calcular_score(estado, 4, 3)


def test_nenhum_fator_e_negativo():
    """Contagem negativa nao e alcancavel por chamador nenhum, mas um peso
    trocado por engano poderia produzi-la, e um score negativo passaria
    despercebido numa fila ordenada."""
    s = calcular_score(_estado(), mensagens_do_lead=0, imoveis_compativeis=0)
    assert min(s.completude, s.urgencia, s.catalogo, s.engajamento, s.capacidade) >= 0
```

- [ ] **Step 2: Rodar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_score.py -v`
Expected: PASS. **Estes testes passam contra a Task 2 já implementada** — são propriedades, não requisitos novos. Se algum falhar, a Task 2 está errada e o conserto é lá, não aqui.

- [ ] **Step 3: Verificar que eles podem falhar**

Um teste de propriedade que nunca poderia falhar é decoração. Verifique cada um:

1. Troque `PONTOS_POR_CAMPO_OBRIGATORIO` para `6` — `test_a_completude_maxima_acompanha_a_lista_de_obrigatorios` continua verde (ele deriva do valor), mas `test_o_teto_com_catalogo_e_95` fica vermelho. **É o esperado**: o primeiro amarra a *relação*, o segundo amarra o *número*. Registre os dois comportamentos.
2. Remova `self.capacidade` da soma em `total` — `test_o_total_e_a_soma_dos_cinco` e os dois de teto ficam vermelhos.
3. Troque a faixa de engajamento `>= 3` por `>= 5` — `test_o_mesmo_cenario_sem_catalogo_ainda_fecha` fica vermelho, porque o lead do cenário manda 4 mensagens.

Reverta as três e registre no relatório.

- [ ] **Step 4: Suíte completa, gates e commit**

```bash
./.venv/Scripts/python.exe -m pytest
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add tests/unit/test_score.py
git commit -m "feat(TEC-150): as propriedades do calculo inteiro, e o teto que e 95"
```

Falhas intermitentes conhecidas sob carga (`ConnectionResetError`, Redis) em `test_montagem.py`, `test_sweep_stalled.py` e `test_dedup_por_message_id.py` passam isoladas e não são desta card.

---

## Auto-revisão

**Cobertura da spec.** D1 → Task 2 (assinatura e pureza). D2 → Task 2 (`Score` e `total`). D3 → Task 1 (a contagem vem de onde a lista mora) e Task 3 (`test_a_completude_maxima_acompanha_a_lista_de_obrigatorios`, `test_o_teto_com_catalogo_e_95`). D4 → Task 2, faixa a faixa. D5 → Task 2 (`_PONTOS_POR_CAPACIDADE` e o default). D6 → Task 2 (constantes de módulo, com o porquê no comentário). O Fluxo da spec diz que nada chama `calcular_score` ainda, e nenhuma task o chama — deliberado, não esquecimento.

**Consistência de tipos.** `campos_obrigatorios_preenchidos(estado) -> int` nasce na Task 1 e é chamada com essa assinatura na Task 2. `Score` e `calcular_score(estado, mensagens_do_lead=0, imoveis_compativeis=0)` nascem na Task 2 e são consumidos na Task 3 com os mesmos nomes e a mesma ordem de parâmetros. `PONTOS_POR_CAMPO_OBRIGATORIO` é público na Task 2 porque a Task 3 o importa.

**Uma escolha que merece atenção do revisor.** A Task 3 não introduz comportamento — seus testes passam contra a Task 2 sem mudança nenhuma. Isso a torna uma task de testes puros, o que normalmente eu evitaria. Ela existe separada porque um revisor pode legitimamente aprovar os fatores e reprovar as propriedades: são gates diferentes, e o teste que amarra a completude à lista de obrigatórios é justamente o tipo de coisa que se perde quando entra no meio de vinte e sete testes de faixa.

# TEC-146 — Normalizar valores monetários: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tirar do modelo a decisão da ordem de grandeza de valores monetários, passando-a para um parser determinístico em código, e armazenar preços em centavos.

**Architecture:** O `SCHEMA_DA_EXTRACAO` deixa de pedir dois números em reais e passa a pedir o trecho literal da fala do lead sobre orçamento. Um módulo novo e puro, `domain/agente/dinheiro.py`, resolve essa expressão em centavos, aplica uma banda de plausibilidade que depende da intenção do turno, e recusa com motivo tipado o que não fecha. `extrair` continua nunca levantando: recusa é descarte de campo. Uma regra curta no prompt faz o modelo pedir confirmação no mesmo turno — economia, não garantia.

**Tech Stack:** Python 3.13, SQLAlchemy 2 (asyncio) + asyncpg, Alembic, pytest (`asyncio_mode = "auto"`), ruff (`line-length = 100`), mypy (`files = ["src"]`).

**Spec:** [`docs/superpowers/specs/2026-09-01-tec-146-normalizar-valores-monetarios-design.md`](../specs/2026-09-01-tec-146-normalizar-valores-monetarios-design.md)

## Global Constraints

- **Python ≥3.13.** `StrEnum`, `X | None` nativos. Sem `typing.Optional`.
- **ruff:** `line-length = 100`, regras `E, F, I, UP, B`. Rode `./.venv/Scripts/python.exe -m ruff check src tests` antes de cada commit.
- **mypy:** cobre só `src`. `warn_unreachable = true` — código morto reprova.
- **Comentários e docstrings em português sem acento**, como todo o `src/`. Prosa de `docs/` leva acento; código não.
- **`extrair` nunca levanta.** Regra de desenho já entregue e testada por `test_extrair_nunca_levanta`. Nenhuma task pode quebrá-la.
- **Orçamento de prompt: margem de 13,0 tokens medida em 2026-09-01.** Teto fixo de 655 em `test_a_margem_do_orcamento_do_prompt_e_deliberada`. Antes de tocar em `SISTEMA_DO_AGENTE` ou no schema, rode `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`. Ao reprovar, a pergunta é *"o que sai para o novo texto entrar?"*, não *"quanto subo o número?"*.
- **Comando de teste:** `./.venv/Scripts/python.exe -m pytest`. O `addopts = "-m 'not perf'"` já exclui os testes de latência.
- **A ordem das tasks é orçamentária, não estética.** A Task 4 troca dois campos `number` por um `string` no schema compilado (parcela de 374,5 tokens) e **libera** margem; a Task 7 gasta. Inverter a ordem faz a Task 7 reprovar por um teto que a Task 4 teria aberto.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/agente/dinheiro.py` *(criar)* | Parser puro: expressão → centavos, ou recusa tipada. Sem I/O, sem banco, sem modelo. |
| `src/mobia/domain/agente/schemas.py` *(modificar)* | `Extracao` troca os dois campos `Decimal` por dois `int` em centavos. |
| `src/mobia/domain/agente/classificador.py` *(modificar)* | `SCHEMA_DA_EXTRACAO` passa a pedir a expressão; `extrair` chama o parser; `SISTEMA_DO_AGENTE` ganha a regra da banda. |
| `src/mobia/domain/context/models.py` *(modificar)* | `LeadQualification` troca `Numeric(12,2)` por `BigInteger`. |
| `alembic/versions/0011_preco_em_centavos.py` *(criar)* | Colunas novas, backfill, drop das antigas. |
| `src/mobia/evals/corpus.py` *(modificar)* | Converte a anotação em reais para centavos ao carregar. |

---

## Task 1: O núcleo do parser — valor único

**Files:**
- Create: `src/mobia/domain/agente/dinheiro.py`
- Test: `tests/unit/test_dinheiro.py`

**Interfaces:**
- Consumes: nada.
- Produces: `_Valor(centavos: int, tinha_marcador: bool)` e `_valor_de(texto: str) -> _Valor | None`. Privados ao módulo; a Task 2 os consome de dentro do mesmo arquivo.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/unit/test_dinheiro.py`:

```python
from decimal import Decimal

import pytest

from mobia.domain.agente.dinheiro import _Valor, _valor_de


@pytest.mark.parametrize(
    ("texto", "centavos", "tinha_marcador"),
    [
        ("500 mil", 50_000_000, True),
        ("500k", 50_000_000, True),
        ("R$ 500.000", 50_000_000, False),
        ("uns 500 mil", 50_000_000, True),
        ("1,5 milhao", 150_000_000, True),
        ("2 milhoes", 200_000_000, True),
        ("500", 50_000, False),
        ("cerca de 800 mil reais", 80_000_000, True),
    ],
)
def test_valor_unico(texto, centavos, tinha_marcador):
    assert _valor_de(texto) == _Valor(centavos=centavos, tinha_marcador=tinha_marcador)


@pytest.mark.parametrize("texto", ["", "o que der", "quinhentos mil", "sei la"])
def test_sem_numero_devolve_none(texto):
    """A gramatica e lista fixa: numero por extenso nao e resolvido, e isso e
    lacuna declarada da spec, nao bug."""
    assert _valor_de(texto) is None


def test_ponto_e_milhar_virgula_e_decimal():
    assert _valor_de("500.000").centavos == 50_000_000
    assert _valor_de("1,5").centavos == 150
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.agente.dinheiro'`

- [ ] **Step 3: Implementação mínima**

Crie `src/mobia/domain/agente/dinheiro.py`:

```python
"""Resolve expressao monetaria em lingua natural para centavos.

TEC-146. Puro de proposito: sem I/O, sem banco, sem chamada ao modelo. Quem
decide a ordem de grandeza e este modulo, e nao o modelo -- ver D1 do desenho.
A gramatica e lista fixa e erra por falta; estende-la e decisao de card, nao
de quem passa por aqui.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Ruido que nao carrega valor. Sai antes de qualquer parsing para que
# "uns 500 mil" e "500 mil" sigam o mesmo caminho.
_RUIDO = re.compile(
    r"\b(r\$|reais?|uns?|umas?|cerca de|por volta de|mais ou menos|em torno de)\b"
)

# `\b` separa "mil" de "milhao": sem ele o primeiro padrao comeria o prefixo do
# segundo e "1 milhao" viraria mil.
_MULTIPLICADORES: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"\b(milhao|milhoes|milhões|milhão|mi)\b"), Decimal(1_000_000)),
    (re.compile(r"\b(mil|k)\b"), Decimal(1_000)),
)

_NUMERO = re.compile(r"\d[\d.]*(?:,\d+)?")


@dataclass(frozen=True)
class _Valor:
    """Um valor resolvido, e se a fala trazia marcador de grandeza.

    `tinha_marcador` nao e curiosidade: e o que separa "uns 500" (ambiguo) de
    "500 mil" (claro) na banda da Task 3. Um numero nu abaixo do piso quase
    certamente quis dizer outra coisa.
    """

    centavos: int
    tinha_marcador: bool


def _decimal_de(bruto: str) -> Decimal | None:
    """Ponto e separador de milhar; virgula e decimal. Convencao pt-BR."""
    try:
        return Decimal(bruto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _valor_de(texto: str) -> _Valor | None:
    limpo = _RUIDO.sub(" ", texto.casefold())
    achado = _NUMERO.search(limpo)
    if achado is None:
        return None

    valor = _decimal_de(achado.group())
    if valor is None:
        return None

    # O marcador vale se aparecer DEPOIS do numero: "500 mil" multiplica,
    # "mil e quinhentos reais de condominio, imovel de 500" nao.
    resto = limpo[achado.end() :]
    tinha_marcador = False
    for padrao, fator in _MULTIPLICADORES:
        if padrao.search(resto):
            valor *= fator
            tinha_marcador = True
            break

    centavos = (valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return _Valor(centavos=int(centavos), tinha_marcador=tinha_marcador)
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v`
Expected: PASS, 13 testes.

- [ ] **Step 5: Lint e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/dinheiro.py tests/unit/test_dinheiro.py
git commit -m "feat(TEC-146): o nucleo do parser resolve valor unico em centavos"
```

---

## Task 2: Direção e faixa

**Files:**
- Modify: `src/mobia/domain/agente/dinheiro.py`
- Test: `tests/unit/test_dinheiro.py`

**Interfaces:**
- Consumes: `_Valor`, `_valor_de` da Task 1.
- Produces: `FaixaDePreco(min_centavos: int | None, max_centavos: int | None)` e `_faixa_de(expressao: str) -> FaixaDePreco | None`. `FaixaDePreco` é público — a Task 3 e o `extrair` da Task 4 o consomem.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/unit/test_dinheiro.py`:

```python
from mobia.domain.agente.dinheiro import FaixaDePreco, _faixa_de


@pytest.mark.parametrize(
    ("expressao", "minimo", "maximo"),
    [
        ("uns 500 mil", None, 50_000_000),
        ("ate 500 mil", None, 50_000_000),
        ("no maximo 500 mil", None, 50_000_000),
        ("a partir de 300 mil", 30_000_000, None),
        ("no minimo 300 mil", 30_000_000, None),
        ("acima de 300 mil", 30_000_000, None),
        ("entre 400 e 500 mil", 40_000_000, 50_000_000),
        ("de 300 a 450 mil", 30_000_000, 45_000_000),
        ("300 a 450 mil", 30_000_000, 45_000_000),
    ],
)
def test_direcao_e_faixa(expressao, minimo, maximo):
    assert _faixa_de(expressao) == FaixaDePreco(min_centavos=minimo, max_centavos=maximo)


def test_marcador_final_distribui_para_os_dois_lados():
    """A regra que a D2 do desenho protege: em "entre 400 e 500 mil" o `mil`
    vale para os dois. E o motivo de o modelo devolver a faixa inteira em vez
    de partir os limites -- partir e decisao de normalizacao."""
    assert _faixa_de("entre 400 e 500 mil") == FaixaDePreco(
        min_centavos=40_000_000, max_centavos=50_000_000
    )


def test_cada_lado_com_seu_proprio_marcador():
    assert _faixa_de("de 800 mil a 1,2 milhao") == FaixaDePreco(
        min_centavos=80_000_000, max_centavos=120_000_000
    )


def test_faixa_sem_numero_nenhum_devolve_none():
    assert _faixa_de("o que der") is None
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v`
Expected: FAIL com `ImportError: cannot import name 'FaixaDePreco'`

- [ ] **Step 3: Implementação mínima**

Acrescente a `src/mobia/domain/agente/dinheiro.py`:

```python
# Preposicoes que abrem faixa. "de X a Y" e "entre X e Y" sao as duas formas
# que o corpus da TEC-145 traz; "X a Y" e a mesma coisa sem a abertura.
_FAIXA = re.compile(r"(?:entre\s+)?(.+?)\s+(?:a|e|ate)\s+(.+)", re.DOTALL)

_SO_MAXIMO = re.compile(r"\b(ate|no maximo|maximo|abaixo de|menos de)\b")
_SO_MINIMO = re.compile(r"\b(a partir de|no minimo|minimo|acima de|mais de)\b")


@dataclass(frozen=True)
class FaixaDePreco:
    """Faixa resolvida. Extremo nulo e faixa aberta daquele lado."""

    min_centavos: int | None = None
    max_centavos: int | None = None


def _faixa_de(expressao: str) -> FaixaDePreco | None:
    limpo = expressao.casefold()

    # Direcao antes de faixa: "ate 500 mil" casaria em `_FAIXA` pelo "ate",
    # com o lado esquerdo vazio. Testar a direcao primeiro evita o falso par.
    if _SO_MINIMO.search(limpo):
        valor = _valor_de(limpo)
        return None if valor is None else FaixaDePreco(min_centavos=valor.centavos)
    if _SO_MAXIMO.search(limpo):
        valor = _valor_de(limpo)
        return None if valor is None else FaixaDePreco(max_centavos=valor.centavos)

    par = _FAIXA.match(limpo)
    if par is not None:
        esquerda, direita = _valor_de(par.group(1)), _valor_de(par.group(2))
        if esquerda is not None and direita is not None:
            # O marcador do lado direito distribui para a esquerda quando o
            # esquerdo nao tem o seu: "entre 400 e 500 mil" sao 400 MIL e 500
            # mil, nao 400 reais e 500 mil.
            minimo = esquerda.centavos
            if not esquerda.tinha_marcador and direita.tinha_marcador:
                proporcao = direita.centavos // _valor_de(par.group(2).replace("mil", "").replace("milhao", "")).centavos
                minimo = esquerda.centavos * proporcao
            return FaixaDePreco(min_centavos=minimo, max_centavos=direita.centavos)

    valor = _valor_de(limpo)
    return None if valor is None else FaixaDePreco(max_centavos=valor.centavos)
```

> **Nota para quem implementa:** o cálculo de `proporcao` acima é a forma ingênua e **vai falhar** em `"de 800 mil a 1,2 milhao"`, onde os dois lados têm marcador próprio. Faça o teste `test_cada_lado_com_seu_proprio_marcador` passar reescrevendo a distribuição: extraia o multiplicador aplicado em `_valor_de` devolvendo-o no `_Valor` (campo `fator: Decimal`), e aplique o fator da direita à esquerda só quando `not esquerda.tinha_marcador`. Não deixe a divisão por reconstrução de string no código final.

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v`
Expected: PASS. Se `test_cada_lado_com_seu_proprio_marcador` reprovar, aplique a nota do Step 3 antes de seguir.

- [ ] **Step 5: Lint e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests
git add src/mobia/domain/agente/dinheiro.py tests/unit/test_dinheiro.py
git commit -m "feat(TEC-146): direcao e faixa, com o marcador distribuindo para os dois lados"
```

---

## Task 3: A banda por intenção e os três motivos de recusa

**Files:**
- Modify: `src/mobia/domain/agente/dinheiro.py`
- Test: `tests/unit/test_dinheiro.py`

**Interfaces:**
- Consumes: `FaixaDePreco`, `_faixa_de` da Task 2; `Intencao` de `mobia.domain.agente.schemas`.
- Produces: `MotivoDaRecusa` (StrEnum: `AMBIGUA`, `IMPLAUSIVEL`, `ILEGIVEL`), `Recusa(motivo)`, e a função pública `parsear(expressao: str, intencao: Intencao) -> FaixaDePreco | Recusa`. É esta que a Task 4 chama.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `tests/unit/test_dinheiro.py`:

```python
from mobia.domain.agente.dinheiro import MotivoDaRecusa, Recusa, parsear
from mobia.domain.agente.schemas import Intencao


def test_expressao_clara_de_compra_e_aceita():
    assert parsear("uns 500 mil", Intencao.COMPRA) == FaixaDePreco(max_centavos=50_000_000)


def test_numero_nu_abaixo_do_piso_e_ambiguo():
    """O caso da card: "uns 500" para compra nao e R$ 500, e o sistema nao
    deve adivinhar qual e."""
    assert parsear("uns 500", Intencao.COMPRA) == Recusa(MotivoDaRecusa.AMBIGUA)


def test_magnitude_explicita_fora_da_banda_e_implausivel():
    assert parsear("2,5 milhoes", Intencao.ALUGUEL) == Recusa(MotivoDaRecusa.IMPLAUSIVEL)


def test_sem_numero_e_ilegivel():
    """ILEGIVEL mede o buraco da gramatica; os outros dois medem o lead."""
    assert parsear("quinhentos mil", Intencao.COMPRA) == Recusa(MotivoDaRecusa.ILEGIVEL)


def test_aluguel_aceita_valor_que_compra_recusaria():
    assert parsear("1500", Intencao.ALUGUEL) == FaixaDePreco(max_centavos=150_000)
    assert parsear("1500", Intencao.COMPRA) == Recusa(MotivoDaRecusa.AMBIGUA)


def test_indefinida_usa_a_uniao_das_bandas():
    assert parsear("1500", Intencao.INDEFINIDA) == FaixaDePreco(max_centavos=150_000)


def test_faixa_invertida_e_recusada():
    """D6 do desenho: faixa invertida e canario de bug do parser -- o caso
    mais provavel e o marcador ter se ligado ao lado errado. Reordenar em
    silencio calaria o sinal."""
    assert parsear("entre 500 e 400 mil", Intencao.COMPRA) == Recusa(
        MotivoDaRecusa.IMPLAUSIVEL
    )


def test_faixa_igual_nos_dois_lados_e_valida():
    obtido = parsear("exatamente 600 mil", Intencao.COMPRA)
    assert obtido == FaixaDePreco(max_centavos=60_000_000)
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v`
Expected: FAIL com `ImportError: cannot import name 'MotivoDaRecusa'`

- [ ] **Step 3: Implementação mínima**

Acrescente a `src/mobia/domain/agente/dinheiro.py`:

```python
from enum import StrEnum

from mobia.domain.agente.schemas import Intencao

# Bandas em centavos. Constantes de modulo, nao configuracao: a card pede
# configurabilidade para os PESOS DO SCORE (TEC-150), e nao diz nada sobre
# bandas de preco. Configuracao que ninguem pediu e superficie a mais.
_BANDA_DE_COMPRA = (3_000_000, 100_000_000_000)      # R$ 30 mil a R$ 1 bilhao
_BANDA_DE_ALUGUEL = (30_000, 20_000_000)             # R$ 300 a R$ 200 mil

_BANDAS = {
    Intencao.COMPRA: _BANDA_DE_COMPRA,
    Intencao.INVESTIMENTO: _BANDA_DE_COMPRA,
    Intencao.VENDER_IMOVEL: _BANDA_DE_COMPRA,
    Intencao.ALUGUEL: _BANDA_DE_ALUGUEL,
}

# Uniao das duas: na duvida, aceita. Fechar a banda para o lead ainda nao
# classificado custaria valores de aluguel legitimos, que sao a maioria dos
# valores baixos. Lacuna declarada no desenho.
_BANDA_FROUXA = (
    min(_BANDA_DE_COMPRA[0], _BANDA_DE_ALUGUEL[0]),
    max(_BANDA_DE_COMPRA[1], _BANDA_DE_ALUGUEL[1]),
)


class MotivoDaRecusa(StrEnum):
    """Tres motivos porque mandam quem investiga para lados diferentes.

    AMBIGUA e IMPLAUSIVEL dizem que o LEAD foi impreciso; ILEGIVEL diz que o
    PARSER nao deu conta. Um pico de ILEGIVEL e trabalho para a proxima card
    da gramatica; um pico de AMBIGUA e sinal sobre como os leads deste
    produto falam de dinheiro.
    """

    AMBIGUA = "AMBIGUA"
    IMPLAUSIVEL = "IMPLAUSIVEL"
    ILEGIVEL = "ILEGIVEL"


@dataclass(frozen=True)
class Recusa:
    motivo: MotivoDaRecusa


def parsear(expressao: str, intencao: Intencao) -> FaixaDePreco | Recusa:
    """Resolve a expressao, ou recusa com motivo. Nunca levanta.

    Chamador com `expressao` nula nao chega aqui: nao ha o que parsear, nada e
    gravado e nada e logado. E o turno comum, que nao fala de orcamento.
    """
    faixa = _faixa_de(expressao)
    if faixa is None:
        return Recusa(MotivoDaRecusa.ILEGIVEL)

    piso, teto = _BANDAS.get(intencao, _BANDA_FROUXA)
    extremos = [v for v in (faixa.min_centavos, faixa.max_centavos) if v is not None]

    # Invertida antes da banda: os dois extremos podem estar dentro dela e
    # ainda assim a faixa nao fazer sentido.
    if (
        faixa.min_centavos is not None
        and faixa.max_centavos is not None
        and faixa.min_centavos > faixa.max_centavos
    ):
        return Recusa(MotivoDaRecusa.IMPLAUSIVEL)

    for valor in extremos:
        if valor > teto:
            return Recusa(MotivoDaRecusa.IMPLAUSIVEL)
        if valor < piso:
            # Numero nu abaixo do piso e ambiguo, nao implausivel: o lead
            # quase certamente disse outra coisa. Com marcador explicito, ele
            # disse algo que nao fecha com a intencao.
            return Recusa(
                MotivoDaRecusa.AMBIGUA
                if not _tinha_marcador(expressao)
                else MotivoDaRecusa.IMPLAUSIVEL
            )

    return faixa


def _tinha_marcador(expressao: str) -> bool:
    limpo = expressao.casefold()
    return any(padrao.search(limpo) for padrao, _ in _MULTIPLICADORES)
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_dinheiro.py -v`
Expected: PASS, todos os testes das Tasks 1 a 3.

- [ ] **Step 5: Lint, tipos e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/dinheiro.py tests/unit/test_dinheiro.py
git commit -m "feat(TEC-146): banda por intencao, e tres motivos de recusa que apontam para lados diferentes"
```

---

## Task 4: O schema pede a expressão, e `extrair` chama o parser

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py:241-242`
- Modify: `src/mobia/domain/agente/classificador.py` — `SCHEMA_DA_EXTRACAO`, `extrair`, e remoção de `_preco` / `PRECO_MINIMO` / `PRECO_MAXIMO`
- Test: `tests/unit/test_extracao.py`

**Interfaces:**
- Consumes: `parsear`, `FaixaDePreco`, `Recusa`, `MotivoDaRecusa` da Task 3.
- Produces: `Extracao.faixa_preco_min_centavos: int | None` e `Extracao.faixa_preco_max_centavos: int | None`. A Task 5 (modelo) e a Task 6 (repositório e eval) dependem exatamente destes dois nomes.

> **Esta task é a que libera orçamento de prompt.** Dois campos `number` saem do schema compilado e um `string` entra. Meça antes e depois — a Task 7 depende do que sobrar.

- [ ] **Step 1: Medir o orçamento ANTES**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Anote a linha `margem`. Em 2026-09-01 ela era **13,0**.

- [ ] **Step 2: Escrever os testes que falham**

Em `tests/unit/test_extracao.py`, substitua `test_preco_guarda_precisao_de_decimal`, `test_preco_fora_da_faixa_e_descartado`, `test_faixa_invertida_descarta_os_dois_precos` e `test_faixa_igual_nos_dois_lados_e_valida` por:

```python
def test_expressao_de_preco_vira_centavos():
    obtido = extrair({"faixa_preco_expressao": "uns 600 mil"}, Intencao.COMPRA)
    assert obtido.faixa_preco_max_centavos == 60_000_000
    assert obtido.faixa_preco_min_centavos is None


def test_expressao_ambigua_nao_grava_nada_e_nao_mata_os_outros_campos():
    """O defeito que esta card conserta: antes, "uns 500" virava R$ 500 em
    silencio e ia para o filtro de busca."""
    obtido = extrair({"faixa_preco_expressao": "uns 500", "quartos": 2}, Intencao.COMPRA)
    assert obtido == Extracao(quartos=2)


def test_faixa_invertida_continua_descartada():
    """D6: canario de bug do parser. Reordenar em silencio calaria o sinal."""
    obtido = extrair(
        {"faixa_preco_expressao": "entre 500 e 400 mil", "quartos": 2}, Intencao.COMPRA
    )
    assert obtido == Extracao(quartos=2)


def test_expressao_nula_nao_e_recusa():
    assert extrair({"faixa_preco_expressao": None, "quartos": 2}, Intencao.COMPRA) == Extracao(
        quartos=2
    )
```

E atualize `test_extrair_de_dicionario_completo` para usar `"faixa_preco_expressao": "600 mil"` no lugar dos dois campos numéricos, esperando `faixa_preco_max_centavos=60_000_000`.

- [ ] **Step 3: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py -v`
Expected: FAIL com `TypeError: extrair() takes 1 positional argument but 2 were given`

- [ ] **Step 4: Implementar**

Em `schemas.py`, troque os dois campos de `Extracao`:

```python
    faixa_preco_min_centavos: int | None = None
    faixa_preco_max_centavos: int | None = None
```

Em `classificador.py`, no `SCHEMA_DA_EXTRACAO`, remova `faixa_preco_min` e `faixa_preco_max` de `properties` e de `required`, e acrescente em ambos:

```python
        "faixa_preco_expressao": _anulavel({"type": "string"}),
```

Remova `PRECO_MINIMO`, `PRECO_MAXIMO` e a função `_preco` — a faixa agora é a banda do `dinheiro.py`. Reescreva a cabeça de `extrair`:

```python
def extrair(bruto: Any, intencao: Intencao) -> Extracao:
    """Converte o objeto `extracao` do modelo, descartando o que nao serve.

    **Nunca levanta.** A extracao viaja na mesma chamada que a resposta ao
    lead, e um numero malformado nao pode matar uma resposta entregavel:
    extracao e enriquecimento, a resposta e o produto.

    `intencao` entra desde a TEC-146: a banda de plausibilidade do preco
    depende dela -- R$ 1.500 e aluguel corriqueiro e preco de compra absurdo.
    """
    if not isinstance(bruto, dict):
        return Extracao()

    minimo = maximo = None
    expressao = bruto.get("faixa_preco_expressao")
    if isinstance(expressao, str) and expressao.strip():
        resultado = parsear(expressao, intencao)
        if isinstance(resultado, Recusa):
            log.info("extracao.preco_recusado", motivo=resultado.motivo.value)
        else:
            minimo, maximo = resultado.min_centavos, resultado.max_centavos

    return Extracao(
        faixa_preco_min_centavos=minimo,
        faixa_preco_max_centavos=maximo,
        regiao=_regiao(bruto.get("regiao")),
        ...  # o resto dos campos segue inalterado
    )
```

Atualize o chamador de `extrair` no mesmo módulo para passar a intenção já classificada.

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py tests/unit/test_dinheiro.py -v`
Expected: PASS

- [ ] **Step 6: Medir o orçamento DEPOIS, e anotar o ganho**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
A margem deve ter **subido** — dois campos saíram do schema compilado e um entrou. Anote o número; a Task 7 gasta dele. Se ela tiver caído, pare: alguma coisa entrou no schema sem estar no plano.

- [ ] **Step 7: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/ tests/unit/test_extracao.py
git commit -m "feat(TEC-146): o modelo devolve a expressao, e o inteiro passa a ser do codigo"
```

---

## Task 5: Migração `0011` e o modelo

**Files:**
- Create: `alembic/versions/0011_preco_em_centavos.py`
- Modify: `src/mobia/domain/context/models.py:84-85`
- Test: `tests/integration/test_repositorio_contexto.py`

**Interfaces:**
- Consumes: os nomes `faixa_preco_min_centavos` / `faixa_preco_max_centavos` da Task 4.
- Produces: colunas `BigInteger` de mesmo nome em `lead_qualification`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_repositorio_contexto.py`, acrescente:

```python
async def test_preco_em_centavos_sobrevive_ao_round_trip(session):
    """BigInteger e nao Integer: 10^11 centavos (R$ 1 bilhao, o teto da banda)
    estoura int32, que para em ~2,1x10^9 -- R$ 21 milhoes."""
    await gravar_estado(
        session,
        channel="whatsapp",
        conversation_key="5511999999999",
        intencao=Intencao.COMPRA,
        extracao=Extracao(faixa_preco_max_centavos=100_000_000_000),
    )
    estado = await ler_estado(session, channel="whatsapp", conversation_key="5511999999999")
    assert estado.faixa_preco_max_centavos == 100_000_000_000
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_contexto.py -v`
Expected: FAIL — a coluna não existe.

- [ ] **Step 3: Escrever a migração**

Crie `alembic/versions/0011_preco_em_centavos.py`:

```python
"""preco em centavos, como inteiro

TEC-146. `numeric(12,2)` guardava reais e deixava a ordem de grandeza a cargo
do modelo. Centavos como inteiro tiram a virgula da conta e fecham a RN-05.6.

BIGINT e nao INTEGER: o teto da banda de compra e R$ 1 bilhao, ou 10^11
centavos. `int32` para em ~2,1x10^9 -- R$ 21 milhoes -- e truncaria a faixa
que ja existe.

O backfill e lossless por construcao, nao por sorte: `numeric(12,2) * 100` e
inteiro exato, entao o ROUND nunca tem o que arredondar.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_min_centavos", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_max_centavos", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE lead_qualification SET "
        "faixa_preco_min_centavos = ROUND(faixa_preco_min * 100)::bigint, "
        "faixa_preco_max_centavos = ROUND(faixa_preco_max * 100)::bigint"
    )
    op.drop_column("lead_qualification", "faixa_preco_min")
    op.drop_column("lead_qualification", "faixa_preco_max")


def downgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_min", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_max", sa.Numeric(12, 2), nullable=True),
    )
    # Cabe para todo valor dentro da banda da D3; fora dela nada e gravavel.
    op.execute(
        "UPDATE lead_qualification SET "
        "faixa_preco_min = faixa_preco_min_centavos / 100.0, "
        "faixa_preco_max = faixa_preco_max_centavos / 100.0"
    )
    op.drop_column("lead_qualification", "faixa_preco_min_centavos")
    op.drop_column("lead_qualification", "faixa_preco_max_centavos")
```

Em `models.py`, troque as duas linhas:

```python
    faixa_preco_min_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    faixa_preco_max_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

Acrescente `BigInteger` ao import de `sqlalchemy` e remova `Numeric` se ficar sem uso.

- [ ] **Step 4: Rodar a migração e o teste**

```bash
docker compose up -d
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_contexto.py -v
```
Expected: PASS

- [ ] **Step 5: Conferir que o downgrade volta**

```bash
./.venv/Scripts/python.exe -m alembic downgrade 0010
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: as duas direções sem erro.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0011_preco_em_centavos.py src/mobia/domain/context/models.py tests/integration/test_repositorio_contexto.py
git commit -m "feat(TEC-146): migracao 0011, preco em centavos com backfill lossless"
```

---

## Task 6: Integração — corpus, runner do eval e montagem

**Files:**
- Modify: `src/mobia/evals/corpus.py` — `_turno_de`
- Test: `tests/unit/test_evals_corpus.py`, `tests/integration/test_extracao_no_turno.py`, `tests/integration/test_montagem.py`

**Interfaces:**
- Consumes: os nomes de campo da Task 4.
- Produces: nada novo. Fecha os consumidores.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/unit/test_evals_corpus.py`:

```python
def test_corpus_anota_reais_e_carrega_centavos(tmp_path):
    """D7: a anotacao continua legivel para humanos. 50000000 no YAML convida
    ao zero a mais de quem adicionar caso novo, e um erro desses num corpus
    que e o baseline medido da TEC-145 aparece como regressao de acuracia que
    ninguem atribui a esta migracao."""
    turno = _turno_de(
        {"lead": "ate 500 mil", "intencao": "COMPRA", "campos": {"faixa_preco_max": 500000}},
        "compra-01",
        "compra.yaml",
    )
    assert turno.campos == {"faixa_preco_max_centavos": 50_000_000}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus.py -v`
Expected: FAIL — a chave sai como `faixa_preco_max`.

- [ ] **Step 3: Implementar a conversão no carregador**

Em `src/mobia/evals/corpus.py`, dentro de `_turno_de`, no laço `for nome, valor in campos_brutos.items()`, acrescente:

```python
# TEC-146. A anotacao fica em reais porque e artefato humano; o banco guarda
# centavos. A conversao mora aqui, no unico ponto em que o corpus vira dado,
# para nao haver duas unidades circulando no runner.
_EM_REAIS = {"faixa_preco_min": "faixa_preco_min_centavos",
             "faixa_preco_max": "faixa_preco_max_centavos"}
```

e no laço, troque nome e valor quando `nome in _EM_REAIS`, gravando `int(valor) * 100` sob o nome novo.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte inteira e fechar os consumidores restantes**

Run: `./.venv/Scripts/python.exe -m pytest`
Corrija `test_extracao_no_turno.py`, `test_montagem.py`, `test_evals_reperguntas.py` e `test_evals_metricas.py` onde citarem os nomes antigos. **Não mexa em `evals/corpus/*.yaml`** — a anotação fica em reais por decisão da D7.

- [ ] **Step 6: Commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests
./.venv/Scripts/python.exe -m mypy
git add src/mobia/evals/corpus.py tests/
git commit -m "feat(TEC-146): o corpus segue em reais, e a conversao mora no carregador"
```

---

## Task 7: A regra da banda no prompt

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py` — `SISTEMA_DO_AGENTE`
- Test: `tests/unit/test_config.py` (margem), `tests/integration/test_montagem.py`

**Interfaces:**
- Consumes: a margem liberada pela Task 4.
- Produces: nada em código. Fecha a D4.

> **Esta é a camada de economia, não a de correção.** O código da Task 4 já garante que valor ambíguo não é gravado. Se esta task não couber no orçamento, a card ainda está correta — só mais cara em reperguntas.

- [ ] **Step 1: Medir a margem disponível**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Anote. O texto do Step 3 custa ~10,25 tokens no proxy `len/4`.

- [ ] **Step 2: Escrever o teste que falha**

Em `tests/integration/test_montagem.py`:

```python
def test_o_prompt_manda_confirmar_orcamento_vago():
    """D4: o codigo e a correcao (nao grava), o prompt e a economia (pergunta
    no mesmo turno). A camada que garante nao pode depender da que lembra."""
    assert "orcamento vago" in SISTEMA_DO_AGENTE
```

- [ ] **Step 3: Acrescentar a frase mais curta que faz o serviço**

Ao final de `SISTEMA_DO_AGENTE`, antes do fechamento do parêntese:

```python
    " Orcamento vago: peca confirmacao."
```

Trinta e quatro caracteres, ~8,5 tokens no proxy. Redigido curto de propósito: a cláusula longa (*"Se o valor de orçamento não trouxer ordem de grandeza clara, peça confirmação ao lead"*) custa ~21 tokens e não caberia.

- [ ] **Step 4: Rodar a margem e o teste**

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py -v
```
Expected: PASS nos dois.

**Se `test_a_margem_do_orcamento_do_prompt_e_deliberada` reprovar:** a pergunta é *"o que sai do prompt para este texto entrar?"*, não *"quanto subo o 655?"*. Subir é resposta legítima, mas só depois da primeira pergunta, e o histórico dos aumentos anteriores fica na docstring do teste. Registre a decisão no comentário acima de `SISTEMA_DO_AGENTE`, como as cards anteriores fizeram.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `./.venv/Scripts/python.exe -m pytest`
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/agente/classificador.py tests/
git commit -m "feat(TEC-146): o prompt pede confirmacao de orcamento vago, e o codigo continua garantindo"
```

---

## Auto-revisão

**Cobertura da spec.** D1 → Task 4. D2 → Task 2 (`test_marcador_final_distribui_para_os_dois_lados`). D3 → Task 3. D4 → Task 4 (código garante) + Task 7 (prompt pede). D5 → Task 5. D6 → Task 3 (`test_faixa_invertida_e_recusada`) e Task 4 (`test_faixa_invertida_continua_descartada`). D7 → Task 6. Fluxo, gramática e testes da spec estão distribuídos pelas sete tasks. Sem lacuna.

**Consistência de tipos.** `FaixaDePreco(min_centavos, max_centavos)` nasce na Task 2 e é consumido com os mesmos nomes nas Tasks 3 e 4. `parsear(expressao, intencao) -> FaixaDePreco | Recusa` nasce na Task 3 e é chamado com essa assinatura na Task 4. `Extracao.faixa_preco_min_centavos` / `_max_centavos` nascem na Task 4 e são consumidos com esses nomes nas Tasks 5 e 6. `extrair` ganha o segundo parâmetro na Task 4, e a Task 4 atualiza o chamador junto.

**Risco conhecido, e onde ele mora.** A distribuição do marcador na Task 2 tem implementação ingênua no Step 3, com nota explícita mandando reescrevê-la para passar `test_cada_lado_com_seu_proprio_marcador`. É deliberado: o teste vem antes e define a forma certa. Quem executar não deve deixar a divisão por reconstrução de string no código final.

# TEC-153 — A trilha do investidor: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A intenção `INVESTIMENTO` passa a ativar um subagente com prompt e campos próprios, o perfil do investidor é classificado por regra determinística, e o ticket decide qual especialidade de corretor o lead exige.

**Architecture:** Um schema e um prompt próprios do investidor, usados numa segunda chamada ao modelo **apenas no turno em que a intenção vira `INVESTIMENTO`** e num prompt trocado nos turnos seguintes. As regras — perfil, especialidade, ticket — são funções puras em módulos sem I/O, testáveis sem banco e sem modelo. Os campos persistem em colunas novas de `lead_qualification`.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, Postgres, Anthropic API, pytest/pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-153-trilha-do-investidor-design.md`

## Global Constraints

- **Os três gates do CI, nesta ordem, antes de qualquer commit.** `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`; `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`; `./.venv/Scripts/python.exe -m mypy`. **O formatador é um gate separado do linter — passar num não diz nada sobre o outro.**
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **O orçamento do prompt é medido e tem ritual.** Antes e depois de qualquer mudança em prompt ou schema: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`. **O schema compilado é uma das quatro parcelas.** `SCHEMA_DO_INVESTIDOR` **não** pode entrar em `SCHEMA_DA_RESPOSTA` — é dessa separação que depende o custo zero para quem não é investidor (D2 do spec). Se o teste reprovar, a pergunta é "o que sai para o novo texto entrar?", nunca "quanto subo o número?".
- **Loop de teste:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4s, sem Docker, sem `-n`). Suíte inteira, uma vez no fim: `-n 8 --dist loadfile --tb=short`.
- `tests/integration` exige `docker compose` de pé. O `ConnectionResetError [WinError 64]` acontece em rajadas e não é do seu código — rode de novo antes de investigar.
- Nunca `-q` sem `--tb=short`.
- **Mensagem de commit:** use **heredoc** (`git commit -F - <<'EOF'`), **nunca** here-string do PowerShell (`@'...'@`) — a ferramenta Bash é Git Bash e aquilo corrompe a mensagem em silêncio. Assunto `tipo(TEC-153): o que passou a ser verdade`, português sem acento, linha em branco antes do trailer, e termine com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Confira com `git log -1 --format=%s`.
- Antes do PR: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`.

---

### Task 1: As colunas do investidor

**Files:**
- Create: `alembic/versions/0033_trilha_do_investidor.py`
- Modify: `src/mobia/domain/context/models.py` (`LeadQualification`, abaixo de `perguntas_feitas`)
- Test: `tests/integration/test_migracao_investidor.py`

**Interfaces:**
- Produces: sete colunas nuláveis em `lead_qualification` — `ticket_investimento_centavos` (BigInteger), `retorno_esperado_pct` (Numeric(4,2)), `retorno_esperado_tipo` (String(16)), `horizonte` (String(16)), `tolerancia_reforma` (String(16)), `ja_investe_em_imoveis` (Boolean), `perfil_investidor` (String(16)).

- [ ] **Step 1: Escreva o teste que falha**

`tests/integration/test_migracao_investidor.py` — basename distinto de tudo em `tests/unit/` e `tests/perf/`:

```python
"""A `0033` acrescenta os campos da RN-05.2 e da RN-07.2. TEC-153."""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker

ESPERADAS = {
    "ticket_investimento_centavos": "bigint",
    "retorno_esperado_pct": "numeric",
    "retorno_esperado_tipo": "text",
    "horizonte": "text",
    "tolerancia_reforma": "text",
    "ja_investe_em_imoveis": "boolean",
    "perfil_investidor": "text",
}


async def test_as_colunas_do_investidor_existem_e_sao_nulaveis() -> None:
    """Nulaveis pela mesma razao das vizinhas: qualificacao e progressiva, e
    campo ausente e o estado normal, nao um defeito."""
    async with get_sessionmaker()() as session:
        resultado = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "  FROM information_schema.columns "
                " WHERE table_name = 'lead_qualification' "
                "   AND column_name = ANY(:nomes)"
            ),
            {"nomes": list(ESPERADAS)},
        )
        colunas = {linha.column_name: linha for linha in resultado}

    assert set(colunas) == set(ESPERADAS)
    for nome, tipo in ESPERADAS.items():
        assert colunas[nome].data_type.startswith(tipo), f"{nome}: {colunas[nome].data_type}"
        assert colunas[nome].is_nullable == "YES"
```

Nota: `String(16)` do SQLAlchemy vira `character varying` no Postgres, não `text`. Se o teste reprovar por isso, **ajuste o valor esperado no teste para o tipo real** — não troque a coluna para `Text` só para o teste passar. `String(16)` é o que limita a grafia de um enum.

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_migracao_investidor.py -v --tb=short`
Expected: FAIL — `assert set(colunas) == set(ESPERADAS)`, com `colunas` vazio.

- [ ] **Step 3: A migration**

`alembic/versions/0033_trilha_do_investidor.py`, com `revision = "0033"` e `down_revision = "0032"`. O docstring explica o porquê, não o quê:

```python
r"""os campos de qualificacao do investidor

TEC-153, RN-05.2 e RN-07.2. Sete colunas nulaveis em `lead_qualification`, e
nao tabela nova: e o mesmo lead, o mesmo momento do turno e o mesmo ciclo de
vida das colunas vizinhas. Tabela separada exigiria join para responder "o
que sabemos deste lead" e entraria no TRUNCATE de todo teste que toca banco.

Tres destas colunas -- `horizonte`, `tolerancia_reforma`,
`ja_investe_em_imoveis` -- nao estao no dicionario de dados do SRS, embora a
RN-05.2 as nomeie. Ver a Emenda E-02 da RN-05.2.

`retorno_esperado_tipo` nao existe no SRS de forma nenhuma: e o campo
QUALITATIVO que a RN-07.2 pressupoe sem nomear, porque `retorno_esperado_pct`
sozinho nao separa renda de valorizacao -- 8% ao ano descreve os dois. Ver a
Emenda E-01 da RN-07.2.

`perfil_investidor` e DERIVADO (`perfil_de`, em `context/qualificacao.py`) e
gravado, nao calculado na leitura: quem le o lead precisa do perfil sem
reexecutar a regra, e a TEC-154 vai le-lo direto.

Revision ID: 0033
Revises: 0032
"""

import sqlalchemy as sa

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

_COLUNAS = (
    sa.Column("ticket_investimento_centavos", sa.BigInteger(), nullable=True),
    sa.Column("retorno_esperado_pct", sa.Numeric(4, 2), nullable=True),
    sa.Column("retorno_esperado_tipo", sa.String(16), nullable=True),
    sa.Column("horizonte", sa.String(16), nullable=True),
    sa.Column("tolerancia_reforma", sa.String(16), nullable=True),
    sa.Column("ja_investe_em_imoveis", sa.Boolean(), nullable=True),
    sa.Column("perfil_investidor", sa.String(16), nullable=True),
)


def upgrade() -> None:
    for coluna in _COLUNAS:
        op.add_column("lead_qualification", coluna)


def downgrade() -> None:
    for coluna in reversed(_COLUNAS):
        op.drop_column("lead_qualification", coluna.name)
```

- [ ] **Step 4: As colunas no modelo**

Em `LeadQualification`, abaixo de `perguntas_feitas`, com comentário explicando o porquê de cada grupo (siga a densidade do arquivo — toda coluna dele carrega um comentário de razão). Importe `Numeric` do `sqlalchemy` junto dos demais, em ordem alfabética.

```python
    # TEC-153, RN-05.2. Os campos que o subagente do investidor pergunta, e
    # que a trilha padrao nao tem onde guardar. Nulaveis pela mesma razao das
    # vizinhas: qualificacao e progressiva.
    ticket_investimento_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Centavos como todo dinheiro deste schema (RN-05.6), e `Numeric` para o
    # percentual porque ele e taxa, nao dinheiro: `numeric(4,2)` vem do
    # dicionario de dados do SRS.
    retorno_esperado_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    # O campo QUALITATIVO que a RN-07.2 pressupoe sem nomear. O percentual
    # acima nao separa renda de valorizacao -- e este que separa, e e ele que
    # `perfil_de` le. Ver a Emenda E-01 da RN-07.2.
    retorno_esperado_tipo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    horizonte: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tolerancia_reforma: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ja_investe_em_imoveis: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # DERIVADO de `horizonte` + `retorno_esperado_tipo` por `perfil_de`, e
    # gravado em vez de recalculado na leitura: a TEC-154 le o perfil direto.
    #
    # **NULL nao e MISTO.** NULL e "falta um dos dois campos, ainda nao sei";
    # MISTO e "sei, e os sinais se contradizem". Colapsar os dois faria a
    # TEC-154 exibir indicador de perfil para quem nunca respondeu.
    perfil_investidor: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

`Decimal` vem de `decimal`; acrescente o import se ele ainda não estiver no arquivo.

- [ ] **Step 5: Aplique e rode**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_migracao_investidor.py -v --tb=short
```

- [ ] **Step 6: Gates e commit**

Os três gates, depois commit com heredoc: `feat(TEC-153): lead_qualification ganha os campos do investidor`.

---

### Task 2: O vocabulário do investidor

**Files:**
- Create: `src/mobia/domain/agente/investidor.py`
- Test: `tests/unit/test_vocabulario_do_investidor.py`

**Interfaces:**
- Produces: `Horizonte` (CURTO/MEDIO/LONGO), `RetornoEsperadoTipo` (ALUGUEL/REVENDA/AMBOS), `ToleranciaReforma` (NENHUMA/LEVE/PESADA), `PerfilInvestidor` (RENDA/VALORIZACAO/MISTO) — todos `StrEnum` —, o dataclass `ExtracaoDoInvestidor` e `CAMPOS_DO_INVESTIDOR: frozenset[str]`.

**Módulo novo, e não `schemas.py`:** `schemas.py` define o schema estrito da chamada principal, e a docstring de `Intencao` avisa que acrescentar membro ali muda o conjunto que o modelo pode devolver. O vocabulário do investidor não pertence àquela chamada.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O vocabulario da trilha do investidor. TEC-153, RN-05.2 e RN-07.2."""

import dataclasses

from mobia.domain.agente.investidor import (
    CAMPOS_DO_INVESTIDOR,
    ExtracaoDoInvestidor,
    Horizonte,
    PerfilInvestidor,
    RetornoEsperadoTipo,
)


def test_o_horizonte_tem_as_tres_faixas_da_rn_05_2() -> None:
    assert [h.value for h in Horizonte] == ["CURTO", "MEDIO", "LONGO"]


def test_o_tipo_de_retorno_separa_renda_de_valorizacao() -> None:
    """E o campo que o percentual nao consegue ser: 8% ao ano descreve tanto
    aluguel quanto revenda."""
    assert [t.value for t in RetornoEsperadoTipo] == ["ALUGUEL", "REVENDA", "AMBOS"]


def test_o_perfil_tem_os_tres_da_rn_07_2() -> None:
    assert [p.value for p in PerfilInvestidor] == ["RENDA", "VALORIZACAO", "MISTO"]


def test_a_extracao_do_investidor_nasce_toda_vazia() -> None:
    """Campo ausente e o estado normal da qualificacao progressiva."""
    vazia = ExtracaoDoInvestidor()
    assert all(getattr(vazia, campo.name) is None for campo in dataclasses.fields(vazia))


def test_campos_do_investidor_acompanha_o_dataclass() -> None:
    """Pinado contra o dataclass, e nao escrito a mao: uma segunda lista de
    nomes divergiria em silencio, que e o defeito que a TEC-146 gastou uma
    card inteira consertando."""
    assert CAMPOS_DO_INVESTIDOR == {campo.name for campo in dataclasses.fields(ExtracaoDoInvestidor)}
```

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_vocabulario_do_investidor.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.agente.investidor'`.

- [ ] **Step 3: Implemente**

`src/mobia/domain/agente/investidor.py`:

```python
"""O vocabulario da trilha do investidor. TEC-153, RN-05.2 e RN-07.2.

**Modulo proprio, e nao `schemas.py`.** Aquele arquivo define o schema
estrito da chamada principal, e o schema compilado e uma das quatro parcelas
do orcamento de prompt medido contra o teto fixo -- seis campos que a maioria
dos leads nunca preenche nao podem custar tokens a todos eles. O vocabulario
do investidor pertence a OUTRA chamada, e fica fora daquele schema de
proposito. Ver a D2 do desenho.

Sem I/O, como `handoff/vocabulario.py` e `corretores/vocabulario.py`: e o que
deixa a regra ser testada em `tests/unit/`, sem Postgres de pe.
"""

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Horizonte(StrEnum):
    """As faixas da RN-05.2. Faixas, nao datas -- o que importa e o prazo em
    que o dinheiro sai, nao a data em que o lead pensou nisso."""

    CURTO = "CURTO"
    MEDIO = "MEDIO"
    LONGO = "LONGO"


class RetornoEsperadoTipo(StrEnum):
    """O que o investidor espera COMO retorno, nao QUANTO.

    Este e o campo que a RN-07.2 pressupoe sem nomear. `retorno_esperado_pct`
    nao separa renda de valorizacao: 8% ao ano descreve os dois. Ver a Emenda
    E-01 da RN-07.2.
    """

    ALUGUEL = "ALUGUEL"
    REVENDA = "REVENDA"
    AMBOS = "AMBOS"


class ToleranciaReforma(StrEnum):
    NENHUMA = "NENHUMA"
    LEVE = "LEVE"
    PESADA = "PESADA"


class PerfilInvestidor(StrEnum):
    """Os tres da RN-07.2. Derivado por `perfil_de`, nunca informado pelo lead."""

    RENDA = "RENDA"
    VALORIZACAO = "VALORIZACAO"
    MISTO = "MISTO"


@dataclass(frozen=True, slots=True)
class ExtracaoDoInvestidor:
    """O que a chamada do subagente investidor devolve sobre a fala do lead.

    Frozen como `Extracao`, e todo campo nulavel: qualificacao e progressiva,
    e campo ausente e o estado normal, nao defeito.

    **`ticket_expressao` e `str`, nao `int`.** O modelo devolve o que o lead
    falou ("uns 800 mil") e quem normaliza e `ticket_de`, em `dinheiro.py` --
    o mesmo desenho que `faixa_preco_expressao` ja usa em `Extracao`. Pedir
    centavos ao modelo seria delegar a ele uma conversao que o codigo faz
    melhor e que precisa ser a mesma da trilha padrao.
    """

    ticket_expressao: str | None = None
    retorno_esperado_pct: Decimal | None = None
    retorno_esperado_tipo: RetornoEsperadoTipo | None = None
    horizonte: Horizonte | None = None
    tolerancia_reforma: ToleranciaReforma | None = None
    ja_investe_em_imoveis: bool | None = None


# Derivado do dataclass, nunca escrito a mao: uma segunda lista de nomes
# divergiria em silencio, que e o defeito que a TEC-146 gastou uma card
# inteira consertando. Quem le isto e `_marca_de`, para que a trilha do
# investidor conte no teto da RN-05.5 (TEC-149).
CAMPOS_DO_INVESTIDOR: frozenset[str] = frozenset(
    campo.name for campo in dataclasses.fields(ExtracaoDoInvestidor)
)
```

- [ ] **Step 4: Rode e veja passar** — 5 passed.
- [ ] **Step 5: Gates e commit** — `feat(TEC-153): o vocabulario do investidor ganha modulo proprio`.

---

### Task 3: A regra do perfil

**Files:**
- Modify: `src/mobia/domain/context/qualificacao.py`
- Test: `tests/unit/test_perfil_do_investidor.py`

**Interfaces:**
- Consumes: `Horizonte`, `RetornoEsperadoTipo`, `PerfilInvestidor` (Task 2).
- Produces: `perfil_de(horizonte, retorno_tipo) -> PerfilInvestidor | None`.

- [ ] **Step 1: Escreva o teste que falha**

Cubra **as nove células** da tabela da D4, mais os casos de ausência. A tabela:

| tipo \ horizonte | CURTO | MEDIO | LONGO |
|---|---|---|---|
| ALUGUEL | MISTO | RENDA | RENDA |
| REVENDA | VALORIZACAO | VALORIZACAO | MISTO |
| AMBOS | MISTO | MISTO | MISTO |

```python
"""O perfil do investidor da RN-07.2. TEC-153, D4."""

import pytest

from mobia.domain.agente.investidor import Horizonte, PerfilInvestidor, RetornoEsperadoTipo
from mobia.domain.context.qualificacao import perfil_de

RENDA, VALORIZACAO, MISTO = (
    PerfilInvestidor.RENDA,
    PerfilInvestidor.VALORIZACAO,
    PerfilInvestidor.MISTO,
)


@pytest.mark.parametrize(
    ("tipo", "horizonte", "esperado"),
    [
        (RetornoEsperadoTipo.ALUGUEL, Horizonte.CURTO, MISTO),
        (RetornoEsperadoTipo.ALUGUEL, Horizonte.MEDIO, RENDA),
        (RetornoEsperadoTipo.ALUGUEL, Horizonte.LONGO, RENDA),
        (RetornoEsperadoTipo.REVENDA, Horizonte.CURTO, VALORIZACAO),
        (RetornoEsperadoTipo.REVENDA, Horizonte.MEDIO, VALORIZACAO),
        (RetornoEsperadoTipo.REVENDA, Horizonte.LONGO, MISTO),
        (RetornoEsperadoTipo.AMBOS, Horizonte.CURTO, MISTO),
        (RetornoEsperadoTipo.AMBOS, Horizonte.MEDIO, MISTO),
        (RetornoEsperadoTipo.AMBOS, Horizonte.LONGO, MISTO),
    ],
)
def test_a_tabela_do_perfil(tipo, horizonte, esperado) -> None:
    assert perfil_de(horizonte, tipo) is esperado


def test_o_cenario_do_gherkin_e_renda() -> None:
    """"horizonte longo e expectativa de aluguel recorrente" -> RENDA."""
    assert perfil_de(Horizonte.LONGO, RetornoEsperadoTipo.ALUGUEL) is RENDA


def test_as_diagonais_discordantes_sao_misto() -> None:
    """"quero aluguel mas saio em um ano" e "quero revender mas fico dez anos"
    sao sinais que se contradizem. Escolher um deles seria chute."""
    assert perfil_de(Horizonte.CURTO, RetornoEsperadoTipo.ALUGUEL) is MISTO
    assert perfil_de(Horizonte.LONGO, RetornoEsperadoTipo.REVENDA) is MISTO


@pytest.mark.parametrize(
    ("horizonte", "tipo"),
    [
        (None, RetornoEsperadoTipo.ALUGUEL),
        (Horizonte.LONGO, None),
        (None, None),
    ],
)
def test_sem_um_dos_dois_o_perfil_e_none_e_nao_misto(horizonte, tipo) -> None:
    """NULL e "ainda nao sei"; MISTO e "sei, e e misto". Colapsar os dois faria
    a TEC-154 exibir indicador de perfil para quem nunca respondeu."""
    assert perfil_de(horizonte, tipo) is None
```

- [ ] **Step 2: Rode e veja falhar** — `ImportError: cannot import name 'perfil_de'`.

- [ ] **Step 3: Implemente**

Em `qualificacao.py`, no fim do módulo. Uma tabela `dict` de `(horizonte, tipo)` para perfil, e o retorno cedo `None` quando qualquer um dos dois falta. A docstring explica as duas diagonais e o `None` vs `MISTO`. **Acrescente ao docstring do módulo** que ele agora também hospeda a regra da RN-07.2 — o módulo já foi corrigido uma vez por ficar desatualizado por omissão.

- [ ] **Step 4: Rode e veja passar** — 15 passed.
- [ ] **Step 5: Gates e commit** — `feat(TEC-153): o perfil do investidor vira tabela deterministica`.

---

### Task 4: A especialidade por faixa de ticket

**Files:**
- Modify: `src/mobia/domain/corretores/vocabulario.py`
- Test: `tests/unit/test_especialidade_por_ticket.py`

**Interfaces:**
- Produces: `TICKET_DE_ALTO_TICKET_CENTAVOS: int` e `especialidade_de(ticket_centavos: int) -> Especialidade`.

- [ ] **Step 1: Escreva o teste que falha**

O Esquema de Cenário do Gherkin, mais a fronteira exata:

```python
"""O roteamento por faixa de ticket da RN-07.4. TEC-153, D5."""

import pytest

from mobia.domain.corretores.vocabulario import (
    TICKET_DE_ALTO_TICKET_CENTAVOS,
    Especialidade,
    especialidade_de,
)


def test_o_limiar_e_um_milhao_de_reais() -> None:
    """Pinado: e o numero da RN-07.4, e o unico lugar em que ele esta escrito."""
    assert TICKET_DE_ALTO_TICKET_CENTAVOS == 100_000_000


@pytest.mark.parametrize(
    ("ticket", "esperada"),
    [
        (80_000_000, Especialidade.INVESTIMENTO),
        (100_000_000, Especialidade.INVESTIMENTO_ALTO_TICKET),
        (250_000_000, Especialidade.INVESTIMENTO_ALTO_TICKET),
    ],
)
def test_o_esquema_de_cenario_da_card(ticket, esperada) -> None:
    assert especialidade_de(ticket) is esperada


def test_um_centavo_abaixo_do_limiar_ainda_e_investimento() -> None:
    """A RN-07.4 diz "a partir de", entao o limiar PERTENCE ao alto ticket. E
    a fronteira que o Esquema de Cenario nao exercita sozinho."""
    assert especialidade_de(TICKET_DE_ALTO_TICKET_CENTAVOS - 1) is Especialidade.INVESTIMENTO
```

- [ ] **Step 2: Rode e veja falhar** — `ImportError`.

- [ ] **Step 3: Implemente**

```python
# RN-07.4, em centavos como todo dinheiro deste dominio. O unico lugar em que
# este numero esta escrito.
#
# Constante de modulo e nao configuracao: a card fixa o valor e ninguem pediu
# configurabilidade -- superficie que ninguem pediu e superficie a mais, o
# mesmo argumento que as bandas de `dinheiro.py` usam.
TICKET_DE_ALTO_TICKET_CENTAVOS = 100_000_000


def especialidade_de(ticket_centavos: int) -> Especialidade:
    """A especialidade que o ticket exige. RN-07.4, TEC-153.

    `>=` e nao `>`: a regra diz "a partir de R$ 1.000.000", entao o limiar
    pertence ao alto ticket.

    **Nasce sem chamador, e isso e declarado.** Alocar corretor e a TEC-166, e
    a TEC-153 poe a alocacao fora de escopo -- o Gherkin dela diz "quando o
    corretor e alocado", um passo que ainda nao existe. E a mesma situacao em
    que `Gatilho.LIMITE_DE_PERGUNTAS` ficou desde a TEC-174 ate a TEC-149
    chegar: a regra existe, testada, esperando quem a chame.
    """
    if ticket_centavos >= TICKET_DE_ALTO_TICKET_CENTAVOS:
        return Especialidade.INVESTIMENTO_ALTO_TICKET
    return Especialidade.INVESTIMENTO
```

- [ ] **Step 4: Rode e veja passar** — 5 passed.
- [ ] **Step 5: Gates e commit** — `feat(TEC-153): o ticket passa a decidir a especialidade exigida`.

---

### Task 5: O ticket normalizado

**Files:**
- Modify: `src/mobia/domain/agente/dinheiro.py`
- Test: `tests/unit/test_ticket_do_investidor.py`

**Interfaces:**
- Consumes: `parsear`, `FaixaDePreco`, `Recusa` (já existem no módulo).
- Produces: `ticket_de(expressao: str) -> int | None`.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O ticket do investidor reusa o parser de dinheiro. TEC-153, D6."""

from mobia.domain.agente.dinheiro import ticket_de


def test_o_cenario_do_gherkin() -> None:
    """"uns 800 mil" informado como ticket vira 80000000 centavos."""
    assert ticket_de("uns 800 mil") == 80_000_000


def test_um_milhao_e_o_limiar_do_alto_ticket() -> None:
    assert ticket_de("1 milhao") == 100_000_000


def test_expressao_sem_valor_devolve_none() -> None:
    """Recusa e caminho normal desde a TEC-148, nao excecao."""
    assert ticket_de("prefiro nao dizer") is None


def test_faixa_colapsa_no_extremo_superior() -> None:
    """Numa busca "ate 800 mil" e teto; num ticket e o montante disponivel.
    A semantica difere, e o colapso acontece aqui, na borda."""
    assert ticket_de("ate 800 mil") == 80_000_000
```

- [ ] **Step 2: Rode e veja falhar** — `ImportError: cannot import name 'ticket_de'`.

- [ ] **Step 3: Implemente**

No fim de `dinheiro.py`:

```python
def ticket_de(expressao: str) -> int | None:
    """O ticket do investidor, em centavos. TEC-153, RN-05.2.

    **Reusa `parsear` e colapsa na borda**, em vez de um segundo parser
    monetario: a TEC-146 gastou uma card inteira consertando uma segunda
    fonte para a mesma verdade, e a normalizacao de "uns 800 mil" nao muda
    porque o campo mudou de nome.

    O colapso e necessario porque a SEMANTICA difere. Numa busca, "ate 800
    mil" e um teto e a faixa tem dois extremos. Num ticket, e o montante
    disponivel: um valor so. Toma-se `max_centavos`, e `min_centavos` quando
    so ele veio -- "a partir de 800 mil" como ticket ainda descreve 800 mil
    de dinheiro na mao.

    `Recusa` devolve `None` sem levantar: recusa de valor e caminho normal
    desde a TEC-148.
    """
    resultado = parsear(expressao, Intencao.INVESTIMENTO)
    if not isinstance(resultado, FaixaDePreco):
        return None
    return resultado.max_centavos if resultado.max_centavos is not None else resultado.min_centavos
```

Confirme os nomes reais de `Recusa`/`FaixaDePreco` e a assinatura de `parsear` antes de escrever — se `parsear` tiver parâmetros adicionais (por exemplo `piso_do_numero_nu`), use o default e diga no relatório qual você usou.

- [ ] **Step 4: Rode e veja passar** — 4 passed.
- [ ] **Step 5: Gates e commit** — `feat(TEC-153): o ticket do investidor reusa o parser de dinheiro`.

---

### Task 6: O teto de perguntas passa a contar o investidor

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (`_marca_de` / `perguntas_contaveis`)
- Test: `tests/unit/test_perguntas_contaveis.py` (acrescentar; o arquivo existe desde a TEC-149)

**Interfaces:**
- Consumes: `CAMPOS_DO_INVESTIDOR` (Task 2).

**Por que esta task existe:** `perguntas_contaveis` reconhece um nome comparando com `_CAMPOS_DA_EXTRACAO` e `_NOME_DA_MARCA`. Um campo de `ExtracaoDoInvestidor` não está em nenhum dos dois, então **toda pergunta da trilha do investidor sairia de graça do teto de 8 da RN-05.5**. Um investidor seria perguntado indefinidamente enquanto um comprador é cortado na oitava, e nada no código diria por quê.

- [ ] **Step 1: Escreva o teste que falha**

Acrescente ao arquivo existente:

```python
def test_campo_do_investidor_tambem_conta() -> None:
    """Sem isto a trilha do investidor escapa inteira do teto da RN-05.5, e um
    investidor e interrogado sem fim enquanto um comprador e cortado na
    oitava. TEC-153."""
    assert len(perguntas_contaveis(("horizonte",))) == 1
    assert len(perguntas_contaveis(("ticket_expressao",))) == 1


def test_campo_do_investidor_e_campo_padrao_somam_juntos() -> None:
    assert len(perguntas_contaveis(("horizonte", "urgencia"))) == 2
```

- [ ] **Step 2: Rode e veja falhar** — as duas novas reprovam com `0 == 1`; as quatro antigas seguem verdes.

- [ ] **Step 3: Implemente**

Em `_marca_de`, acrescente `CAMPOS_DO_INVESTIDOR` à consulta, com comentário dizendo por que o vocabulário cresceu:

```python
    # TEC-153: a trilha do investidor tem schema proprio (o schema compilado e
    # parcela do orcamento de prompt), entao os nomes dela nao estao em
    # `_CAMPOS_DA_EXTRACAO`. Sem esta linha, toda pergunta do investidor
    # sairia de graca do teto da RN-05.5.
    return nome if nome in _CAMPOS_DA_EXTRACAO or nome in CAMPOS_DO_INVESTIDOR else None
```

- [ ] **Step 4: Rode e veja passar** — 6 passed no arquivo.
- [ ] **Step 5: Gates e commit** — `fix(TEC-153): o teto de perguntas passa a contar a trilha do investidor`.

---

### Task 7: O prompt e a chamada do investidor

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py`
- Test: `tests/unit/test_classificador_investidor.py`

**Interfaces:**
- Consumes: `ExtracaoDoInvestidor`, os enums (Task 2).
- Produces: `SISTEMA_DO_INVESTIDOR: str`, `SCHEMA_DO_INVESTIDOR: dict`, e `async def qualificar_investidor(self, contexto) -> RespostaDoInvestidor` no protocolo e na implementação.

**O ritual do orçamento é obrigatório nesta task.** Rode `pytest -q -k margem_do_orcamento -s` **antes** de começar e **depois** de terminar, e ponha os dois números no relatório. `SCHEMA_DO_INVESTIDOR` **não** pode ser anexado a `SCHEMA_DA_RESPOSTA` — se o número se mexer, você o anexou por engano.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""A chamada do subagente investidor. TEC-153, RN-07.1, D1 e D2."""

from mobia.domain.agente.classificador import (
    SCHEMA_DA_RESPOSTA,
    SCHEMA_DO_INVESTIDOR,
    SISTEMA_DO_INVESTIDOR,
)


def test_o_schema_do_investidor_nao_entra_no_schema_principal() -> None:
    """E disto que depende o custo zero para quem nao e investidor: o schema
    compilado e uma das quatro parcelas do orcamento de prompt, e seis campos
    que a maioria dos leads nunca preenche nao podem custar tokens a todos.
    TEC-153, D2."""
    assert "investidor" not in SCHEMA_DA_RESPOSTA["properties"]
    for nome in SCHEMA_DO_INVESTIDOR["properties"]:
        assert nome not in SCHEMA_DA_RESPOSTA["properties"]


def test_o_prompt_do_investidor_e_diferente_do_principal() -> None:
    from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE

    assert SISTEMA_DO_INVESTIDOR != SISTEMA_DO_AGENTE


def test_o_prompt_do_investidor_nao_pede_quartos_nem_vagas() -> None:
    """Cenario 1 do Gherkin: "o agente nao pergunta sobre numero de quartos"."""
    baixo = SISTEMA_DO_INVESTIDOR.lower()
    assert "quarto" not in baixo
    assert "vaga" not in baixo
```

- [ ] **Step 2: Rode e veja falhar** — `ImportError`.

- [ ] **Step 3: Implemente**

Três peças, seguindo os padrões que já existem no arquivo:

1. `SISTEMA_DO_INVESTIDOR`, junto de `SISTEMA_DA_DESAMBIGUACAO` e `SISTEMA_DA_REACAO`. O texto pede ticket, expectativa (tipo e percentual), horizonte, tolerância a reforma e se já investe — e **não** menciona quartos, vagas nem metragem. Comentário acima dele registrando que ele não entra no orçamento do prompt principal porque é `system` de outra chamada.
2. `SCHEMA_DO_INVESTIDOR`, no molde de `SCHEMA_DA_EXTRACAO`, com `additionalProperties: False` e os seis campos. Se você usar uma ordem declarada (como `_ORDEM_DOS_CAMPOS` faz para o principal), replique a guarda de import que aquele bloco usa — `RuntimeError`, não `assert`, pela razão que o comentário de lá dá (`python -O` removeria o assert).
3. `qualificar_investidor`, no molde de `desambiguar`: chama `self._chamar` com `system=SISTEMA_DO_INVESTIDOR`, `max_tokens` próprio e `output_config` montado do schema. **Sem `tools`/`porta`** — a qualificação do investidor não busca imóvel, e a docstring de `desambiguar` explica por que os campos de busca saem vazios nesse caminho. Acrescente o método ao `Protocol` também.

A docstring de `qualificar_investidor` deve registrar o que a de `desambiguar` registra e vale igual aqui: **o turno paga o contexto de entrada inteiro duas vezes**, porque trocar o `system` invalida o cache do que vem depois dele.

- [ ] **Step 4: Rode e veja passar**, e rode o ritual do orçamento

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador_investidor.py -v --tb=short
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```
O segundo tem de imprimir o **mesmo** número de antes. Se mexeu, o schema do investidor vazou para o principal.

- [ ] **Step 5: Gates e commit** — `feat(TEC-153): o subagente do investidor ganha prompt e schema proprios`.

---

### Task 8: A fiação no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`, `src/mobia/domain/context/repositorio.py`
- Test: `tests/integration/test_turno_investidor.py`

**Interfaces:**
- Consumes: tudo das tasks 2–7.
- Produces: `SUBAGENTE_INVESTIDOR = "investidor"`, e a gravação dos campos e do perfil.

**Esta é a task de maior risco do plano.** Leia os âncoras no arquivo real antes de escrever, e **pare e pergunte se algum não bater**.

A regra, na ordem:

1. Depois da geração, `virou_investidor = gerada.intencao is Intencao.INVESTIMENTO and anterior_nao_era_investimento`. A intenção anterior vem de `ler_intencao`, que o bloco transacional já chama.
2. `ja_e_investidor` (a intenção anterior já era `INVESTIMENTO`) escolhe o prompt **antes** da chamada única — sem segunda chamada.
3. Quando `virou_investidor`, a segunda chamada roda, a resposta da chamada 1 é descartada para efeito de texto, e `subagente` vira `SUBAGENTE_INVESTIDOR` — o mesmo tratamento que `desambiguando` já recebe em `texto, telemetria, subagente = ...`.
4. **Precedência: desambiguação vence.** Se o turno for ambíguo e investidor ao mesmo tempo, desambigua — sem intenção confiável não há trilha a escolher (D1 do spec). Isto é uma condição explícita, não um acidente de ordem.
5. Os campos extraídos e o perfil derivado (`perfil_de`) são gravados por uma função nova no repositório, no mesmo commit pré-entrega em que `gravar_estado` roda.

- [ ] **Step 1: Escreva o teste que falha**

`tests/integration/test_turno_investidor.py`, usando `rodar_turno`/`classificador_fake` como `tests/integration/test_turno_teto_de_perguntas.py` faz (copie dali as constantes locais `CANAL`/`CONVERSA` e o helper `_semear_estado`). Quatro testes:

- `test_a_virada_para_investimento_chama_o_subagente` — a intenção vira `INVESTIMENTO` e o fake registra **duas** chamadas, a segunda com o prompt do investidor.
- `test_investidor_ja_conhecido_nao_paga_segunda_chamada` — estado com `intencao="INVESTIMENTO"`; assere **uma** chamada.
- `test_desambiguacao_vence_a_virada` — turno ambíguo e investidor; assere que o desambiguador respondeu e o subagente do investidor não.
- `test_o_perfil_e_gravado_a_partir_dos_campos` — horizonte longo + `ALUGUEL` gravados pelo turno resultam em `perfil_investidor == "RENDA"` lido do banco.

O `ClassificadorFake` de `tests/conftest.py` vai precisar de um método `qualificar_investidor` e de um contador próprio. **Estenda o fake, não crie um segundo** — dois dublês do mesmo protocolo divergiriam.

- [ ] **Step 2: Rode e veja falhar** — o primeiro teste falha com uma chamada em vez de duas.
- [ ] **Step 3: Implemente** a fiação e a função de gravação.
- [ ] **Step 4: Rode e veja passar**, e rode `tests/integration` inteiro (`-n 4 --dist loadfile --tb=short`), porque esta task mexe no caminho que dezenas de outros testes exercitam.
- [ ] **Step 5: Gates e commit** — `feat(TEC-153): o turno ativa a trilha do investidor na virada`.

---

### Task 9: As emendas ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

O texto das duas emendas está pronto na seção **"Emendas ao SRS"** do spec — copie de lá, não componha outro. A E-01 entra aninhada abaixo da RN-07.2; a E-02, abaixo da RN-05.2. **Nunca reescreva o texto de 22/08/2026.** Acrescente as duas linhas correspondentes à tabela de emendas do cabeçalho.

- [ ] **Step 1: Leia as emendas existentes sob RN-05.4 e RN-05.7** como template de formatação.
- [ ] **Step 2: Aplique as duas emendas e as duas linhas da tabela.**
- [ ] **Step 3: Gates e commit** — `docs(TEC-153): a RN-07.2 e a RN-05.2 ganham emenda`.

---

## Fechamento

- [ ] **Suíte inteira, UMA vez:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`. Guarde o hash com o resultado. Se falhar, repita sobre a mesma árvore antes de culpar a mudança.
- [ ] **Ritual do orçamento uma última vez:** `pytest -q -k margem_do_orcamento -s`. O número tem de ser o mesmo do início do plano.
- [ ] **`./.venv/Scripts/python.exe scripts/comentarios_tocados.py`** — reconfira todo `ALTERADO` e todo `VIZINHO` em `classificador.py`, `turno.py`, `repositorio.py`, `qualificacao.py` e `dinheiro.py`.
- [ ] **PR contra `main`**, depois comentário na [TEC-153](https://eduardodurieuxlopes.atlassian.net/browse/TEC-153) e card para **Em análise** — não para Feito. O comentário registra, no mínimo: as duas emendas nomeadas; que a especialidade nasce sem chamador (L1) e o critério de aceite do roteamento não é exercitável ponta a ponta; que o perfil não muda a busca (L2); que a preferência por tipo ficou fora (L3); e que o turno da virada paga duas chamadas ao provedor (L4).

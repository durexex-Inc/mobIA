# TEC-149 — Teto de perguntas de qualificação: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O agente para de fazer perguntas de qualificação depois da oitava, oferece o corretor com texto determinístico e registra handoff com o gatilho `LIMITE_DE_PERGUNTAS`.

**Architecture:** Um contador persistido em `lead_qualification` cresce em SQL no commit pós-entrega, ao lado de `marcar_perguntados` e sob a mesma guarda. A decisão do teto é uma função pura em `domain/context/qualificacao.py`; a substituição do texto acontece em `turno.py`, no mesmo ponto em que a moderação de saída já substitui o dela. O handoff é uma chamada a `registrar_handoff`, com gatilho que existe desde a TEC-174 e nunca teve emissor.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, Postgres, pytest/pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-149-teto-de-perguntas-design.md`

## Global Constraints

- **Os três gates do CI, nesta ordem, antes de qualquer commit.** `ruff check src tests alembic evals scripts`; `ruff format --check src tests alembic evals scripts`; `mypy src`. Localmente: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, depois `-m ruff format --check ...`, depois `-m mypy`. **Passar no linter não diz nada sobre o formatador — são gates separados.**
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Loop de teste enquanto escreve:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4s, sem Docker, sem `-n`). Suíte inteira, uma vez só no fim: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`.
- **`tests/integration` exige `docker compose` de pé.** Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` mesmo com o container `healthy`. Espere e retente; não diagnostique código por causa disso.
- **Uma falha isolada com `ConnectionResetError` não autoriza conclusão nenhuma.** Rode o arquivo sozinho antes de culpar a mudança.
- **Nunca `-q` sem `--tb=short`:** `-q` imprime só o nome do teste que falhou, sem traceback.
- **Comentário desatualizado é defeito.** Antes do PR: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`, e reconfira toda linha `ALTERADO` e `VIZINHO`.
- **Mensagem de commit:** `tipo(TEC-149): o que passou a ser verdade`, português sem acento no assunto.
- **Emenda ao SRS entra como item aninhado** `Emenda E-nn (TEC-nnn, data)` abaixo da regra que altera, nunca reescrevendo o texto de 22/08/2026.

---

### Task 1: A coluna `perguntas_feitas`

**Files:**
- Create: `alembic/versions/0032_teto_de_perguntas.py`
- Modify: `src/mobia/domain/context/models.py` (classe `LeadQualification`, logo abaixo de `campos_recusados`)
- Test: `tests/integration/test_migracao_teto_de_perguntas.py`

**Interfaces:**
- Consumes: nada.
- Produces: `LeadQualification.perguntas_feitas: Mapped[int]`, coluna `perguntas_feitas smallint NOT NULL DEFAULT 0`.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/integration/test_migracao_teto_de_perguntas.py`. Basename distinto de tudo em `tests/unit/` e `tests/perf/` — basename repetido entre unit e integration aborta a coleta da suíte inteira.

```python
"""A `0032` acrescenta o contador do teto da RN-05.5. TEC-149."""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker


async def test_a_coluna_do_contador_existe_nao_nulavel_com_default_zero() -> None:
    async with get_sessionmaker()() as session:
        linha = (
            await session.execute(
                text(
                    "SELECT data_type, is_nullable, column_default "
                    "  FROM information_schema.columns "
                    " WHERE table_name = 'lead_qualification' "
                    "   AND column_name = 'perguntas_feitas'"
                )
            )
        ).one_or_none()

    assert linha is not None, "a coluna perguntas_feitas nao existe"
    assert linha.data_type == "smallint"
    # NOT NULL com default: `0` numa linha antiga nao afirma "ninguem
    # perguntou", afirma "ninguem contava" -- e o lead antigo ganha orcamento
    # cheio, que erra na direcao de continuar atendendo como hoje. Ver D1.
    assert linha.is_nullable == "NO"
    assert linha.column_default is not None and "0" in linha.column_default
```

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_migracao_teto_de_perguntas.py -v --tb=short`
Expected: FAIL com `AssertionError: a coluna perguntas_feitas nao existe`.

- [ ] **Step 3: Escreva a migration**

Crie `alembic/versions/0032_teto_de_perguntas.py`:

```python
"""o contador do teto de perguntas

TEC-149, RN-05.5. O SRS pede este contador em `conversa.perguntas_feitas`, e
nao ha tabela `conversa`: a Emenda E-01 da RN-05.7 (TEC-148) ja estabeleceu
que `conversation_key` e o id externo do lead e deferiu a criacao da
entidade. O contador vive aqui, na mesma chave -- e o teto passa a valer por
LEAD, sem fronteira de conversa e sem expirar. Ver a Emenda E-01 da RN-05.5.

`NOT NULL DEFAULT 0`, e nao nulavel como as colunas vizinhas desta tabela.
Ali `NULL` distingue "linha anterior a card" de "a card rodou e nao havia
nada"; para um contador essa distincao nao paga. `0` numa linha antiga nao
afirma "ninguem perguntou" -- afirma "ninguem contava", e o lead antigo ganha
orcamento cheio. Erra na direcao de continuar atendendo como hoje, em vez de
cortar alguem que nunca foi avisado.

`smallint` porque o teto e 8: o tipo vem do dicionario de dados do SRS, e
nem o maior exagero de contagem chega perto de 32.767.

Revision ID: 0032
Revises: 0031
"""

import sqlalchemy as sa

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("perguntas_feitas", sa.SmallInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "perguntas_feitas")
```

- [ ] **Step 4: Acrescente a coluna ao modelo**

Em `src/mobia/domain/context/models.py`, dentro de `LeadQualification`, imediatamente abaixo da linha de `campos_recusados`:

```python
    # TEC-149, RN-05.5. Quantas perguntas de qualificacao ja foram FEITAS E
    # ENTREGUES a este lead. Cresce so no commit pos-entrega do turno -- ver
    # `contar_perguntas` no repositorio, e o porque no comentario que chama
    # `marcar_perguntados` em `turno.py`.
    #
    # `NOT NULL DEFAULT 0`, ao contrario das colunas acima: ali o `NULL`
    # distingue "linha anterior a card" de "nao havia nada", e para um
    # contador isso nao paga. Zero numa linha antiga significa "ninguem
    # contava", e o lead antigo recomeca com orcamento cheio.
    #
    # Conta CAMPO perguntado, nao turno: a Emenda E-01 da RN-05.4 permite
    # duas perguntas por turno desde a TEC-255, e contar turnos daria dezesseis
    # perguntas sob um teto que diz oito.
    perguntas_feitas: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
```

Acrescente `SmallInteger` à lista de importações de `sqlalchemy` no topo do arquivo, mantendo a ordem alfabética que o `ruff` exige.

- [ ] **Step 5: Aplique a migration e rode o teste**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_migracao_teto_de_perguntas.py -v --tb=short
```
Expected: PASS.

Se o `upgrade` reprovar com `ConnectionResetError [WinError 64]`, espere e retente — é o comportamento documentado do banco local, não a sua migration.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0032_teto_de_perguntas.py src/mobia/domain/context/models.py tests/integration/test_migracao_teto_de_perguntas.py
git commit -m "feat(TEC-149): lead_qualification ganha o contador de perguntas"
```

---

### Task 2: Quais nomes de `perguntou` contam

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (junto de `_marca_de`, que já existe)
- Test: `tests/unit/test_perguntas_contaveis.py`

**Interfaces:**
- Consumes: `_marca_de(nome: str) -> str | None`, privada do módulo.
- Produces: `perguntas_contaveis(perguntou: Iterable[str]) -> frozenset[str]`.

**Por que não é `len(perguntou)` cru:** o modelo pode devolver nome que não pertence a vocabulário nenhum, e devolve os dois extremos do orçamento (`faixa_preco_min` e `faixa_preco_max`) como nomes distintos para **uma** pergunta. `_marca_de` já colapsa os dois em `_MARCA_DO_ORCAMENTO` e já devolve `None` para o que não reconhece.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_perguntas_contaveis.py`:

```python
"""O que conta como pergunta para o teto da RN-05.5. TEC-149, D3."""

from mobia.domain.context.repositorio import perguntas_contaveis


def test_campo_conhecido_conta_uma_vez() -> None:
    assert len(perguntas_contaveis(("urgencia",))) == 1


def test_os_dois_extremos_do_orcamento_sao_uma_pergunta_so() -> None:
    """Perguntar "de quanto ate quanto" e UMA pergunta, e o modelo declara os
    dois nomes. `_marca_de` ja colapsa os dois no mesmo nome logico; contar
    cru gastaria dois do orcamento de oito por uma frase."""
    assert len(perguntas_contaveis(("faixa_preco_min", "faixa_preco_max"))) == 1


def test_nome_desconhecido_nao_conta() -> None:
    """O modelo as vezes devolve o TEXTO da pergunta em vez do nome do campo.
    Contar isso puniria o lead por um defeito nosso."""
    assert perguntas_contaveis(("qual o seu prazo?",)) == frozenset()


def test_entrada_vazia_e_conjunto_vazio() -> None:
    assert perguntas_contaveis(()) == frozenset()
```

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_perguntas_contaveis.py -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'perguntas_contaveis'`.

- [ ] **Step 3: Implemente**

Em `src/mobia/domain/context/repositorio.py`, logo abaixo de `_marca_de`:

```python
def perguntas_contaveis(perguntou: Iterable[str]) -> frozenset[str]:
    """Os nomes de `perguntou` que contam para o teto da RN-05.5. TEC-149, D3.

    Conjunto e nao lista: os dois extremos do orcamento chegam como nomes
    distintos e sao UMA pergunta -- `_marca_de` ja os colapsa no mesmo nome
    logico, e o conjunto termina o servico. Nome que nao pertence a
    vocabulario nenhum sai fora: o modelo as vezes devolve o texto da
    pergunta em lugar do nome do campo, e contar isso gastaria o orcamento
    do lead com um defeito nosso.

    Reusa `_marca_de` de proposito, em vez de uma segunda lista de nomes:
    duas fontes para o mesmo vocabulario divergiriam em silencio, que e o
    defeito que a TEC-146 gastou uma card inteira consertando.
    """
    marcas = (_marca_de(nome) for nome in perguntou)
    return frozenset(marca for marca in marcas if marca is not None)
```

Confirme que `Iterable` já está importado de `collections.abc` no topo do arquivo; `marcar_perguntados` já o usa na assinatura.

- [ ] **Step 4: Rode e veja passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_perguntas_contaveis.py -v --tb=short`
Expected: 4 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/repositorio.py tests/unit/test_perguntas_contaveis.py
git commit -m "feat(TEC-149): o vocabulario diz quais nomes de perguntou contam"
```

---

### Task 3: A regra do teto, pura

**Files:**
- Modify: `src/mobia/domain/context/qualificacao.py`
- Test: `tests/unit/test_teto_de_perguntas.py`

**Interfaces:**
- Consumes: nada.
- Produces: `TETO_DE_PERGUNTAS: int` (valor `8`) e `excedeu_o_teto(perguntas_feitas: int, perguntas_deste_turno: int) -> bool`.

**Por que em `qualificacao.py`:** é o módulo das regras puras de qualificação, sem I/O, "de propósito" segundo a própria docstring dele — a RN-05.3 já mora lá e a RN-05.5 é irmã. Manter a regra fora de `turno.py` é o que permite testá-la em `tests/unit/`, sem Postgres.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_teto_de_perguntas.py`:

```python
"""O teto de 8 perguntas da RN-05.5. TEC-149, D3 e D4."""

from mobia.domain.context.qualificacao import TETO_DE_PERGUNTAS, excedeu_o_teto


def test_o_teto_e_oito() -> None:
    """Pinado: e o numero da RN-05.5, e mudar sem mudar a regra e defeito."""
    assert TETO_DE_PERGUNTAS == 8


def test_conversa_nova_nao_excede() -> None:
    assert excedeu_o_teto(0, 1) is False


def test_a_oitava_pergunta_ainda_passa() -> None:
    """Sete gastas mais uma sao oito, e a regra diz "nao mais de 8"."""
    assert excedeu_o_teto(7, 1) is False


def test_a_nona_nao_passa() -> None:
    assert excedeu_o_teto(8, 1) is True


def test_duas_perguntas_sobre_sete_gastas_suprimem_o_turno_inteiro() -> None:
    """A consequencia declarada da D4: com duas perguntas num turno o teto
    morde entre 7 e 8, e a oitava nunca e feita. A alternativa seria entregar
    meia pergunta, e a prosa e um texto so."""
    assert excedeu_o_teto(7, 2) is True


def test_turno_que_nao_pergunta_nunca_excede() -> None:
    """Depois do teto o agente continua respondendo duvida e mostrando
    imovel: "nao faz mais perguntas" nao e "para de conversar"."""
    assert excedeu_o_teto(99, 0) is False
```

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_teto_de_perguntas.py -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'TETO_DE_PERGUNTAS'`.

- [ ] **Step 3: Implemente**

Em `src/mobia/domain/context/qualificacao.py`, abaixo de `CAMPOS_OBRIGATORIOS`:

```python
# RN-05.5. O unico lugar em que este numero esta escrito.
TETO_DE_PERGUNTAS = 8
```

E no fim do módulo:

```python
def excedeu_o_teto(perguntas_feitas: int, perguntas_deste_turno: int) -> bool:
    """O turno passaria do teto da RN-05.5 se entregasse suas perguntas.

    Recebe DOIS inteiros, e nao o estado nem a tupla `perguntou`: a regra e
    aritmetica, e quem sabe traduzir nome de campo em pergunta contavel e
    `perguntas_contaveis`, no repositorio, onde o vocabulario mora. Manter
    esta funcao sem dependencia e o que a deixa em `tests/unit/`.

    `>` e nao `>=` porque a regra diz "nao mais de 8": a oitava pergunta e
    permitida, a nona nao. Com duas perguntas num turno sobre sete ja gastas,
    o turno inteiro e suprimido e a oitava nunca e feita -- consequencia
    declarada na D4, e a alternativa seria entregar meia pergunta.

    Zero perguntas neste turno nunca excede, por maior que seja o contador:
    depois do teto o agente continua respondendo duvida e mostrando imovel,
    so nunca mais qualifica.
    """
    return perguntas_feitas + perguntas_deste_turno > TETO_DE_PERGUNTAS
```

- [ ] **Step 4: Rode e veja passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_teto_de_perguntas.py -v --tb=short`
Expected: 6 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/qualificacao.py tests/unit/test_teto_de_perguntas.py
git commit -m "feat(TEC-149): a regra do teto de perguntas vira funcao pura"
```

---

### Task 4: `contar_perguntas`, o incremento em SQL

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` (imediatamente abaixo de `marcar_perguntados`)
- Test: `tests/integration/test_contar_perguntas.py`

**Interfaces:**
- Consumes: `perguntas_contaveis` (Task 2), `LeadQualification.perguntas_feitas` (Task 1).
- Produces: `async def contar_perguntas(session, *, channel: str, conversation_key: str, perguntou: Iterable[str]) -> None`.

**Por que função irmã e não um trecho dentro de `marcar_perguntados`:** aquela função tem duas saídas antecipadas (`if not preenchidos: return` e `if not marcados: return`) e o comentário dela declara que *"marcar de menos e o erro seguro"*. Para o contador o mesmo atalho inverte o sinal — o turno em que o lead escreve "oi" e o agente pergunta o orçamento não extrai nada, sairia no primeiro `return`, e a pergunta feita e entregue não contaria. Ver D2.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/integration/test_contar_perguntas.py`:

```python
"""O contador do teto cresce por campo entregue. TEC-149, D2 e D3."""

import asyncio
from typing import Any

from sqlalchemy import select

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import contar_perguntas
from mobia.infra.db import get_sessionmaker

# Constantes locais, como nos outros arquivos de integracao: eles sao
# autocontidos de proposito.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _semear(session: Any) -> None:
    session.add(LeadQualification(channel=CANAL, conversation_key=CONVERSA))
    await session.commit()


async def _contador(session: Any) -> int:
    # `expire_all` antes de reler: o incremento aconteceu em SQL, e o objeto
    # que esta sessao tem em memoria nao sabe disso.
    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is not None
    return linha.perguntas_feitas


async def test_um_campo_perguntado_soma_um(session: Any) -> None:
    await _semear(session)

    await contar_perguntas(
        session, channel=CANAL, conversation_key=CONVERSA, perguntou=("urgencia",)
    )
    await session.commit()

    assert await _contador(session) == 1


async def test_dois_turnos_somam(session: Any) -> None:
    """O que a coluna compra: o numero sobrevive ao turno em vez de viver na
    memoria dele."""
    await _semear(session)

    for campo in ("urgencia", "regiao"):
        await contar_perguntas(
            session, channel=CANAL, conversation_key=CONVERSA, perguntou=(campo,)
        )
        await session.commit()

    assert await _contador(session) == 2


async def test_turno_sem_pergunta_nao_mexe_no_contador(session: Any) -> None:
    await _semear(session)

    await contar_perguntas(session, channel=CANAL, conversation_key=CONVERSA, perguntou=())
    await session.commit()

    assert await _contador(session) == 0


async def test_nome_desconhecido_nao_conta(session: Any) -> None:
    """O modelo as vezes devolve o TEXTO da pergunta em vez do nome do campo."""
    await _semear(session)

    await contar_perguntas(
        session, channel=CANAL, conversation_key=CONVERSA, perguntou=("qual o seu prazo?",)
    )
    await session.commit()

    assert await _contador(session) == 0


async def test_dois_turnos_concorrentes_nao_perdem_incremento(session: Any) -> None:
    """A razao de o incremento ser SQL, e nao leitura em Python seguida de
    escrita (D2).

    Duas SESSOES, e nao duas chamadas na mesma: e a corrida real entre dois
    turnos da mesma conversa, que a docstring de `marcar_perguntados` ja
    descreve para as colunas de valor. Com `perguntas_feitas + 1` o Postgres
    serializa os dois UPDATE na mesma linha e o total e 2. Com um
    read-modify-write, os dois leriam 0 e gravariam 1 -- e este teste
    reprovaria com 1, que e o bug que ninguem veria em producao ate o lead
    ser cortado cedo ou tarde demais.
    """
    await _semear(session)

    async def _incrementar(campo: str) -> None:
        async with get_sessionmaker()() as sessao:
            await contar_perguntas(
                sessao, channel=CANAL, conversation_key=CONVERSA, perguntou=(campo,)
            )
            await sessao.commit()

    await asyncio.gather(_incrementar("urgencia"), _incrementar("regiao"))

    assert await _contador(session) == 2
```

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_contar_perguntas.py -v --tb=short`
Expected: FAIL com `ImportError: cannot import name 'contar_perguntas'`.

- [ ] **Step 3: Implemente**

Em `src/mobia/domain/context/repositorio.py`, imediatamente abaixo de `marcar_perguntados`:

```python
async def contar_perguntas(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    perguntou: Iterable[str],
) -> None:
    """Soma ao contador do teto da RN-05.5 as perguntas deste turno. TEC-149.

    **Funcao irma de `marcar_perguntados`, e nao um trecho dentro dela.** As
    duas rodam no mesmo commit pos-entrega e pela mesma razao -- a pergunta
    so conta depois de o lead te-la recebido --, mas as guardas sao
    diferentes e incompativeis. `marcar_perguntados` sai cedo quando o turno
    nao extraiu campo nenhum, e o comentario de la declara que "marcar de
    menos e o erro seguro". Aqui o mesmo atalho inverte o sinal: o turno em
    que o lead escreve "oi" e o agente pergunta o orcamento nao extrai nada,
    sairia naquele `return`, e a pergunta FEITA E ENTREGUE nao contaria --
    dando ao lead mais perguntas do que as oito que a regra promete.

    **Incremento em SQL, nunca lendo em Python para regravar.** E a mesma
    razao pela qual a uniao da marca foi para o SQL: dois turnos concorrentes
    da mesma conversa, em que o commit pos-entrega mais lento sobrescreve o
    valor mais novo pelo mais velho, em silencio. `coluna = coluna + :n` nao
    tem esse problema, e um contador errado nao tem sintoma nenhum ate o
    lead ser cortado cedo ou tarde demais.

    Sem nada contavel, nenhum UPDATE: um turno que so respondeu duvida nao
    gasta orcamento, e um `SET` que soma zero so produziria escrita morta.
    """
    quantas = len(perguntas_contaveis(perguntou))
    if not quantas:
        return

    await session.execute(
        update(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
        .values(
            perguntas_feitas=LeadQualification.perguntas_feitas + quantas,
            updated_at=datetime.now(UTC),
        )
    )
```

- [ ] **Step 4: Rode e veja passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_contar_perguntas.py -v --tb=short`
Expected: 5 passed.

Se der `ConnectionResetError`, rode o arquivo de novo antes de investigar.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/repositorio.py tests/integration/test_contar_perguntas.py
git commit -m "feat(TEC-149): contar_perguntas soma o teto no commit pos-entrega"
```

---

### Task 5: A fiação no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py`
- Test: `tests/integration/test_turno_teto_de_perguntas.py`

**Interfaces:**
- Consumes: `excedeu_o_teto`, `TETO_DE_PERGUNTAS` (Task 3), `perguntas_contaveis`, `contar_perguntas` (Tasks 2 e 4), `Gatilho.LIMITE_DE_PERGUNTAS` e `registrar_handoff` (já existem).
- Produces: `TEXTO_DO_LIMITE_DE_PERGUNTAS`, e o comportamento que os cenários 1, 3 e 4 do Gherkin descrevem.

São quatro mudanças em `turno.py`, e a ordem importa:

1. A constante do texto, junto das outras `TEXTO_*` do topo do módulo.
2. O cálculo da bandeira `teto_atingido`, **depois** da geração (precisa de `gerada.perguntou`) e **antes** do bloco transacional que registra handoff.
3. A substituição `texto = TEXTO_DO_LIMITE_DE_PERGUNTAS`, no mesmo ponto em que a moderação de saída substitui pelo neutro.
4. `teto_atingido` entra como quinta condição da guarda do bloco pós-entrega, e `contar_perguntas` entra ao lado de `marcar_perguntados`.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/integration/test_turno_teto_de_perguntas.py`:

```python
"""O teto de 8 perguntas visto do turno inteiro. TEC-149, RN-05.5.

Cenarios 1, 3 e 4 do Gherkin da card. O cenario 2 -- desambiguacao nao conta
-- vive em `tests/unit/`, porque la a garantia e estrutural e nao precisa de
turno em volta.
"""

from typing import Any

from sqlalchemy import select, text

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.agente.turno import TEXTO_DO_LIMITE_DE_PERGUNTAS
from mobia.domain.context.models import LeadQualification

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_temperatura_no_turno.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _semear_estado(session: Any, *, perguntas_feitas: int, **campos: object) -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            perguntas_feitas=perguntas_feitas,
            **campos,
        )
    )
    await session.commit()


async def _gatilhos(session: Any) -> list[str]:
    resultado = await session.execute(text("SELECT gatilho FROM handoffs"))
    return [linha.gatilho for linha in resultado]


async def _contador(session: Any) -> int:
    # `expire_all` antes de reler: o incremento aconteceu em SQL, e o objeto
    # que esta sessao tem em memoria nao sabe disso.
    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is not None
    return linha.perguntas_feitas


async def test_atingido_o_teto_o_lead_recebe_o_corretor_e_nasce_handoff(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Cenario 1: oito perguntas gastas, urgencia ainda vazia."""
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("urgencia",)),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert TEXTO_DO_LIMITE_DE_PERGUNTAS in entregador.entregues
    assert "LIMITE_DE_PERGUNTAS" in await _gatilhos(session)
    # A pergunta foi SUPRIMIDA, nao feita: o contador nao pode ter crescido,
    # senao o proximo turno nasce acima do teto por uma pergunta que o lead
    # nunca viu.
    assert await _contador(session) == 8


async def test_a_prosa_do_modelo_nao_vaza_no_turno_do_teto(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A outra metade do cenario 1, num teste proprio porque e outra coisa:
    nao basta o texto do teto SAIR, a prosa do modelo tem de NAO sair -- ela
    carrega a pergunta que o teto proibe."""
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()
    prosa = "E qual a sua urgencia para decidir?"

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("urgencia",), resposta=prosa),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert prosa not in entregador.entregues


async def test_lead_qualificado_antes_do_teto_segue_o_fluxo_normal(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Cenario 3: quatro perguntas feitas e os quatro obrigatorios preenchidos."""
    await _semear_estado(
        session,
        perguntas_feitas=4,
        intencao=Intencao.COMPRA.value,
        faixa_preco_max_centavos=50_000_000,
        regiao="centro",
        urgencia=Urgencia.ATE_3_MESES.value,
    )
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("vagas",)),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues
    assert "LIMITE_DE_PERGUNTAS" not in await _gatilhos(session)
    # Contou: o turno nao extraiu campo nenhum, e a pergunta contou mesmo
    # assim. E o que separa `contar_perguntas` de `marcar_perguntados` (D2).
    assert await _contador(session) == 5


async def test_o_contador_sobrevive_ao_turno(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Cenario 4: o contador continua de onde estava.

    O Gherkin fala em "worker reiniciado". O que um teste pode observar disso
    e que o numero veio do BANCO e nao da memoria do processo: dois turnos
    independentes, e o segundo enxerga o que o primeiro somou.
    """
    await _semear_estado(session, perguntas_feitas=6)

    for campo in ("regiao", "vagas"):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA, perguntou=(campo,)),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    # 6 + 1 + 1. O segundo turno ainda passa: sete gastas mais uma sao oito, e
    # a regra diz "nao mais de 8".
    assert await _contador(session) == 8
```

**Se a primeira asserta reprovar porque a entrega trouxe mais de uma mensagem** — o caminho de identificação envia texto próprio em conversa nova —, não relaxe a asserta para "passou perto": mantenha `TEXTO_DO_LIMITE_DE_PERGUNTAS in entregues` e confie no teste seguinte, que é quem garante que a prosa do modelo não saiu.

- [ ] **Step 2: Rode e veja falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_teto_de_perguntas.py -v --tb=short`
Expected: FAIL — o primeiro teste entrega a prosa do modelo em vez do texto do teto, e nenhum handoff nasce.

- [ ] **Step 3: A constante do texto**

Em `src/mobia/domain/agente/turno.py`, junto das outras constantes `TEXTO_*` do topo:

```python
# TEC-149, RN-05.5. Substitui a prosa do modelo no turno em que a pergunta
# seguinte passaria do teto.
#
# **Nao promete que alguem foi avisado, e isso e deliberado.** Criar handoff
# nao notifica ninguem: as cards de notificacao por e-mail e WhatsApp
# (TEC-280 e TEC-281) estao abertas. A TEC-174 escreveu "ja avisei um
# corretor" e teve de reescrever o texto depois, porque nada notificava.
#
# Sem kind proprio, ao contrario de KIND_DO_CRITERIO_AMPLIADO: aquele e
# mensagem ADICIONAL e precisa de kind distinto por causa do
# UNIQUE (message_id, kind). Isto aqui e substituicao, como o
# TEXTO_NEUTRO_DE_SAIDA da moderacao -- nao ha segunda mensagem com que
# colidir.
TEXTO_DO_LIMITE_DE_PERGUNTAS = (
    "Ja perguntei bastante e nao quero virar interrogatorio. "
    "Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui. "
    "Pode deixar que ele entra em contato."
)
```

- [ ] **Step 4: A bandeira, a substituição e a guarda**

Depois da geração e antes do bloco transacional em que a TEC-174 chama `registrar_handoff`:

```python
    # TEC-149, RN-05.5. Depois da geracao, porque depende de `gerada.perguntou`;
    # antes do bloco transacional, porque e ele quem registra o handoff.
    teto_atingido = excedeu_o_teto(
        contexto.estado.perguntas_feitas if contexto.estado is not None else 0,
        len(perguntas_contaveis(gerada.perguntou)),
    )
```

Dentro do bloco transacional, ao lado dos dois `registrar_handoff` que já existem:

```python
        if teto_atingido:
            handoff_do_teto = await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.LIMITE_DE_PERGUNTAS,
            )
```

Declare `handoff_do_teto: HandoffRegistrado | None = None` junto das outras duas declarações, e logue-o **depois** do commit, no mesmo lugar e formato em que os outros dois são logados — `registrar_handoff` não loga, quem loga é este módulo.

A substituição do texto, junto da substituição da moderação:

```python
    if teto_atingido:
        # A prosa do modelo nao sai: ela contem a pergunta que o teto proibe,
        # e nao da para entregar meia pergunta -- a prosa e um texto so.
        # Substituicao em lugar, como a moderacao de saida faz logo acima.
        texto = TEXTO_DO_LIMITE_DE_PERGUNTAS
```

E a guarda do bloco pós-entrega ganha a quinta condição:

```python
    if (
        not desambiguando
        and not saida_bloqueada
        and not citacao_bloqueada
        and not entrega_parcial
        and not teto_atingido
    ):
```

com este comentário acrescentado à lista de razões que já está lá:

```python
        # `not teto_atingido` pela mesma razao das outras quatro: o texto de
        # `gerada` nao foi o que saiu. A pergunta foi SUPRIMIDA, nao feita --
        # marcar ou contar aqui gastaria orcamento do lead por uma pergunta
        # que ele nunca viu, e o proximo turno ja nasceria acima do teto.
```

Dentro desse bloco, ao lado de `marcar_perguntados` e antes do `commit`:

```python
            await contar_perguntas(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                perguntou=gerada.perguntou,
            )
```

Acrescente aos imports do módulo: `contar_perguntas` e `perguntas_contaveis` de `mobia.domain.context.repositorio`, e `excedeu_o_teto` de `mobia.domain.context.qualificacao` (que já é importado para `esta_qualificado`).

- [ ] **Step 5: Rode e veja passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_teto_de_perguntas.py -v --tb=short`
Expected: 4 passed.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_turno_teto_de_perguntas.py
git commit -m "feat(TEC-149): o turno para de perguntar no teto e chama o corretor"
```

---

### Task 6: A garantia da desambiguação e a emenda ao SRS

**Files:**
- Create: `tests/unit/test_desambiguacao_nao_conta_no_teto.py`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (abaixo da RN-05.5, e a tabela de emendas do cabeçalho)

**Interfaces:**
- Consumes: `PerguntaDeDesambiguacao` (já existe).
- Produces: nada que outra task use.

O cenário 2 do Gherkin já é verdade **por construção**: `PerguntaDeDesambiguacao` não tem campo `perguntou`, e `marcar_perguntados`/`contar_perguntas` só recebem `gerada.perguntou`. O teste não faz código novo passar — ele trava a garantia para que reintroduzir `perguntou` naquele schema um dia não a desfaça em silêncio.

- [ ] **Step 1: Escreva o teste**

```python
"""Pergunta de desambiguacao nao conta no teto. TEC-149, cenario 2, D6.

Esta garantia e ESTRUTURAL e nao condicional: a desambiguacao nao tem como
declarar pergunta, entao nao tem como incrementar o contador. O teste existe
para que a estrutura nao mude em silencio -- acrescentar `perguntou` a
`PerguntaDeDesambiguacao` faria o caminho de desambiguacao passar a gastar
orcamento do lead sem que uma linha de `turno.py` mudasse.
"""

import dataclasses

from mobia.domain.agente.schemas import PerguntaDeDesambiguacao


def test_a_desambiguacao_nao_declara_pergunta() -> None:
    campos = {campo.name for campo in dataclasses.fields(PerguntaDeDesambiguacao)}
    assert "perguntou" not in campos, (
        "PerguntaDeDesambiguacao ganhou `perguntou`: o caminho de "
        "desambiguacao passou a poder gastar o teto da RN-05.5, e o cenario 2 "
        "do Gherkin da TEC-149 deixou de valer por construcao. Decida em "
        "codigo se ele conta, em vez de deixar a estrutura decidir."
    )
```

- [ ] **Step 2: Rode e veja passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_desambiguacao_nao_conta_no_teto.py -v --tb=short`
Expected: PASS. **Ele passa de imediato, e isso é esperado** — é guarda de invariante existente, não ciclo TDD.

- [ ] **Step 3: Prove que ele pega alguma coisa**

Acrescente temporariamente `perguntou: tuple[str, ...] = ()` a `PerguntaDeDesambiguacao`, rode o teste, confirme que ele reprova com a mensagem acima, e **desfaça a alteração**. Sem este passo não há evidência nenhuma de que o teste vale.

- [ ] **Step 4: Escreva a emenda ao SRS**

Abaixo da RN-05.5, como item aninhado — nunca reescrevendo o texto de 22/08/2026. O texto da emenda está pronto na seção **Emendas ao SRS** do spec; copie-o de lá. Acrescente também a linha correspondente na tabela de emendas do cabeçalho do SRS: `| E-01 | RN-05.5 | [TEC-149](...) | 14/09/2026 |`.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/unit/test_desambiguacao_nao_conta_no_teto.py docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-149): a RN-05.5 ganha emenda e a desambiguacao ganha guarda"
```

---

## Fechamento

- [ ] **Rode a suíte inteira UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Uma execução verde basta. Se falhar, repita **sobre a mesma árvore** antes de culpar a mudança — é o que separa flake de regressão.

- [ ] **Reconfira os comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Espere `ALTERADO` nos arquivos desta branch. Todo `VIZINHO` em `turno.py`, `repositorio.py` e `qualificacao.py` precisa ser lido: são funções cujo código mudou e cujos comentários não aparecem no diff.

- [ ] **Abra o PR e comente na card**

PR contra `main`. Depois, comentário na [TEC-149](https://eduardodurieuxlopes.atlassian.net/browse/TEC-149) e card para **Em análise** — não para Feito, que quem mergeia é quem fecha. O comentário registra, no mínimo: a emenda E-01 à RN-05.5 nomeada; a consequência de o teto ser permanente (D1) e não ter válvula de saída (L2); que o teto morde entre 7 e 8 com duas perguntas num turno (D4); e que **nada notifica o corretor** — o handoff nasce e ninguém é avisado enquanto TEC-280 e TEC-281 não existirem (L1).

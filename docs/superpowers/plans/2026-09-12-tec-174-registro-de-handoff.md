# TEC-174 — Registro de handoff: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar a tabela `handoffs`, a função que a escreve com deduplicação, e a fiação dos três gatilhos que hoje têm como disparar.

**Architecture:** Módulo de domínio novo em `src/mobia/domain/handoff/`, no molde de `domain/followup/` e `domain/moderacao/`. A escrita é um `INSERT ... ON CONFLICT DO UPDATE` sobre um índice único parcial (`WHERE status = 'PENDENTE'`), então a deduplicação é invariante de banco e não disciplina de consulta. `registrar_handoff` recebe **sessão** e deixa o commit para quem chama, como `registrar_recalculo` — é o que põe o handoff na mesma transação do recálculo no gatilho `QUENTE`.

**Tech Stack:** Python 3.13, SQLAlchemy 2 async, asyncpg, Alembic, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-12-tec-174-registro-de-handoff-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Gates antes de cada commit:** `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `ruff format --check` no mesmo escopo, e `mypy`.
- **Suíte inteira:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile` (~49s). Um arquivo só: sem `-n`.
- **`tests/unit/` não pode tocar banco** — nem `session`, nem `session_factory`, nem `client`, nem `get_sessionmaker()`. A fixture `banco_limpo` sai cedo lá, e um teste de unidade que peça sessão quebra de um jeito que não aponta para a causa.
- **Comentário desatualizado é defeito.** Antes do PR: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`.
- **Nomes de enum são vocabulário de banco.** Trocar um valor depois custa migration; escolha o nome uma vez.

---

### Task 1: A tabela, o modelo e o índice parcial

**Files:**
- Create: `alembic/versions/0023_handoffs.py`
- Create: `src/mobia/domain/handoff/__init__.py` (vazio)
- Create: `src/mobia/domain/handoff/models.py`
- Modify: `tests/conftest.py` — acrescentar `"handoffs"` a `TABELAS`
- Test: `tests/integration/test_handoff_schema.py`

**Interfaces:**
- Consumes: `Base` de `mobia.domain.messages.models`
- Produces: `Handoff` (modelo ORM, `__tablename__ = "handoffs"`); índice `uq_handoffs_conversa_pendente`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""O schema de `handoffs`: o que so o Postgres prova."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _linha(status: str = "PENDENTE", conversa: str = CONVERSA) -> Handoff:
    return Handoff(
        id=uuid.uuid4(),
        channel=CANAL,
        conversation_key=conversa,
        gatilho="LEAD_QUENTE",
        etiqueta="lead-quente",
        prioridade="NORMAL",
        status=status,
        criado_em=datetime.now(UTC),
        atualizado_em=datetime.now(UTC),
    )


async def test_a_tabela_aceita_uma_linha_pendente(session: AsyncSession) -> None:
    session.add(_linha())
    await session.commit()
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 1


async def test_dois_pendentes_na_mesma_conversa_sao_recusados_pelo_banco(
    session: AsyncSession,
) -> None:
    """O UNIQUE parcial e a garantia da deduplicacao, nao a consulta.

    Sem ele, dois turnos concorrentes do mesmo lead criam dois handoffs -- e a
    concorrencia e prevista, nao hipotetica: `turno.py` declara que
    `lead.esquentou` reemite para o MESMO lead desde a TEC-148.
    """
    session.add(_linha())
    await session.commit()
    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_um_concluido_nao_bloqueia_um_pendente_novo(session: AsyncSession) -> None:
    """O indice so olha para PENDENTE.

    Um lead atendido meses atras que volta merece handoff novo -- por isso o
    `postgresql_where`, e nao um UNIQUE simples sobre o par.
    """
    session.add(_linha(status="CONCLUIDO"))
    await session.commit()
    session.add(_linha())
    await session.commit()
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 2


async def test_gatilhos_adicionais_nasce_vazio_e_nao_nulo(session: AsyncSession) -> None:
    """`array_append` sobre NULL funciona, mas o default vazio evita a duvida."""
    linha = _linha()
    session.add(linha)
    await session.commit()
    valor = await session.scalar(
        text("SELECT gatilhos_adicionais FROM handoffs WHERE id = :i"), {"i": linha.id}
    )
    assert valor == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.handoff'`

- [ ] **Step 3: Escrever a migration**

Criar `alembic/versions/0023_handoffs.py`:

```python
"""o registro de handoff: o ponto de juncao entre o agente e o time humano

TEC-174, RF-16 e RN-16.1.

**Chaveada pelo par `(channel, conversation_key)`.** O modelo da secao 5 do SRS
pede `conversa_id UUID FK -> Conversa`, e `Conversa` nao existe: a entidade foi
deferida para a TEC-130, e `lead_qualification`, `followups`, `optout_events`,
`moderation_events` e `recomendacoes` usam todas o par. A emenda E-03 da secao 5
declara a divergencia.

**Primeira tabela mutavel do repo.** `followups`, `optout_events` e
`moderation_events` sao append-only. Esta nao pode ser: a regra de deduplicacao
da card manda ATUALIZAR o handoff aberto em vez de criar outro. Dai
`atualizado_em`, que as append-only nao tem.

**O UNIQUE e PARCIAL, e e o coracao da card.** `WHERE status = 'PENDENTE'` faz
"um handoff aberto por conversa" ser invariante de schema em vez de disciplina
de consulta -- e deixa um handoff CONCLUIDO nao bloquear um novo, porque um lead
atendido meses atras que volta merece handoff proprio. E o primeiro indice
parcial do repo.

**`corretor_id` sem FK, e sem tabela alvo.** `corretores` nasce na TEC-196; a
restricao entra junto com ela. E ausencia de FK PROVISORIA, ao contrario da de
`moderation_events` e `lead_score_audit`, que e permanente e tem outra causa --
la a FK e dispensada porque a retencao da trilha nao pode ser encurtada pela
cascata da limpeza de `messages`. Ver a emenda E-02 da RN-16.1.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "handoffs",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("gatilho", sa.String(32), nullable=False),
        sa.Column("etiqueta", sa.String(32), nullable=False),
        sa.Column("prioridade", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("corretor_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column(
            "gatilhos_adicionais",
            sa.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_handoffs"),
        sa.CheckConstraint("prioridade IN ('ALTA', 'NORMAL')", name="ck_handoffs_prioridade"),
        sa.CheckConstraint(
            "status IN ('PENDENTE', 'ACEITO', 'ESCALADO', 'CONCLUIDO')",
            name="ck_handoffs_status",
        ),
    )
    op.create_index(
        "uq_handoffs_conversa_pendente",
        "handoffs",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDENTE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_handoffs_conversa_pendente", table_name="handoffs")
    op.drop_table("handoffs")
```

- [ ] **Step 4: Escrever o modelo**

Criar `src/mobia/domain/handoff/__init__.py` vazio e `src/mobia/domain/handoff/models.py`:

```python
"""O handoff: a tarefa que o lead pronto vira para o corretor.

TEC-174. Ver `alembic/versions/0023_handoffs.py` para o porque do par como
identidade, do UNIQUE parcial e do `corretor_id` sem FK.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # O gatilho que CRIOU o handoff. Os que chegarem depois vao para
    # `gatilhos_adicionais` -- a etiqueta nao muda, porque e por ela que a fila
    # do dashboard e filtrada (TEC-192) e etiqueta movel embaralha filtro salvo.
    gatilho: Mapped[str] = mapped_column(String(32), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(32), nullable=False)

    # Escala para ALTA e nunca desce -- emenda E-01 da RN-16.1. Sem isso, um
    # pedido explicito de humano sobre um handoff aberto ficaria NORMAL, o que
    # contraria a RN-04.6.
    prioridade: Mapped[str] = mapped_column(String(8), nullable=False)

    # Nasce e permanece PENDENTE nesta card. ACEITO/ESCALADO vem da TEC-178 e
    # CONCLUIDO da TEC-179 -- o enum nasce completo porque mudar valor de enum
    # depois custa migration, e o `IN` do CHECK e o unico lugar a mexer.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # Nulavel e sem FK ate a TEC-196 criar `corretores`. Nada escreve aqui hoje.
    corretor_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    gatilhos_adicionais: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("prioridade IN ('ALTA', 'NORMAL')", name="ck_handoffs_prioridade"),
        CheckConstraint(
            "status IN ('PENDENTE', 'ACEITO', 'ESCALADO', 'CONCLUIDO')",
            name="ck_handoffs_status",
        ),
        Index(
            "uq_handoffs_conversa_pendente",
            "channel",
            "conversation_key",
            unique=True,
            postgresql_where=text("status = 'PENDENTE'"),
        ),
    )
```

- [ ] **Step 5: Acrescentar `handoffs` a `TABELAS`**

Em `tests/conftest.py`, no fim da tupla `TABELAS`, antes do `)`:

```python
    # TEC-174. Mutavel, ao contrario das append-only acima: o UNIQUE parcial
    # sobre status='PENDENTE' faz um handoff de um teste bloquear a criacao no
    # proximo, e a falha apareceria so a partir do segundo teste do arquivo --
    # o mesmo sintoma que `imoveis` ja registra.
    "handoffs",
```

- [ ] **Step 6: Aplicar a migration e rodar**

Run: `./.venv/Scripts/python.exe -m alembic upgrade head` e depois `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_schema.py -q`
Expected: PASS, 4 testes

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0023_handoffs.py src/mobia/domain/handoff/ tests/conftest.py tests/integration/test_handoff_schema.py
git commit -m "feat(TEC-174): a tabela de handoffs, com a deduplicacao como invariante de schema"
```

---

### Task 2: O vocabulário — gatilho, etiqueta e prioridade

**Files:**
- Create: `src/mobia/domain/handoff/vocabulario.py`
- Test: `tests/unit/test_handoff_vocabulario.py`

**Interfaces:**
- Produces: `Gatilho`, `Prioridade` e `Status` (StrEnum), `ETIQUETA_DE: dict[Gatilho, str]`, `PRIORIDADE_DE: dict[Gatilho, Prioridade]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/test_handoff_vocabulario.py` — **sem banco**, este arquivo roda sem Docker:

```python
"""O vocabulario do handoff: gatilho, etiqueta, prioridade.

Nao toca banco. Ver o conftest raiz: `tests/unit/` sai cedo de `banco_limpo`.
"""

from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho, Prioridade


def test_todo_gatilho_tem_etiqueta_e_prioridade() -> None:
    """Os dois mapas cobrem o enum inteiro.

    Um gatilho sem etiqueta so falharia em producao, no instante do handoff --
    e os tres gatilhos ainda sem fiacao (TEC-143, TEC-149, TEC-170) nao tem
    outro teste que os exercite.
    """
    for gatilho in Gatilho:
        assert gatilho in ETIQUETA_DE
        assert gatilho in PRIORIDADE_DE


def test_as_etiquetas_do_gherkin_da_card() -> None:
    assert ETIQUETA_DE[Gatilho.LEAD_QUENTE] == "lead-quente"
    assert ETIQUETA_DE[Gatilho.PEDIDO_DE_HUMANO] == "pedido-humano"
    assert ETIQUETA_DE[Gatilho.VENDA_IMOVEL] == "venda-imovel"
    assert ETIQUETA_DE[Gatilho.LIMITE_DE_PERGUNTAS] == "qualificacao-parcial"


def test_so_o_pedido_de_humano_nasce_alta() -> None:
    """RN-16.1: pedido explicito alto, os demais normais."""
    altos = [g for g in Gatilho if PRIORIDADE_DE[g] is Prioridade.ALTA]
    assert altos == [Gatilho.PEDIDO_DE_HUMANO]


def test_as_etiquetas_cabem_na_coluna() -> None:
    """`etiqueta` e String(32). Estourar so apareceria no INSERT."""
    assert all(len(e) <= 32 for e in ETIQUETA_DE.values())
    assert all(len(g.value) <= 32 for g in Gatilho)

```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_vocabulario.py -q`
Expected: FAIL — `ModuleNotFoundError: ... vocabulario`

- [ ] **Step 3: Escrever o vocabulário**

Criar `src/mobia/domain/handoff/vocabulario.py`:

```python
"""Gatilho, etiqueta e prioridade do handoff.

Modulo sem I/O de proposito: e o que deixa a regra ser testada em
`tests/unit/`, sem Postgres de pe.
"""

from enum import StrEnum


class Gatilho(StrEnum):
    """Os gatilhos da RN-16.1.

    **Nasce completo, com fiacao para tres.** Acrescentar valor a este enum
    depois custa migration (o `IN` do CHECK em `handoffs.status` e irmao deste
    problema); acrescentar um CHAMADOR nao custa nada. TEC-143, TEC-149 e
    TEC-170 chegam e so chamam `registrar_handoff` com o gatilho que ja existe.

    A RN-16.1 junta VENDER_IMOVEL e SUPORTE_CONTRATO num item so, e aqui eles
    sao dois: o Gherkin da card so nomeia a etiqueta `venda-imovel`, e as duas
    intencoes viram filas diferentes para o corretor -- quem quer vender um
    imovel e quem tem duvida de contrato vigente nao sao o mesmo trabalho.
    """

    LEAD_QUENTE = "LEAD_QUENTE"
    AGENDAMENTO_CONFIRMADO = "AGENDAMENTO_CONFIRMADO"
    PEDIDO_DE_HUMANO = "PEDIDO_DE_HUMANO"
    VENDA_IMOVEL = "VENDA_IMOVEL"
    SUPORTE_CONTRATO = "SUPORTE_CONTRATO"
    LIMITE_DE_PERGUNTAS = "LIMITE_DE_PERGUNTAS"
    ERRO_DO_AGENTE = "ERRO_DO_AGENTE"


class Prioridade(StrEnum):
    ALTA = "ALTA"
    NORMAL = "NORMAL"


class Status(StrEnum):
    """Nesta card so PENDENTE e escrito. Ver o modelo."""

    PENDENTE = "PENDENTE"
    ACEITO = "ACEITO"
    ESCALADO = "ESCALADO"
    CONCLUIDO = "CONCLUIDO"


# A etiqueta e o filtro do corretor no dashboard (TEC-192), e por isso ela e do
# gatilho que CRIOU o handoff e nao muda quando outro chega.
ETIQUETA_DE: dict[Gatilho, str] = {
    Gatilho.LEAD_QUENTE: "lead-quente",
    Gatilho.AGENDAMENTO_CONFIRMADO: "agendamento-confirmado",
    Gatilho.PEDIDO_DE_HUMANO: "pedido-humano",
    Gatilho.VENDA_IMOVEL: "venda-imovel",
    Gatilho.SUPORTE_CONTRATO: "suporte-contrato",
    Gatilho.LIMITE_DE_PERGUNTAS: "qualificacao-parcial",
    Gatilho.ERRO_DO_AGENTE: "erro-do-agente",
}

PRIORIDADE_DE: dict[Gatilho, Prioridade] = {
    Gatilho.LEAD_QUENTE: Prioridade.NORMAL,
    Gatilho.AGENDAMENTO_CONFIRMADO: Prioridade.NORMAL,
    # O unico ALTA da RN-16.1.
    Gatilho.PEDIDO_DE_HUMANO: Prioridade.ALTA,
    Gatilho.VENDA_IMOVEL: Prioridade.NORMAL,
    Gatilho.SUPORTE_CONTRATO: Prioridade.NORMAL,
    Gatilho.LIMITE_DE_PERGUNTAS: Prioridade.NORMAL,
    Gatilho.ERRO_DO_AGENTE: Prioridade.NORMAL,
}


# A escalada da emenda E-01 -- prioridade de handoff aberto sobe e nunca desce --
# NAO mora aqui. Ela e um `CASE` dentro do `ON CONFLICT DO UPDATE` de
# `repositorio.py`, porque quem decide precisa ver a linha existente, e o Python
# nao a ve naquele caminho. Uma gemea em Python seria segunda implementacao da
# mesma regra, livre para divergir em silencio da que roda de verdade.
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_vocabulario.py -q`
Expected: PASS, 4 testes

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/handoff/vocabulario.py tests/unit/test_handoff_vocabulario.py
git commit -m "feat(TEC-174): o vocabulario do handoff: gatilho, etiqueta e prioridade"
```

---

### Task 3: `registrar_handoff` com deduplicação

**Files:**
- Create: `src/mobia/domain/handoff/repositorio.py`
- Test: `tests/integration/test_handoff_repositorio.py`

**Interfaces:**
- Consumes: `Handoff` (Task 1); `Gatilho`, `Prioridade`, `Status`, `ETIQUETA_DE`, `PRIORIDADE_DE`, `escalada` (Task 2)
- Produces: `async def registrar_handoff(session: AsyncSession, *, channel: str, conversation_key: str, gatilho: Gatilho) -> bool` — devolve `True` quando criou linha nova, `False` quando atualizou uma aberta. **Não commita.**

- [ ] **Step 1: Escrever o teste que falha**

```python
"""A deduplicacao do handoff: o que so o Postgres prova."""

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _linhas(session: AsyncSession) -> list[dict]:
    resultado = await session.execute(
        text(
            "SELECT gatilho, etiqueta, prioridade, status, gatilhos_adicionais "
            "FROM handoffs ORDER BY criado_em"
        )
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_o_gatilho_quente_cria_com_etiqueta_e_prioridade(session: AsyncSession) -> None:
    criou = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    assert criou is True
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "lead-quente"
    assert linhas[0]["prioridade"] == "NORMAL"
    assert linhas[0]["status"] == "PENDENTE"


async def test_gatilho_repetido_nao_duplica_e_acumula(session: AsyncSession) -> None:
    """Cenario 2 do Gherkin."""
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    criou = await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.VENDA_IMOVEL
    )
    await session.commit()
    assert criou is False
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilhos_adicionais"] == ["VENDA_IMOVEL"]
    # A etiqueta e do gatilho que criou, e nao muda.
    assert linhas[0]["etiqueta"] == "lead-quente"


async def test_pedido_de_humano_escala_a_prioridade_de_um_aberto(session: AsyncSession) -> None:
    """Emenda E-01 da RN-16.1, e o caso que a RN-04.6 exige."""
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.PEDIDO_DE_HUMANO
    )
    await session.commit()
    linhas = await _linhas(session)
    assert linhas[0]["prioridade"] == "ALTA"


async def test_a_prioridade_nunca_desce(session: AsyncSession) -> None:
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.PEDIDO_DE_HUMANO
    )
    await session.commit()
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    linhas = await _linhas(session)
    assert linhas[0]["prioridade"] == "ALTA"


async def test_conversas_diferentes_tem_handoffs_diferentes(session: AsyncSession) -> None:
    await registrar_handoff(
        session, channel=CANAL, conversation_key=CONVERSA, gatilho=Gatilho.LEAD_QUENTE
    )
    await registrar_handoff(
        session, channel=CANAL, conversation_key="5511900000000", gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    assert len(await _linhas(session)) == 2


async def test_duas_escritas_concorrentes_produzem_uma_linha(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """A corrida e prevista: `lead.esquentou` reemite para o mesmo lead.

    Duas sessoes de verdade, e nao duas chamadas em sequencia -- o que se quer
    provar e que quem arbitra e o indice parcial, nao a ordem do codigo.
    """

    async def escrever(gatilho: Gatilho) -> None:
        async with session_factory() as propria:
            await registrar_handoff(
                propria, channel=CANAL, conversation_key=CONVERSA, gatilho=gatilho
            )
            await propria.commit()

    await asyncio.gather(
        escrever(Gatilho.LEAD_QUENTE),
        escrever(Gatilho.VENDA_IMOVEL),
        return_exceptions=True,
    )
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_repositorio.py -q`
Expected: FAIL — `ImportError: cannot import name 'registrar_handoff'`

- [ ] **Step 3: Escrever o repositório**

Criar `src/mobia/domain/handoff/repositorio.py`:

```python
"""A escrita do handoff, com a deduplicacao que a RN-16.1 exige."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import case, func, literal, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho, Prioridade, Status

log = structlog.get_logger(__name__)


async def registrar_handoff(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    gatilho: Gatilho,
) -> bool:
    """Cria o handoff da conversa, ou acumula o gatilho no que ja esta aberto.

    Devolve `True` quando criou linha nova e `False` quando atualizou uma
    aberta. **Nao commita** -- o commit e de quem chama, como em
    `registrar_recalculo`. E isso que poe o handoff na MESMA transacao do
    recalculo no gatilho QUENTE: ou o lead vira QUENTE e tem handoff, ou nem
    uma coisa nem outra. O estado intermediario -- lead quente, ninguem
    avisado -- e exatamente o que a card existe para impedir.

    **Um statement, e nao um SELECT seguido de INSERT.** A corrida e prevista:
    `turno.py` declara que `lead.esquentou` reemite para o MESMO lead desde a
    TEC-148, e a suite roda com oito workers. Quem arbitra e o indice parcial
    `uq_handoffs_conversa_pendente`, nao a ordem do codigo.
    """
    agora = datetime.now(UTC)
    prioridade = PRIORIDADE_DE[gatilho]

    statement = pg_insert(Handoff).values(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        gatilho=gatilho.value,
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=prioridade.value,
        status=Status.PENDENTE.value,
        gatilhos_adicionais=[],
        criado_em=agora,
        atualizado_em=agora,
    )

    resultado = await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            index_where=text("status = 'PENDENTE'"),
            set_={
                "gatilhos_adicionais": func.array_append(
                    Handoff.gatilhos_adicionais, literal(gatilho.value)
                ),
                # A escalada de `vocabulario.escalada`, em SQL: o Python nao ve
                # a linha existente neste caminho, e ler antes para decidir
                # devolveria a corrida que este statement existe para evitar.
                "prioridade": case(
                    (
                        literal(prioridade.value) == Prioridade.ALTA.value,
                        literal(Prioridade.ALTA.value),
                    ),
                    else_=Handoff.prioridade,
                ),
                "atualizado_em": agora,
            },
        ).returning(Handoff.criado_em)
    )

    criado_em = resultado.scalar_one()
    criou = criado_em == agora
    log.info(
        "handoff.criado" if criou else "handoff.gatilho_adicional",
        channel=channel,
        gatilho=gatilho.value,
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=prioridade.value,
    )
    return criou
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_repositorio.py -q`
Expected: PASS, 6 testes

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/handoff/repositorio.py tests/integration/test_handoff_repositorio.py
git commit -m "feat(TEC-174): o handoff nasce deduplicado pelo indice, nao pela consulta"
```

---

### Task 4: O gatilho `QUENTE`, na transação do recálculo

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — a condição do `lead.esquentou` (hoje por volta da linha 836) e o comentário das linhas 822-827
- Test: `tests/integration/test_handoff_no_turno.py`

**Interfaces:**
- Consumes: `registrar_handoff` (Task 3), `Gatilho` (Task 2)

- [ ] **Step 1: Escrever o teste que falha**

```python
"""A fiacao do handoff dentro do turno."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.schemas import Intencao


async def _handoffs(session: AsyncSession) -> list[dict]:
    resultado = await session.execute(
        text("SELECT gatilho, etiqueta, prioridade FROM handoffs ORDER BY criado_em")
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_lead_que_esquenta_ganha_handoff(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-06.5 ganha destino: o comentario de `turno.py` dizia que nao havia.

    "quero agendar visita" e o gatilho da RN-06.3 que forca QUENTE num turno so.
    E o mesmo texto que `test_temperatura_no_turno.py` usa -- reusado de
    proposito: se o gatilho mudar, os dois arquivos falham juntos e ninguem
    descobre pela metade.
    """
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilho"] == "LEAD_QUENTE"
    assert linhas[0]["etiqueta"] == "lead-quente"


async def test_lead_que_nao_esquenta_nao_ganha_handoff(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )
    assert await _handoffs(session) == []
```

As cinco fixtures do conftest raiz sao **factories**, e nao instancias: chame
`classificador_fake(Intencao.COMPRA)`, `outbound_fake()`, `resumidor_fake()` e
`contador_fake()`. Ver `tests/integration/test_temperatura_no_turno.py:319`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_no_turno.py -q`
Expected: FAIL — `UndefinedTable` não; a tabela existe. Falha na asserção: `len(linhas) == 1` com `linhas == []`

- [ ] **Step 3: Fiar o gatilho — DENTRO do bloco de sessão, não junto ao log**

**Leia este passo inteiro antes de editar.** O ponto óbvio é errado.

A condição do `lead.esquentou` está por volta da linha 836, **fora** do bloco `async with session_factory() as session:`, que abre na 719 e fecha com `await session.commit()` na **756**. Escrever o handoff ali exigiria sessão nova — e a D8 do desenho exige a mesma transação do recálculo: *"ou o lead vira QUENTE e tem handoff, ou nem uma coisa nem outra."*

Então a escrita e o log ficam em lados opostos do commit.

**A escrita entra no bloco**, logo depois do `registrar_recalculo` da linha 750 e antes do `await session.commit()` da 756:

```python
        recalculo = await registrar_recalculo(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            gatilhos=gatilhos,
        )
        # TEC-174. Aqui dentro, e nao junto ao `lead.esquentou` la embaixo: este
        # `commit` e o que torna indivisivel "o lead esquentou" e "o corretor
        # tem tarefa". Do lado de fora seria sessao nova, e existiria a janela
        # em que o lead esta QUENTE e ninguem foi avisado -- que e o "lead
        # qualificado morre no banco" que a card existe para impedir.
        if (
            recalculo is not None
            and recalculo.anterior is not Temperatura.QUENTE
            and recalculo.temperatura is Temperatura.QUENTE
        ):
            await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.LEAD_QUENTE,
            )
        await session.commit()
```

**O `log.info("lead.esquentou")` NÃO se move.** Ele fica onde está, depois do commit, e o comentário das linhas 819-820 diz por quê com todas as letras: *"Depois do commit, como `lead.qualificado`: logar uma transicao que o rollback desfez e mentir para quem le o log."* Mover o log para dentro do bloco reintroduziria exatamente o defeito que aquele comentário previne.

A condição aparece duas vezes no arquivo depois desta mudança — uma para escrever, outra para logar. É duplicação deliberada, e o comentário acima registra a razão: as duas metades pertencem a lados opostos do commit.

- [ ] **Step 4: Corrigir o comentário que passou a mentir**

O bloco das linhas 822-827 afirma que o handoff *"nao existe -- nao ha epico, nao ha consumidor"*. Passou a existir. Substituir esse parágrafo por:

```python
    # **A notificacao da RN-06.5 continua sem existir, mas o registro dela nao.**
    # Desde a TEC-174 a travessia para QUENTE cria um `handoff` na MESMA
    # transacao deste recalculo -- ou o lead vira QUENTE e tem handoff, ou nem
    # uma coisa nem outra. O que falta e a entrega ao corretor (TEC-177): os 60
    # segundos da regra seguem triviais porque o evento e sincrono no turno.
```

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_no_turno.py tests/integration/test_turno.py -q`
Expected: PASS — o segundo arquivo entra para pegar regressão no turno

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_handoff_no_turno.py
git commit -m "feat(TEC-174): o lead que esquenta ganha handoff na mesma transacao"
```

---

### Task 5: O gatilho de intenção

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — após a classificação
- Modify: `src/mobia/domain/context/qualificacao.py:19` — o comentário que aponta para um destino que agora existe
- Test: `tests/integration/test_handoff_no_turno.py` (acrescentar)

**Interfaces:**
- Consumes: `registrar_handoff` (Task 3), `Gatilho` (Task 2), `Intencao` de `mobia.domain.agente.schemas`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/integration/test_handoff_no_turno.py`:

```python
async def test_vender_imovel_cria_handoff_e_o_lead_ainda_recebe_resposta(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-03.4 ganha destino.

    O lead CONTINUA recebendo a resposta do turno: silenciar e a RN-16.4, que e
    a TEC-179. Esta card so registra -- e a segunda asserta e a nao-regressao
    dessa decisao, nao enfeite.
    """
    entregador = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )
    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilho"] == "VENDA_IMOVEL"
    assert entregador.entregues, "o lead deixou de receber resposta"


async def test_suporte_contrato_tem_etiqueta_propria(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Fila diferente da de quem quer vender."""
    await rodar_turno(
        session,
        classificador_fake(Intencao.SUPORTE_CONTRATO),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )
    linhas = await _handoffs(session)
    assert linhas[0]["etiqueta"] == "suporte-contrato"
```

`outbound_fake()` devolve um `OutboundFake` que acumula em `.entregues`
(`list[str]`) e `.payloads` (`list[dict]`) — guarde a instancia numa variavel
quando for assertar sobre ela.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_no_turno.py -q`
Expected: FAIL na asserção `len(linhas) == 1`

- [ ] **Step 3: Fiar o gatilho**

Em `turno.py`, junto ao bloco onde a intenção classificada já é usada, dentro da transação que grava o estado do turno:

```python
# RN-03.4: estas duas intencoes nao sao trabalho de SDR, e o comentario de
# `qualificacao.py` ja dizia que elas vao "direto para handoff" -- um destino
# que so passou a existir na TEC-174. O lead segue recebendo a resposta deste
# turno: silenciar e a RN-16.4, que e a TEC-179.
_GATILHO_DA_INTENCAO = {
    Intencao.VENDER_IMOVEL: Gatilho.VENDA_IMOVEL,
    Intencao.SUPORTE_CONTRATO: Gatilho.SUPORTE_CONTRATO,
}

if (gatilho_da_intencao := _GATILHO_DA_INTENCAO.get(gerada.intencao)) is not None:
    await registrar_handoff(
        session,
        channel=message.channel,
        conversation_key=message.conversation_key,
        gatilho=gatilho_da_intencao,
    )
```

O dicionário vai no topo do módulo, junto às outras constantes; o `if` vai no corpo.

- [ ] **Step 4: Corrigir o comentário de `qualificacao.py`**

A linha 19 diz *"VENDER_IMOVEL e SUPORTE_CONTRATO vao direto para handoff"* — verdade que não tinha destino e agora tem. Acrescentar ao fim daquele parágrafo:

```python
# Desde a TEC-174 esse handoff existe de verdade: `turno.py` chama
# `registrar_handoff` com VENDA_IMOVEL ou SUPORTE_CONTRATO, que sao filas
# diferentes para o corretor.
```

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_no_turno.py tests/integration/test_turno.py -q`
Expected: PASS

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py src/mobia/domain/context/qualificacao.py tests/integration/test_handoff_no_turno.py
git commit -m "feat(TEC-174): venda e suporte de contrato viram handoff, em filas separadas"
```

---

### Task 6: O gatilho de erro irrecuperável, e o aviso ao lead

**Files:**
- Modify: `src/mobia/workers/jobs/process_message.py` — `_marcar_falha` e o `except Exception`
- Test: `tests/integration/test_handoff_por_erro.py`

**Interfaces:**
- Consumes: `registrar_handoff` (Task 3), `Gatilho` (Task 2)
- Produces: `_marcar_falha(...) -> int` — passa a devolver o novo valor de `attempts`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""O handoff por erro irrecuperavel, e o aviso que vai com ele."""

import asyncio

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message


async def _total(session: AsyncSession) -> int:
    return await session.scalar(text("SELECT count(*) FROM handoffs")) or 0


async def test_falha_antes_do_teto_nao_cria_handoff(
    session, semear_entrada, processar_com_turno_que_falha
) -> None:
    """Retentar ainda pode resolver: encaminhar aqui seria alarme falso."""
    linha = await semear_entrada(session)
    with pytest.raises(RuntimeError):
        await processar_com_turno_que_falha(linha)
    assert await _total(session) == 0


async def test_falha_que_atinge_o_teto_cria_handoff(
    session, semear_entrada, processar_com_turno_que_falha, settings
) -> None:
    linha = await semear_entrada(session)
    await session.execute(
        update(Message)
        .where(Message.id == linha.id)
        .values(attempts=settings.sweep_max_attempts - 1)
    )
    await session.commit()
    with pytest.raises(RuntimeError):
        await processar_com_turno_que_falha(linha)
    resultado = await session.execute(text("SELECT gatilho, etiqueta FROM handoffs"))
    linhas = [dict(item) for item in resultado.mappings()]
    assert len(linhas) == 1
    assert linhas[0]["gatilho"] == "ERRO_DO_AGENTE"
    assert linhas[0]["etiqueta"] == "erro-do-agente"


async def test_aviso_quebrado_nao_desfaz_o_handoff(
    session, semear_entrada, processar_com_turno_que_falha, settings
) -> None:
    """O corretor ser avisado nao pode depender de o lead ter sido avisado."""
    linha = await semear_entrada(session)
    await session.execute(
        update(Message)
        .where(Message.id == linha.id)
        .values(attempts=settings.sweep_max_attempts - 1)
    )
    await session.commit()
    with pytest.raises(RuntimeError):
        await processar_com_turno_que_falha(linha, outbound_quebrado=True)
    assert await _total(session) == 1


async def test_cancelamento_nao_cria_handoff(
    session, semear_entrada, processar_com_turno_que_falha, settings
) -> None:
    """Desligamento limpo nao e falha do agente.

    A mensagem volta para a fila e o sweeper a recupera. Handoff aqui
    encaminharia ao corretor um lead que so pegou um deploy no meio.
    """
    linha = await semear_entrada(session)
    await session.execute(
        update(Message)
        .where(Message.id == linha.id)
        .values(attempts=settings.sweep_max_attempts - 1)
    )
    await session.commit()
    with pytest.raises(asyncio.CancelledError):
        await processar_com_turno_que_falha(linha, erro=asyncio.CancelledError())
    assert await _total(session) == 0
```

`processar_com_turno_que_falha` e uma fixture **deste arquivo**, nao do conftest
raiz — so ele a usa. Ela chama `process_message` com um `ctx` cujo
`classificador` levanta o erro pedido. Copie o helper `_ctx` de
`tests/integration/test_cancelamento_do_worker.py:54`, que ja monta as seis
chaves (`session_factory`, `outbound`, `classificador`, `resumidor`, `contador`,
`moderador`); para o caso do aviso quebrado, passe `OutboundFake(get_sessionmaker(),
erro=EnvioRecusado())`, que e o parametro que o proprio fake ja aceita.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_por_erro.py -q`
Expected: FAIL — a fixture não existe ainda; depois de criada, falha na asserção do segundo teste

- [ ] **Step 3: Fazer `_marcar_falha` devolver `attempts`**

```python
async def _marcar_falha(
    session_factory: async_sessionmaker[AsyncSession], identifier: uuid.UUID, detalhe: str
) -> int:
    """Fecha a linha como FAILED, conta a tentativa e devolve o novo total.

    Nao loga: os dois chamadores emitem eventos diferentes de proposito, e o
    que eles compartilham e so a escrita.

    **Devolve o total desde a TEC-174.** O incremento e expressao SQL, entao
    sem o `returning` ninguem em Python sabe quantas tentativas ja houve -- e
    "irrecuperavel" e a falha que ESGOTA as tentativas, nao qualquer falha.
    """
    async with session_factory() as session:
        resultado = await session.execute(
            update(Message)
            .where(Message.id == identifier)
            .values(
                status=MessageStatus.FAILED,
                attempts=Message.attempts + 1,
                last_error=detalhe,
            )
            .returning(Message.attempts)
        )
        await session.commit()
        return resultado.scalar_one()
```

- [ ] **Step 4: Criar o handoff quando as tentativas esgotam**

No `except Exception` — e **só** nele, nunca no `except asyncio.CancelledError`:

```python
    except Exception as exc:
        detalhe = _detalhe_do_erro(exc)
        tentativas = await _marcar_falha(session_factory, identifier, detalhe)
        log.warning("message.failed", message_id=message_id, error=detalhe)
        if tentativas >= get_settings().sweep_max_attempts:
            await _encaminhar_por_erro(session_factory, outbound, linha)
        raise
```

E a função, no mesmo módulo:

```python
async def _encaminhar_por_erro(
    session_factory: async_sessionmaker[AsyncSession],
    outbound: OutboundPort,
    message: Message,
) -> None:
    """Cria o handoff do erro irrecuperavel e avisa o lead, nessa ordem.

    **Sessao propria**: a do turno morreu com a excecao.

    **Nada daqui pode escapar.** Uma excecao neste bloco SUBSTITUIRIA o erro
    original do turno e apagaria a causa real da falha -- e o mesmo argumento
    que o `except asyncio.CancelledError` deste arquivo ja faz para si.

    **Handoff primeiro, aviso depois**: o turno falhou, entao nao se sabe se o
    `outbound` responde. Se o aviso falhar, o handoff PERMANECE -- o corretor
    ser avisado nao pode depender de o lead ter sido avisado.
    """
    try:
        async with session_factory() as session:
            await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.ERRO_DO_AGENTE,
            )
            await session.commit()
    except Exception as falha:
        log.error(
            "handoff.nao_registrado",
            message_id=str(message.id),
            reason=type(falha).__name__,
        )
        return

    try:
        await outbound.send(message.id, KIND_DO_AVISO_DE_ERRO, {"texto": TEXTO_DO_AVISO_DE_ERRO})
    except Exception as falha:
        log.warning(
            "handoff.aviso_nao_entregue",
            message_id=str(message.id),
            reason=type(falha).__name__,
        )
```

Com as duas constantes no topo do módulo:

```python
# String fixa, sem id dentro, pelo mesmo argumento de idempotencia que os KINDs
# de `turno.py` registram: kind que muda entre retentativas perde a dedup da
# reserva justamente quando ela importa. A coluna e String(32); isto tem 14.
KIND_DO_AVISO_DE_ERRO = "aviso_de_erro"

# Nao promete prazo nem explica a falha: o lead nao tem o que fazer com
# "timeout do provedor", e prometer horario e promessa que esta card nao tem
# como cumprir -- a alocacao de corretor e a TEC-166.
TEXTO_DO_AVISO_DE_ERRO = (
    "Tive um problema tecnico aqui e nao consegui seguir. "
    "Ja avisei um corretor, que vai continuar com voce por aqui."
)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_handoff_por_erro.py tests/integration/test_cancelamento_do_worker.py -q`
Expected: PASS — o segundo arquivo entra para pegar regressão no caminho de cancelamento

- [ ] **Step 6: Suíte inteira e gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

- [ ] **Step 7: Commit**

```bash
git add src/mobia/workers/jobs/process_message.py tests/integration/test_handoff_por_erro.py
git commit -m "feat(TEC-174): a falha que esgota as tentativas encaminha, e avisa o lead"
```

---

## Cobertura do desenho

| Decisão | Task |
|---|---|
| D1 — enum com seis, fiação de três | 2 |
| D2 — identidade `(channel, conversation_key)` | 1 |
| D3 — `corretor_id` nulável sem FK | 1 |
| D4 — tabela mutável, com `atualizado_em` | 1 |
| D5 — `UNIQUE` parcial e `ON CONFLICT` | 1 e 3 |
| D6 — prioridade escala e nunca desce | 3 (só no SQL — ver o comentário em `vocabulario.py`) |
| D7 — etiqueta fixa | 2 e 3 |
| D8 — recebe sessão, não commita | 3 e 4 |
| D9 — irrecuperável é esgotar `attempts` | 6 |
| D10 — a escrita no erro não levanta | 6 |
| D11 — handoff primeiro, aviso depois | 6 |
| D12 — o SDR não silencia | 5 |

L1 (corretor alocado) e L2 (três gatilhos sem fiação) são lacunas declaradas: não têm task, por desenho.

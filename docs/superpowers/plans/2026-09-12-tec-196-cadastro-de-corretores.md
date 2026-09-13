# TEC-196 — Cadastro de corretores: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A imobiliária passa a ter corretores cadastrados — com contato, especialidade, região, jornada e capacidade —, e o handoff ganha enfim a chave estrangeira que aponta para eles.

**Architecture:** Uma tabela `corretores`, um módulo de domínio novo (`domain/corretores/`) com vocabulário puro e repositório, e um CRUD HTTP guardado pelo token de admin. A migration também acrescenta a FK de `handoffs.corretor_id`, que a emenda E-02 da RN-16.1 prometeu desde a TEC-174.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, FastAPI, Pydantic, pytest.

**Spec:** [`docs/superpowers/specs/2026-09-12-tec-196-cadastro-de-corretores-design.md`](../specs/2026-09-12-tec-196-cadastro-de-corretores-design.md)

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Convenção do repo, não checada por linter. Prosa em `docs/`: com acento.
- **Os três gates estáticos, no escopo exato do CI**, antes de qualquer commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m mypy`
  O formatador é gate separado do linter. **`alembic/` está no escopo do formatador** — a migration nova passa por ele.
- **`ruff`:** `select = ["E", "F", "I", "UP", "B"]`, `line-length = 100`. `fastapi.Depends` está em `extend-immutable-calls`.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4 s, sem Docker, sem `-n`).
- **Suíte inteira:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`. Uma vez; a segunda execução é diagnóstico, só quando a primeira falha.
- **`ConnectionResetError [WinError 64]`** é defeito conhecido desta máquina (~5% dos connects, em rajada), **não** é sinal sobre o código: espere e retente.
- **Mensagens de commit:** português sem acento no assunto, `tipo(TEC-196): o que passou a ser verdade`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **O contato fica EM CLARO** (nome, e-mail, telefone) — decisão D1, emenda E-01 ao modelo Corretor. **Não cifre.** O `UNIQUE(email)` depende disso.
- **Especialidades:** `COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `INVESTIMENTO_ALTO_TICKET`. As três primeiras são grafadas **idênticas** aos membros de `Intencao` (`domain/agente/schemas.py`), de propósito (D3).
- **Cada tabela nova em `TABELAS` (`tests/conftest.py`) entra no `TRUNCATE ... CASCADE` de todo teste que toca banco.** `corretores` precisa entrar, e **antes de `handoffs`** não importa — o `TRUNCATE` é um statement só, com `CASCADE`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/corretores/__init__.py` | **Criar.** Vazio, como os outros módulos de domínio. |
| `src/mobia/domain/corretores/vocabulario.py` | **Criar.** Puro, sem I/O: o enum `Especialidade` e os limites de jornada e capacidade. |
| `src/mobia/domain/corretores/models.py` | **Criar.** A tabela `corretores`. |
| `src/mobia/domain/corretores/repositorio.py` | **Criar.** Criar, listar, obter e atualizar. |
| `alembic/versions/0025_corretores.py` | **Criar.** A tabela e a FK de `handoffs.corretor_id`. |
| `src/mobia/api/routes/corretores.py` | **Criar.** O CRUD HTTP. |
| `src/mobia/app/main.py` | **Modificar.** Registrar o router no guard do token. |
| `tests/conftest.py` | **Modificar.** `corretores` entra em `TABELAS`. |

---

### Task 1: O vocabulário, puro e sem I/O

**Files:**
- Create: `src/mobia/domain/corretores/__init__.py` (vazio)
- Create: `src/mobia/domain/corretores/vocabulario.py`
- Test: `tests/unit/test_corretores_vocabulario.py`

**Interfaces:**
- Consumes: `Intencao` de `mobia.domain.agente.schemas` (só para o teste de alinhamento).
- Produces: `Especialidade` (StrEnum), `HORA_MINIMA`, `HORA_MAXIMA`, `CAPACIDADE_MINIMA`, `jornada_valida(inicio, fim) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_corretores_vocabulario.py
from mobia.domain.agente.schemas import Intencao
from mobia.domain.corretores.vocabulario import (
    CAPACIDADE_MINIMA,
    HORA_MAXIMA,
    HORA_MINIMA,
    Especialidade,
    jornada_valida,
)


def test_sao_as_quatro_especialidades_da_card() -> None:
    assert {e.value for e in Especialidade} == {
        "COMPRA",
        "ALUGUEL",
        "INVESTIMENTO",
        "INVESTIMENTO_ALTO_TICKET",
    }


def test_a_grafia_das_tres_compartilhadas_bate_com_intencao() -> None:
    """D3: e por igualdade de string que a TEC-166 vai mapear.

    Se alguem renomear um membro de qualquer um dos dois enums, este teste
    reprova -- que e exatamente o ponto. Sem ele, a divergencia so apareceria
    na alocacao, como lead que nao casa com corretor nenhum.
    """
    compartilhadas = {"COMPRA", "ALUGUEL", "INVESTIMENTO"}
    especialidades = {e.value for e in Especialidade}
    intencoes = {i.value for i in Intencao}

    assert compartilhadas <= especialidades
    assert compartilhadas <= intencoes


def test_alto_ticket_nao_e_intencao() -> None:
    """E segmentacao de ticket, nao intencao de conversa -- ver a D3."""
    assert "INVESTIMENTO_ALTO_TICKET" not in {i.value for i in Intencao}


def test_jornada_valida_exige_inicio_antes_do_fim() -> None:
    assert jornada_valida(9, 18) is True
    assert jornada_valida(18, 9) is False
    assert jornada_valida(9, 9) is False


def test_jornada_valida_recusa_hora_fora_do_relogio() -> None:
    assert jornada_valida(-1, 18) is False
    assert jornada_valida(9, 24) is False
    assert jornada_valida(HORA_MINIMA, HORA_MAXIMA) is True


def test_a_capacidade_minima_e_uma_visita() -> None:
    # Corretor com capacidade zero nao e corretor desativado -- para isso ha
    # `ativo`. Zero aqui seria uma linha que nunca recebe alocacao e que
    # ninguem consegue explicar depois.
    assert CAPACIDADE_MINIMA == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_corretores_vocabulario.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.corretores'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mobia/domain/corretores/vocabulario.py
"""Especialidade, jornada e capacidade do corretor.

TEC-196. Modulo sem I/O de proposito, no molde de `handoff/vocabulario.py` e
de `context/auditoria.py`: e o que deixa a regra ser testada em `tests/unit/`,
sem Postgres de pe.
"""

from enum import StrEnum

# A jornada e em horas inteiras, e nao em `jsonb` por dia da semana como o
# modelo da secao 5 do SRS pede -- ver a emenda E-02 daquele modelo e a D2 do
# desenho. E a forma que o repo ja usa: `followup_horario_inicio` e
# `followup_horario_fim` em `app/config.py` representam janela assim, e
# `outbound/horario.py` consome nesse formato.
HORA_MINIMA = 0
HORA_MAXIMA = 23

# Zero nao e "desativado" -- para isso existe a coluna `ativo`. Capacidade
# zero seria uma linha que nunca recebe alocacao e que ninguem consegue
# explicar seis meses depois.
CAPACIDADE_MINIMA = 1


class Especialidade(StrEnum):
    """As quatro especialidades da card.

    **As tres primeiras sao grafadas identicas aos membros de `Intencao`**
    (`domain/agente/schemas.py`), e isso e deliberado: e por igualdade de
    string que a TEC-166 vai mapear intencao do lead para especialidade do
    corretor, sem tabela de traducao. Tabela de traducao seria um segundo
    lugar para a mesma verdade divergir.

    **Nao reusa o enum `Intencao`** porque os conjuntos nao coincidem:
    `Intencao` tem VENDER_IMOVEL, SUPORTE_CONTRATO e INDEFINIDA, que nao sao
    especialidade de ninguem. E acrescentar INVESTIMENTO_ALTO_TICKET la
    mudaria o schema estrito da chamada ao modelo -- a docstring de `Intencao`
    avisa que acrescentar um membro muda o conjunto que o modelo pode
    devolver.
    """

    COMPRA = "COMPRA"
    ALUGUEL = "ALUGUEL"
    INVESTIMENTO = "INVESTIMENTO"
    # Segmentacao de ticket, nao intencao de conversa. Por isso nao tem
    # correspondente em `Intencao`.
    INVESTIMENTO_ALTO_TICKET = "INVESTIMENTO_ALTO_TICKET"


def jornada_valida(inicio: int, fim: int) -> bool:
    """A jornada cabe no relogio e comeca antes de terminar.

    Fim igual ao inicio e recusado junto com fim antes do inicio: uma janela
    de duracao zero nao e jornada, e aceita-la poria no banco um corretor a
    quem a TEC-170 nunca conseguiria propor horario nenhum.
    """
    return HORA_MINIMA <= inicio < fim <= HORA_MAXIMA
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_corretores_vocabulario.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Run the static gates**

Run os três comandos das Global Constraints. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/corretores/ tests/unit/test_corretores_vocabulario.py
git commit -m "feat(TEC-196): o vocabulario do corretor, com a grafia que a TEC-166 vai casar"
```

---

### Task 2: A tabela, a migration e a FK que a TEC-174 prometeu

**Files:**
- Create: `alembic/versions/0025_corretores.py`
- Create: `src/mobia/domain/corretores/models.py`
- Modify: `tests/conftest.py` (a tupla `TABELAS`)
- Test: `tests/integration/test_corretores_schema.py`

**Interfaces:**
- Consumes: `Especialidade`, `HORA_MINIMA`, `HORA_MAXIMA`, `CAPACIDADE_MINIMA` (Task 1).
- Produces: `Corretor` (modelo SQLAlchemy) com os campos listados abaixo.

**Precisa dos containers de pé.** Leia `alembic/versions/0024_resumo_do_handoff.py` e `0023_handoffs.py` antes de escrever: o formato do docstring — que explica o **porquê** de cada decisão de schema, não o quê — é o padrão a seguir.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_corretores_schema.py
"""O schema de `corretores` e a FK que a emenda E-02 da RN-16.1 prometeu."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff


def _corretor(**sobrescritas: object) -> Corretor:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "nome": "Paulo Ribeiro",
        "email": "paulo@imobiliaria.com.br",
        "telefone": "5511988887777",
        "creci": "SP-123456",
        "especialidades": ["COMPRA", "INVESTIMENTO"],
        "regioes_atuacao": ["zona sul"],
        "horario_inicio": 9,
        "horario_fim": 18,
        "capacidade_diaria": 4,
        "plantao": False,
        "ativo": True,
    }
    return Corretor(**(campos | sobrescritas))  # type: ignore[arg-type]


async def test_corretor_completo_grava(session: AsyncSession) -> None:
    session.add(_corretor())
    await session.commit()

    linha = (await session.execute(select(Corretor))).scalar_one()
    assert linha.especialidades == ["COMPRA", "INVESTIMENTO"]
    assert linha.horario_inicio == 9
    assert linha.ativo is True


async def test_email_e_unico(session: AsyncSession) -> None:
    """A unica defesa contra corretor duplicado -- ver a D1 do desenho.

    E a razao pela qual o contato NAO e cifrado: nonce aleatorio faz a busca
    por igualdade deixar de existir, e com ela este UNIQUE.
    """
    session.add(_corretor())
    await session.commit()

    session.add(_corretor(email="paulo@imobiliaria.com.br"))
    with pytest.raises(IntegrityError, match="uq_corretores_email"):
        await session.commit()


async def test_jornada_invertida_e_recusada_pelo_banco(session: AsyncSession) -> None:
    session.add(_corretor(horario_inicio=18, horario_fim=9))
    with pytest.raises(IntegrityError, match="ck_corretores_jornada"):
        await session.commit()


async def test_capacidade_zero_e_recusada_pelo_banco(session: AsyncSession) -> None:
    session.add(_corretor(capacidade_diaria=0))
    with pytest.raises(IntegrityError, match="ck_corretores_capacidade"):
        await session.commit()


async def test_especialidade_fora_do_vocabulario_e_recusada(session: AsyncSession) -> None:
    """O CHECK guarda o vocabulario no banco, como `ck_handoffs_status` faz."""
    session.add(_corretor(especialidades=["ASTROLOGIA"]))
    with pytest.raises(IntegrityError, match="ck_corretores_especialidades"):
        await session.commit()


async def test_corretor_sem_especialidade_e_recusado(session: AsyncSession) -> None:
    session.add(_corretor(especialidades=[]))
    with pytest.raises(IntegrityError, match="ck_corretores_especialidades"):
        await session.commit()


async def test_handoff_aponta_para_corretor_existente(session: AsyncSession) -> None:
    """A emenda E-03 da RN-16.1: a FK enfim existe."""
    corretor = _corretor()
    session.add(corretor)
    await session.commit()

    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            corretor_id=corretor.id,
            gatilhos_adicionais=[],
            criado_em=__import__("datetime").datetime.now(__import__("datetime").UTC),
            atualizado_em=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
    )
    await session.commit()

    gravado = (await session.execute(select(Handoff.corretor_id))).scalar_one()
    assert gravado == corretor.id


async def test_handoff_com_corretor_inexistente_e_recusado(session: AsyncSession) -> None:
    """Antes desta card isto passava, porque nao havia FK."""
    from datetime import UTC, datetime

    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            corretor_id=uuid.uuid4(),
            gatilhos_adicionais=[],
            criado_em=datetime.now(UTC),
            atualizado_em=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError, match="fk_handoffs_corretor"):
        await session.commit()


async def test_corretor_continua_opcional_no_handoff(session: AsyncSession) -> None:
    """A nulabilidade permanece: alocar e a TEC-166, nao esta card."""
    from datetime import UTC, datetime

    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            gatilhos_adicionais=[],
            criado_em=datetime.now(UTC),
            atualizado_em=datetime.now(UTC),
        )
    )
    await session.commit()

    assert (await session.execute(select(Handoff.corretor_id))).scalar_one() is None


async def test_a_tabela_entrou_no_truncate_dos_testes() -> None:
    """Sem isto, o corretor de um teste vira o duplicado do proximo."""
    from tests.conftest import TABELAS

    assert "corretores" in TABELAS
```

> Ajuste os `__import__` feios do primeiro teste de FK para um `from datetime import UTC, datetime` no topo do arquivo — estão ali só para o esboço caber numa leitura.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_corretores_schema.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.corretores.models'`

- [ ] **Step 3: Write the model**

```python
# src/mobia/domain/corretores/models.py
"""O corretor: a pessoa para quem o handoff aponta.

TEC-196, RF-19 e RN-19.2. Ver `alembic/versions/0025_corretores.py` para o
porque do contato em claro, do UNIQUE no e-mail e da FK que esta migration
enfim acrescenta a `handoffs`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Corretor(Base):
    __tablename__ = "corretores"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # **Em claro, e nao cifrado como a regra dos campos DP do SRS manda.** Ver
    # a emenda E-01 do modelo Corretor e a D1 do desenho. Em resumo: este repo
    # cifra CONTEUDO e nao IDENTIFICADOR -- o telefone do proprio lead esta em
    # claro em `messages.conversation_key` --, e cifrar aqui destruiria o
    # UNIQUE do e-mail logo abaixo, que e a unica defesa contra corretor
    # duplicado.
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), nullable=False)

    # Registro profissional. Sem leitor hoje, e de proposito: quem o preenche
    # e o administrador no cadastro, entao ele tem escritor desde o primeiro
    # POST -- nao e a coluna sem escritor que a D1 da TEC-174 recusou.
    creci: Mapped[str | None] = mapped_column(String(20), nullable=True)

    especialidades: Mapped[list[str]] = mapped_column(ARRAY(String(28)), nullable=False)

    # Dobradas na escrita com `dobrar()`, a mesma funcao que produz
    # `bairro_busca` no catalogo -- sem isso "Zona Sul" e "zona sul" viram
    # duas regioes e a alocacao da TEC-166 falha por acidente de digitacao.
    regioes_atuacao: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False)

    # Uma janela, e nao `jsonb` por dia da semana. Ver a emenda E-02 do modelo
    # Corretor: e a forma que `app/config.py` ja usa, e a que o criterio de
    # aceite exercita. Sabado meio periodo nao cabe, e isso esta declarado.
    horario_inicio: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    horario_fim: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    capacidade_diaria: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # O generalista que recebe o que nao tem match. **Pode haver mais de um**,
    # e escolher entre eles e a TEC-166 -- ver a D7. Um indice parcial
    # forcando um so inventaria regra que a card nao escreveu e quebraria
    # plantao por turno.
    plantao: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # Desativar e isto, e nao apagar a linha: a FK de `handoffs` a referencia,
    # e o historico tem de sobreviver (D6).
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("email", name="uq_corretores_email"),
        CheckConstraint(
            "horario_inicio >= 0 AND horario_fim <= 23 AND horario_inicio < horario_fim",
            name="ck_corretores_jornada",
        ),
        CheckConstraint("capacidade_diaria >= 1", name="ck_corretores_capacidade"),
        # Guarda o vocabulario no banco, como `ck_handoffs_status` faz para o
        # status. `<@` testa continencia de array em Postgres; a cardinalidade
        # recusa o corretor sem especialidade nenhuma, que nao seria alocavel.
        CheckConstraint(
            "cardinality(especialidades) > 0 AND especialidades <@ ARRAY["
            "'COMPRA','ALUGUEL','INVESTIMENTO','INVESTIMENTO_ALTO_TICKET']::varchar[]",
            name="ck_corretores_especialidades",
        ),
        CheckConstraint("cardinality(regioes_atuacao) > 0", name="ck_corretores_regioes"),
    )
```

- [ ] **Step 4: Write the migration**

```python
# alembic/versions/0025_corretores.py
"""o corretor, e a chave estrangeira que a TEC-174 prometeu por escrito

TEC-196, RF-19 e RN-19.2.

**O contato fica EM CLARO, contra a regra dos campos DP do SRS.** Ver a
emenda E-01 do modelo Corretor. Duas razoes: este repo cifra CONTEUDO e nao
IDENTIFICADOR -- `messages.conversation_key` guarda o telefone do proprio
titular em claro --, e cifrar destruiria o `uq_corretores_email`, porque o
nonce aleatorio do AES-GCM faz a busca por igualdade deixar de existir, por
desenho. Sem esse UNIQUE nao ha defesa contra corretor duplicado, e a
notificacao da RN-16.2 sairia dobrada.

**A jornada e uma janela de horas inteiras, e nao `jsonb` por dia.** Emenda
E-02 do mesmo modelo: e a forma que `app/config.py` ja usa para janela de
atendimento. Sabado meio periodo nao cabe, e isso esta declarado.

**A FK de `handoffs.corretor_id` entra aqui.** A emenda E-02 da RN-16.1
escreveu, na TEC-174, que "a TEC-196 acrescenta a restricao quando criar a
tabela". Esta e a card. `ON DELETE RESTRICT` (o default) porque corretor se
desativa por `ativo = false` e nunca se apaga: a cascata nao tem caso de uso,
e apagar por engano deve doer. A coluna continua NULAVEL, agora por outra
razao -- nao falta mais tabela alvo, falta quem aloque, e alocar e a TEC-166.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corretores",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("email", sa.String(160), nullable=False),
        sa.Column("telefone", sa.String(20), nullable=False),
        sa.Column("creci", sa.String(20), nullable=True),
        sa.Column("especialidades", sa.ARRAY(sa.String(28)), nullable=False),
        sa.Column("regioes_atuacao", sa.ARRAY(sa.String(120)), nullable=False),
        sa.Column("horario_inicio", sa.SmallInteger(), nullable=False),
        sa.Column("horario_fim", sa.SmallInteger(), nullable=False),
        sa.Column("capacidade_diaria", sa.SmallInteger(), nullable=False),
        sa.Column("plantao", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_corretores"),
        sa.UniqueConstraint("email", name="uq_corretores_email"),
        sa.CheckConstraint(
            "horario_inicio >= 0 AND horario_fim <= 23 AND horario_inicio < horario_fim",
            name="ck_corretores_jornada",
        ),
        sa.CheckConstraint("capacidade_diaria >= 1", name="ck_corretores_capacidade"),
        sa.CheckConstraint(
            "cardinality(especialidades) > 0 AND especialidades <@ ARRAY["
            "'COMPRA','ALUGUEL','INVESTIMENTO','INVESTIMENTO_ALTO_TICKET']::varchar[]",
            name="ck_corretores_especialidades",
        ),
        sa.CheckConstraint("cardinality(regioes_atuacao) > 0", name="ck_corretores_regioes"),
    )
    op.create_foreign_key(
        "fk_handoffs_corretor", "handoffs", "corretores", ["corretor_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_handoffs_corretor", "handoffs", type_="foreignkey")
    op.drop_table("corretores")
```

- [ ] **Step 5: Add the table to the test truncate list**

Em `tests/conftest.py`, acrescentar `"corretores"` à tupla `TABELAS`, com um comentário dizendo por que ela precisa entrar: o `UNIQUE(email)` faz o corretor de um teste colidir com o do próximo, exatamente como o comentário de `imoveis` já explica para o `UNIQUE(codigo)`.

- [ ] **Step 6: Run the migration and the tests**

Run:
```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_corretores_schema.py tests/integration/test_handoff_schema.py -v --tb=short
```
Expected: PASS. `test_handoff_schema.py` não pode quebrar com a FK nova.

- [ ] **Step 7: Run the static gates**

Run os três comandos. **Atenção:** `alembic/` está no escopo do `ruff format --check`.

- [ ] **Step 8: Commit**

```bash
git add src/mobia/domain/corretores/models.py alembic/versions/0025_corretores.py tests/conftest.py tests/integration/test_corretores_schema.py
git commit -m "feat(TEC-196): a tabela de corretores, e a FK que a TEC-174 prometeu por escrito"
```

---

### Task 3: O repositório

**Files:**
- Create: `src/mobia/domain/corretores/repositorio.py`
- Test: `tests/integration/test_corretores_repositorio.py`

**Interfaces:**
- Consumes: `Corretor` (Task 2), `Especialidade`/`jornada_valida` (Task 1), `dobrar` de `mobia.domain.texto`.
- Produces: `DadosDoCorretor` (dataclass congelado), `EmailJaCadastrado(Exception)`, `criar_corretor(session, dados) -> Corretor`, `listar_corretores(session, *, apenas_ativos: bool) -> list[Corretor]`, `obter_corretor(session, *, corretor_id) -> Corretor | None`, `atualizar_corretor(session, *, corretor_id, mudancas: dict) -> Corretor | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_corretores_repositorio.py
"""A escrita e a leitura do cadastro."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.repositorio import (
    DadosDoCorretor,
    EmailJaCadastrado,
    atualizar_corretor,
    criar_corretor,
    listar_corretores,
    obter_corretor,
)


def _dados(**sobrescritas: object) -> DadosDoCorretor:
    campos: dict[str, object] = {
        "nome": "Paulo Ribeiro",
        "email": "Paulo@Imobiliaria.com.BR",
        "telefone": "5511988887777",
        "creci": "SP-123456",
        "especialidades": ["COMPRA", "INVESTIMENTO"],
        "regioes_atuacao": ["Zona Sul", "Vila Mariana"],
        "horario_inicio": 9,
        "horario_fim": 18,
        "capacidade_diaria": 4,
        "plantao": False,
    }
    return DadosDoCorretor(**(campos | sobrescritas))  # type: ignore[arg-type]


async def test_criar_normaliza_email_e_regioes(session: AsyncSession) -> None:
    """D4: sem a dobra, "Zona Sul" e "zona sul" viram duas regioes.

    O e-mail cai para minuscula pelo mesmo motivo que o UNIQUE existe: dois
    cadastros do mesmo corretor com caixa diferente passariam pelo UNIQUE e
    a notificacao da TEC-177 sairia dobrada.
    """
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    assert corretor.email == "paulo@imobiliaria.com.br"
    assert corretor.regioes_atuacao == ["zona sul", "vila mariana"]


async def test_email_repetido_em_outra_caixa_e_recusado(session: AsyncSession) -> None:
    await criar_corretor(session, _dados())
    await session.commit()

    with pytest.raises(EmailJaCadastrado):
        await criar_corretor(session, _dados(email="PAULO@imobiliaria.com.br"))


async def test_listar_traz_ativos_e_inativos_por_padrao(session: AsyncSession) -> None:
    ativo = await criar_corretor(session, _dados())
    inativo = await criar_corretor(session, _dados(email="ana@imobiliaria.com.br"))
    await session.commit()
    await atualizar_corretor(session, corretor_id=inativo.id, mudancas={"ativo": False})
    await session.commit()

    todos = await listar_corretores(session, apenas_ativos=False)
    so_ativos = await listar_corretores(session, apenas_ativos=True)

    assert {c.id for c in todos} == {ativo.id, inativo.id}
    assert {c.id for c in so_ativos} == {ativo.id}


async def test_desativar_preserva_a_linha(session: AsyncSession) -> None:
    """Terceiro cenario do Gherkin: desativar nao apaga."""
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    await atualizar_corretor(session, corretor_id=corretor.id, mudancas={"ativo": False})
    await session.commit()

    de_volta = await obter_corretor(session, corretor_id=corretor.id)
    assert de_volta is not None
    assert de_volta.ativo is False
    assert de_volta.nome == "Paulo Ribeiro"


async def test_atualizar_dobra_as_regioes_novas(session: AsyncSession) -> None:
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    await atualizar_corretor(
        session, corretor_id=corretor.id, mudancas={"regioes_atuacao": ["Moema"]}
    )
    await session.commit()

    de_volta = await obter_corretor(session, corretor_id=corretor.id)
    assert de_volta is not None
    assert de_volta.regioes_atuacao == ["moema"]


async def test_atualizar_corretor_inexistente_devolve_none(session: AsyncSession) -> None:
    assert (
        await atualizar_corretor(session, corretor_id=uuid.uuid4(), mudancas={"ativo": False})
        is None
    )


async def test_obter_corretor_inexistente_devolve_none(session: AsyncSession) -> None:
    assert await obter_corretor(session, corretor_id=uuid.uuid4()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_corretores_repositorio.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/mobia/domain/corretores/repositorio.py
"""A escrita e a leitura do cadastro de corretores. TEC-196."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.texto import dobrar

UNIQUE_DO_EMAIL = "uq_corretores_email"


class EmailJaCadastrado(Exception):
    """Ja existe corretor com este e-mail.

    Excecao propria e nao IntegrityError cru porque a rota precisa distinguir
    este caso (409) de qualquer outra falha de integridade (500) -- tratar
    todo IntegrityError como duplicata esconderia um CHECK violado e mandaria
    quem investiga para o lado errado. E o mesmo argumento que
    `outbound/port.py` ja faz para a reserva de envio.
    """


@dataclass(frozen=True)
class DadosDoCorretor:
    """O que o administrador informa. Sem `id`, `ativo` nem carimbos."""

    nome: str
    email: str
    telefone: str
    creci: str | None
    especialidades: list[str]
    regioes_atuacao: list[str]
    horario_inicio: int
    horario_fim: int
    capacidade_diaria: int
    plantao: bool


def _email_canonico(email: str) -> str:
    """Minuscula, para o UNIQUE valer o que promete.

    Sem isto, "Paulo@x.com" e "paulo@x.com" sao duas linhas para o UNIQUE e um
    corretor so para a realidade -- e a notificacao da TEC-177 sairia dobrada.
    """
    return email.strip().casefold()


def _regioes_dobradas(regioes: list[str]) -> list[str]:
    """A mesma dobra que produz `bairro_busca` no catalogo. Ver a D4."""
    return [dobrar(regiao) for regiao in regioes]


async def criar_corretor(session: AsyncSession, dados: DadosDoCorretor) -> Corretor:
    """Cria o corretor. **Nao commita** -- o commit e de quem chama.

    Mesma disciplina de `registrar_handoff` e de `gravar_resumo`, e pela mesma
    razao: quem chama e que sabe o que mais precisa entrar na transacao.
    """
    agora = datetime.now(UTC)
    corretor = Corretor(
        id=uuid.uuid4(),
        nome=dados.nome.strip(),
        email=_email_canonico(dados.email),
        telefone=dados.telefone.strip(),
        creci=dados.creci,
        especialidades=list(dados.especialidades),
        regioes_atuacao=_regioes_dobradas(dados.regioes_atuacao),
        horario_inicio=dados.horario_inicio,
        horario_fim=dados.horario_fim,
        capacidade_diaria=dados.capacidade_diaria,
        plantao=dados.plantao,
        ativo=True,
        criado_em=agora,
        atualizado_em=agora,
    )
    session.add(corretor)
    try:
        await session.flush()
    except IntegrityError as erro:
        if UNIQUE_DO_EMAIL in str(erro.orig):
            raise EmailJaCadastrado(dados.email) from erro
        raise
    return corretor


async def obter_corretor(
    session: AsyncSession, *, corretor_id: uuid.UUID
) -> Corretor | None:
    return (
        await session.execute(select(Corretor).where(Corretor.id == corretor_id))
    ).scalar_one_or_none()


async def listar_corretores(
    session: AsyncSession, *, apenas_ativos: bool
) -> list[Corretor]:
    consulta = select(Corretor).order_by(Corretor.nome)
    if apenas_ativos:
        consulta = consulta.where(Corretor.ativo.is_(True))
    return list((await session.execute(consulta)).scalars().all())


async def atualizar_corretor(
    session: AsyncSession, *, corretor_id: uuid.UUID, mudancas: dict[str, Any]
) -> Corretor | None:
    """Aplica as mudancas informadas. `None` quando o corretor nao existe.

    **Desativar e uma mudanca como outra qualquer** (`{"ativo": False}`), e
    nao uma operacao propria: apagar a linha quebraria a FK que a 0025 criou,
    e a RESTRICT recusaria -- um DELETE existiria so para devolver erro (D6).
    """
    corretor = await obter_corretor(session, corretor_id=corretor_id)
    if corretor is None:
        return None

    for campo, valor in mudancas.items():
        if campo == "email":
            valor = _email_canonico(str(valor))
        elif campo == "regioes_atuacao":
            valor = _regioes_dobradas(list(valor))
        setattr(corretor, campo, valor)

    corretor.atualizado_em = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as erro:
        if UNIQUE_DO_EMAIL in str(erro.orig):
            raise EmailJaCadastrado(str(mudancas.get("email"))) from erro
        raise
    return corretor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_corretores_repositorio.py -v --tb=short`
Expected: PASS (7 testes)

- [ ] **Step 5: Run the static gates**

Run os três comandos. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/corretores/repositorio.py tests/integration/test_corretores_repositorio.py
git commit -m "feat(TEC-196): o cadastro normaliza e-mail e regiao antes de gravar"
```

---

### Task 4: O CRUD HTTP

**Files:**
- Create: `src/mobia/api/routes/corretores.py`
- Modify: `src/mobia/app/main.py`
- Test: `tests/integration/test_rota_de_corretores.py`

**Interfaces:**
- Consumes: tudo das Tasks 1–3; `exigir_admin` de `mobia.api.deps`.
- Produces: `POST /api/v1/corretores`, `GET /api/v1/corretores`, `GET /api/v1/corretores/{id}`, `PATCH /api/v1/corretores/{id}`.

**O molde da fixture de cliente HTTP é `app_com_token` em `tests/integration/test_busca_endpoint.py:22`.** O ponto crítico: **o router só é registrado quando `catalogo_admin_token` é verdadeiro, então o token tem de estar no ambiente ANTES do `create_app()`** — `monkeypatch.setenv` e `get_settings.cache_clear()` antes de criar o app, e outro `cache_clear()` no teardown.

O molde dos modelos de requisição é `FiltrosDaBusca` em `src/mobia/api/routes/imoveis.py:160`: `BaseModel` com `alias` camelCase e `populate_by_name`, porque o corpo HTTP fala camelCase e o Python deste repo fala snake_case.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_rota_de_corretores.py
"""O CRUD de corretores, guardado pelo token de admin."""

import uuid

TOKEN = "token-de-teste-de-corretores"

CORPO = {
    "nome": "Paulo Ribeiro",
    "email": "paulo@imobiliaria.com.br",
    "telefone": "5511988887777",
    "creci": "SP-123456",
    "especialidades": ["COMPRA", "INVESTIMENTO"],
    "regioesAtuacao": ["Zona Sul"],
    "horarioInicio": 9,
    "horarioFim": 18,
    "capacidadeDiaria": 4,
    "plantao": False,
}


async def test_sem_token_e_403(app_com_token) -> None:
    resposta = await app_com_token.post("/api/v1/corretores", json=CORPO)
    assert resposta.status_code == 403


async def test_cadastrar_devolve_201_com_o_id(app_com_token) -> None:
    """Primeiro cenario do Gherkin."""
    resposta = await app_com_token.post(
        "/api/v1/corretores", json=CORPO, headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert uuid.UUID(corpo["id"])
    assert corpo["especialidades"] == ["COMPRA", "INVESTIMENTO"]
    # D4: a regiao e gravada dobrada.
    assert corpo["regioesAtuacao"] == ["zona sul"]
    assert corpo["ativo"] is True


async def test_email_duplicado_e_409(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)

    resposta = await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)

    assert resposta.status_code == 409


async def test_especialidade_invalida_e_422(app_com_token) -> None:
    """O vocabulario e recusado na borda, antes de chegar ao CHECK do banco."""
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"especialidades": ["ASTROLOGIA"]},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_jornada_invertida_e_422(app_com_token) -> None:
    resposta = await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"horarioInicio": 18, "horarioFim": 9},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 422


async def test_listar_filtra_por_ativo(app_com_token) -> None:
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (
        await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)
    ).json()
    await app_com_token.post(
        "/api/v1/corretores",
        json=CORPO | {"email": "ana@imobiliaria.com.br"},
        headers=cabecalho,
    )
    await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"ativo": False}, headers=cabecalho
    )

    todos = (await app_com_token.get("/api/v1/corretores", headers=cabecalho)).json()
    ativos = (
        await app_com_token.get("/api/v1/corretores?ativos=true", headers=cabecalho)
    ).json()

    assert len(todos) == 2
    assert len(ativos) == 1


async def test_desativar_preserva_o_corretor(app_com_token) -> None:
    """Terceiro cenario do Gherkin: desativar nao apaga."""
    cabecalho = {"X-Admin-Token": TOKEN}
    criado = (
        await app_com_token.post("/api/v1/corretores", json=CORPO, headers=cabecalho)
    ).json()

    await app_com_token.patch(
        f"/api/v1/corretores/{criado['id']}", json={"ativo": False}, headers=cabecalho
    )

    lido = await app_com_token.get(f"/api/v1/corretores/{criado['id']}", headers=cabecalho)
    assert lido.status_code == 200
    assert lido.json()["ativo"] is False
    assert lido.json()["nome"] == "Paulo Ribeiro"


async def test_corretor_inexistente_e_404(app_com_token) -> None:
    resposta = await app_com_token.get(
        f"/api/v1/corretores/{uuid.uuid4()}", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404


async def test_nao_existe_rota_de_delete(app_com_token) -> None:
    """D6: apagar quebraria a FK, e a RESTRICT recusaria de qualquer jeito."""
    criado = (
        await app_com_token.post(
            "/api/v1/corretores", json=CORPO, headers={"X-Admin-Token": TOKEN}
        )
    ).json()

    resposta = await app_com_token.delete(
        f"/api/v1/corretores/{criado['id']}", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 405
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_corretores.py -v --tb=short`
Expected: FAIL — `fixture 'app_com_token' not found`, e depois `404` nas rotas.

- [ ] **Step 3: Write the route**

```python
# src/mobia/api/routes/corretores.py
"""O CRUD de corretores. TEC-196, RF-19 e RN-19.2.

**Guardado pelo `exigir_admin`, o mesmo token do catalogo -- e isso estende a
um DADO PESSOAL uma guarda que foi aceita por nao haver dado pessoal.** A
emenda E-01 da TEC-156 escreveu, sobre o catalogo: "aceito porque o objeto e
o catalogo de imoveis e nao dado pessoal, ao contrario da reativacao de
opt-out da TEC-182, que por isso ficou sem rota HTTP". Aqui o objeto E dado
pessoal: nome, e-mail e telefone de pessoas reais. Decisao consciente de
12/09/2026, declarada na emenda E-01 da RN-19.5 e no comentario da card.
**Consequencia: quem tem o token le o contato de todos os corretores.** Ver a
D8 do desenho.

Nao ha rota DELETE de proposito: desativar e `ativo = false` (D6).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mobia.api.deps import exigir_admin
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.repositorio import (
    DadosDoCorretor,
    EmailJaCadastrado,
    atualizar_corretor,
    criar_corretor,
    listar_corretores,
    obter_corretor,
)
from mobia.domain.corretores.vocabulario import (
    CAPACIDADE_MINIMA,
    HORA_MAXIMA,
    HORA_MINIMA,
    Especialidade,
    jornada_valida,
)
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/corretores", tags=["corretores"])


class CorretorNovo(BaseModel):
    """O corpo do cadastro, no camelCase da secao 6 do SRS.

    `alias` e nao atributos em camelCase: o corpo HTTP fala camelCase e o
    Python deste repo fala snake_case -- mesmo molde de `FiltrosDaBusca` em
    `imoveis.py`.
    """

    model_config = ConfigDict(populate_by_name=True)

    nome: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    telefone: str = Field(min_length=8, max_length=20)
    creci: str | None = Field(default=None, max_length=20)
    especialidades: list[Especialidade] = Field(min_length=1)
    regioes_atuacao: list[str] = Field(alias="regioesAtuacao", min_length=1)
    horario_inicio: int = Field(alias="horarioInicio", ge=HORA_MINIMA, le=HORA_MAXIMA)
    horario_fim: int = Field(alias="horarioFim", ge=HORA_MINIMA, le=HORA_MAXIMA)
    capacidade_diaria: int = Field(alias="capacidadeDiaria", ge=CAPACIDADE_MINIMA)
    plantao: bool = False

    @field_validator("horario_fim")
    @classmethod
    def _jornada_coerente(cls, fim: int, info: Any) -> int:
        # A jornada e recusada na borda, com 422, em vez de deixar o CHECK do
        # banco devolver 500. O CHECK continua existindo: e ele que protege a
        # tabela de quem escrever por fora desta rota.
        inicio = info.data.get("horario_inicio")
        if inicio is not None and not jornada_valida(inicio, fim):
            raise ValueError("jornada invalida: o inicio tem de vir antes do fim")
        return fim


class CorretorEditado(BaseModel):
    """As mudancas. Tudo opcional -- o que nao vier nao muda."""

    model_config = ConfigDict(populate_by_name=True)

    nome: str | None = Field(default=None, min_length=1, max_length=120)
    telefone: str | None = Field(default=None, min_length=8, max_length=20)
    creci: str | None = Field(default=None, max_length=20)
    especialidades: list[Especialidade] | None = Field(default=None, min_length=1)
    regioes_atuacao: list[str] | None = Field(default=None, alias="regioesAtuacao", min_length=1)
    capacidade_diaria: int | None = Field(
        default=None, alias="capacidadeDiaria", ge=CAPACIDADE_MINIMA
    )
    plantao: bool | None = None
    ativo: bool | None = None


def _resposta(corretor: Corretor) -> dict[str, object]:
    return {
        "id": str(corretor.id),
        "nome": corretor.nome,
        "email": corretor.email,
        "telefone": corretor.telefone,
        "creci": corretor.creci,
        "especialidades": corretor.especialidades,
        "regioesAtuacao": corretor.regioes_atuacao,
        "horarioInicio": corretor.horario_inicio,
        "horarioFim": corretor.horario_fim,
        "capacidadeDiaria": corretor.capacidade_diaria,
        "plantao": corretor.plantao,
        "ativo": corretor.ativo,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def cadastrar(
    pedido: CorretorNovo, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        try:
            corretor = await criar_corretor(
                session,
                DadosDoCorretor(
                    nome=pedido.nome,
                    email=pedido.email,
                    telefone=pedido.telefone,
                    creci=pedido.creci,
                    especialidades=[e.value for e in pedido.especialidades],
                    regioes_atuacao=pedido.regioes_atuacao,
                    horario_inicio=pedido.horario_inicio,
                    horario_fim=pedido.horario_fim,
                    capacidade_diaria=pedido.capacidade_diaria,
                    plantao=pedido.plantao,
                ),
            )
        except EmailJaCadastrado as erro:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="e-mail ja cadastrado"
            ) from erro
        await session.commit()
        return _resposta(corretor)


@router.get("")
async def listar(
    ativos: Annotated[bool, Query()] = False, _: None = Depends(exigir_admin)
) -> list[dict[str, object]]:
    async with get_sessionmaker()() as session:
        return [_resposta(c) for c in await listar_corretores(session, apenas_ativos=ativos)]


@router.get("/{corretor_id}")
async def obter(
    corretor_id: uuid.UUID, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        corretor = await obter_corretor(session, corretor_id=corretor_id)
    if corretor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="corretor nao existe")
    return _resposta(corretor)


@router.patch("/{corretor_id}")
async def editar(
    corretor_id: uuid.UUID, pedido: CorretorEditado, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    mudancas = pedido.model_dump(exclude_none=True)
    if "especialidades" in mudancas:
        mudancas["especialidades"] = [str(e) for e in mudancas["especialidades"]]

    async with get_sessionmaker()() as session:
        corretor = await atualizar_corretor(
            session, corretor_id=corretor_id, mudancas=mudancas
        )
        if corretor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="corretor nao existe"
            )
        await session.commit()
        return _resposta(corretor)
```

> **O `exclude_none=True` do PATCH tem uma consequência que você deve conferir e declarar:** ele torna impossível limpar o `creci` de volta para `null` pela rota. Se achar que isso importa, troque por `model_dump(exclude_unset=True)` — que distingue "não informado" de "informado como nulo" — e registre a escolha no relatório.

Em `src/mobia/app/main.py`, registrar o router dentro do mesmo `if settings.catalogo_admin_token:` que já guarda o de imóveis.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_corretores.py -v --tb=short`
Expected: PASS (9 testes)

- [ ] **Step 5: Run the static gates**

Run os três comandos. Expected: limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/api/routes/corretores.py src/mobia/app/main.py tests/integration/test_rota_de_corretores.py
git commit -m "feat(TEC-196): o cadastro ganha CRUD, e o token do catalogo passa a cobrir dado pessoal"
```

---

### Task 5: Fechamento

**Files:** nenhum novo; correções onde a verificação apontar.

- [ ] **Step 1: Run the whole suite, once**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
Expected: verde.

**Atenção especial nesta card:** a FK nova em `handoffs.corretor_id` pode quebrar testes existentes que gravem handoff com `corretor_id` arbitrário. Se isso acontecer, **é regressão de verdade e não flake** — conserte o teste para usar um corretor real ou `None`.

Se falhar com `ConnectionResetError [WinError 64]`, é ruído desta máquina (~5% dos connects). `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados. **Se a primeira execução falhar, repita sobre a mesma árvore antes de culpar a mudança.**

- [ ] **Step 2: Check the touched comments**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

Reconfira cada `ALTERADO` e cada `VIZINHO`. O candidato previsível desta branch: **o comentário de `Handoff.corretor_id` em `src/mobia/domain/handoff/models.py`**, que hoje diz *"Nulavel e sem FK ate a TEC-196 criar `corretores`. Nada escreve aqui hoje."* — as duas afirmações mudaram de estado. Corrija-o.

- [ ] **Step 3: Verify the prompt budget was not touched**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Expected: PASS inalterado. Esta card não toca `SISTEMA_DO_AGENTE`.

- [ ] **Step 4: Commit any fixes and push**

```bash
git push -u origin feat/tec-196-cadastro-de-corretores
```

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 2 (contato em claro, `UNIQUE(email)`) e Task 3 (canonicalização). D2 → Tasks 1 e 2 (janela única). D3 → Task 1 (grafia alinhada a `Intencao`). D4 → Task 3 (`dobrar()`). D5 → Task 2 (FK). D6 → Tasks 3 e 4 (sem DELETE). D7 → Task 2 (sem índice parcial de plantão). D8 → Task 4 (`exigir_admin` e a exposição declarada). D9 → Task 2 (`creci`). L1 → Task 4 (o teste é token/não-token). L2, L3, L4 → declaradas; sem task, por construção.

**Consistência de tipos:** `DadosDoCorretor` é produzido na Task 3 e consumido na Task 4; `Especialidade` na Task 1 e usado nas Tasks 2 e 4; `Corretor` na Task 2 e usado nas 3 e 4.

**Dois pontos que o executor resolve contra o repo,** marcados em citação no corpo: os `__import__` do esboço de teste da Task 2, que devem virar import no topo; e o `exclude_none` versus `exclude_unset` do PATCH na Task 4.

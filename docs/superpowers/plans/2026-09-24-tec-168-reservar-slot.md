# TEC-168 — Reservar o slot — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tabela `agendamentos` com constraint de exclusão por intervalo (a garantia do RT-07 no banco), reserva de 5 minutos com expiração preguiçosa, `reservar`/`confirmar`, a agenda real (`AgendaPostgres`) e a disputa que devolve alternativas ao perdedor.

**Architecture:** Migration 0044 cria a extensão `btree_gist`, a tabela e a `EXCLUDE USING gist (corretor_id WITH =, tstzrange(inicio, fim, '[)') WITH &&) WHERE status IN ('RESERVADO','CONFIRMADO')`. O repositório recebe a sessão e não commita; a expiração é feita na leitura (filtro) e na escrita (UPDATE antes do INSERT), sem job.

**Tech Stack:** SQLAlchemy 2 async + asyncpg, Alembic, Postgres 16 (`pgvector/pgvector:pg16`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-168-reservar-slot-design.md`

## Global Constraints

- Comentários e docstrings em `src/`, `tests/` e `alembic/`: português **sem** acento; comentário diz o porquê.
- Status e tipo como `String` + `CHECK`, nunca enum nativo (regra desde a migration 0016).
- UUID gerado em Python (`uuid.uuid4()`); `DateTime(timezone=True)` sempre.
- Repositório recebe `AsyncSession` e **não commita** (disciplina de `registrar_handoff`/`criar_corretor`).
- Violação de constraint é reconhecida pelo **nome** (padrão de `_e_email_duplicado` em `domain/corretores/repositorio.py`).
- `agora` sempre como parâmetro, com fuso; nunca `now()` do banco nas regras.
- Nomes: constraint `ex_agendamentos_sem_sobreposicao`, tabela `agendamentos`, revisão `"0044"` com `down_revision = "0043"`.
- Os testes de integração exigem `docker compose` de pé. Rode os arquivos novos sozinhos (sem `-n`). Se aparecer `[WinError 64]` ou `CannotConnectNowError`, é o ambiente (ver `CLAUDE.md`, "O banco demora mais que o healthcheck diz") — espere e rode de novo antes de concluir qualquer coisa.
- Gates: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Commit: `tipo(TEC-168): o que passou a ser verdade`, sem acento no assunto, trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Sessão depois do `Conflito`** — quem chama continua usando a mesma sessão; ela precisa estar utilizável (o `reservar` faz `rollback`) (teste na Task 2).
2. **Reserva vencida de OUTRO corretor no mesmo horário** — não pode ser expirada por um `reservar` alheio (teste na Task 2).
3. **`confirmar` duas vezes** — a segunda não pode rebaixar nem duplicar; devolve `Expirado` (a linha já não é `RESERVADO`) (teste na Task 2).
4. **Corrida real** — duas sessões, commit das duas, uma linha só (teste na Task 3).
5. **A 0044 desce e sobe** — downgrade limpo sem remover `btree_gist` (teste na Task 1).

---

### Task 1: O modelo, a migration e a garantia do banco

**Files:**
- Create: `src/mobia/domain/agendamento/models.py`
- Create: `alembic/versions/0044_agendamentos.py`
- Modify: `tests/conftest.py` (`TABELAS`: acrescentar `"agendamentos"` com comentário do porquê, no estilo das entradas vizinhas)
- Create: `tests/integration/test_agendamento_schema.py`
- Modify: `tests/integration/test_migrations.py` (um teste "a 0044 desce e sobe de novo", no molde de `test_a_0037_desce_e_sobe_de_novo`)

**Interfaces:**
- Produces: `StatusDoAgendamento` (`RESERVADO`, `CONFIRMADO`, `EXPIRADO`), `EXCLUSAO_DE_SOBREPOSICAO = "ex_agendamentos_sem_sobreposicao"`, modelo `Agendamento` com as colunas da D1.

- [ ] **Step 1: Testes que falham** — `tests/integration/test_agendamento_schema.py`:

```python
"""A garantia de nao sobreposicao, testada no banco. TEC-168, RT-07.

Os inserts aqui sao SQL cru de proposito: o cenario da card diz que a
segunda gravacao e recusada pela constraint, e so um insert que nao passa
pelo repositorio prova que a garantia e do banco e nao do codigo.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mobia.domain.agendamento.models import EXCLUSAO_DE_SOBREPOSICAO

SP = ZoneInfo("America/Sao_Paulo")


def _qui(hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 8, 27, hora, minuto, tzinfo=SP)


async def _inserir(session, *, corretor_id, inicio, fim, status="CONFIRMADO") -> None:
    await session.execute(
        text(
            "INSERT INTO agendamentos (id, corretor_id, channel, conversation_key, imovel_id,"
            " tipo, inicio, fim, status, reservado_ate, criado_em, confirmado_em)"
            " VALUES (:id, :corretor_id, 'whatsapp', :chave, NULL, 'VISITA_PRESENCIAL',"
            " :inicio, :fim, :status, :inicio, :inicio, NULL)"
        ),
        {
            "id": uuid.uuid4(),
            "corretor_id": corretor_id,
            "chave": str(uuid.uuid4())[:20],
            "inicio": inicio,
            "fim": fim,
            "status": status,
        },
    )
    await session.commit()


async def test_sobreposicao_e_barrada_pelo_banco(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))
    with pytest.raises(IntegrityError) as erro:
        await _inserir(session, corretor_id=corretor.id, inicio=_qui(10, 30), fim=_qui(11, 30))
    assert EXCLUSAO_DE_SOBREPOSICAO in str(erro.value)


async def test_horarios_que_encostam_convivem(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(11), fim=_qui(12))


async def test_corretores_diferentes_no_mesmo_horario_convivem(session, semear_corretor) -> None:
    paulo = await semear_corretor(email="paulo@teste.com")
    ana = await semear_corretor(email="ana@teste.com")
    await _inserir(session, corretor_id=paulo.id, inicio=_qui(10), fim=_qui(11))
    await _inserir(session, corretor_id=ana.id, inicio=_qui(10), fim=_qui(11))


async def test_expirado_nao_entra_na_exclusao(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(
        session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status="EXPIRADO"
    )
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))


async def test_reservado_entra_na_exclusao(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(
        session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status="RESERVADO"
    )
    with pytest.raises(IntegrityError):
        await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))


async def test_status_fora_do_vocabulario_e_recusado(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    with pytest.raises(IntegrityError):
        await _inserir(
            session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status="PENDENTE"
        )


async def test_intervalo_invertido_e_recusado(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    with pytest.raises(IntegrityError):
        await _inserir(session, corretor_id=corretor.id, inicio=_qui(11), fim=_qui(10))
```

Se o `semear_corretor` já commitou e o acesso a `corretor.id` depois do commit reclamar (atributo expirado / `MissingGreenlet`), guarde o `id` logo após semear ou siga o que os testes de `test_handoff_repositorio.py` fazem com o corretor; relate o que fez.

- [ ] **Step 2: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/integration/test_agendamento_schema.py --tb=short -q` → `ModuleNotFoundError: mobia.domain.agendamento.models`.

- [ ] **Step 3: O modelo** — `src/mobia/domain/agendamento/models.py`:

```python
"""Os agendamentos, e a garantia de que dois nao se sobrepoem. TEC-168, RT-07.

**A garantia nao mora aqui.** A constraint de exclusao por intervalo
(`EXCLUSAO_DE_SOBREPOSICAO`) e criada em SQL pela migration 0044 e nao e
declarada no modelo: o `ExcludeConstraint` do SQLAlchemy nao expressa bem o
`tstzrange(inicio, fim, '[)')`, e o que importa para o RT-07 e o banco
recusar -- ver `tests/integration/test_agendamento_schema.py`, que prova com
insert cru, sem passar por este modelo.

O lead e o par `(channel, conversation_key)`, como em `handoffs` e
`optout_events`: nao existe tabela de lead.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

# Importados para registrar as tabelas-alvo das FKs no mesmo metadata: sem
# eles o flush nao sabe ordenar `agendamentos` depois de `corretores` e
# `imoveis`.
from mobia.domain.catalogo.models import Imovel  # noqa: F401
from mobia.domain.corretores.models import Corretor  # noqa: F401
from mobia.domain.messages.models import Base


class StatusDoAgendamento(StrEnum):
    RESERVADO = "RESERVADO"
    CONFIRMADO = "CONFIRMADO"
    # A reserva que venceu e foi atropelada por outra (D3 do desenho). Uma
    # vencida que ninguem disputou continua RESERVADO: quem le filtra por
    # `reservado_ate`, e nao por este status.
    EXPIRADO = "EXPIRADO"


EXCLUSAO_DE_SOBREPOSICAO = "ex_agendamentos_sem_sobreposicao"


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    corretor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("corretores.id", name="fk_agendamentos_corretor"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nulo: reuniao remota pode nao ter imovel. O contrato do SRS (6.4) tem
    # `imovelId`, e a FK impede apontar para imovel que nao existe.
    imovel_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("imoveis.id", name="fk_agendamentos_imovel"),
        nullable=True,
    )
    tipo: Mapped[str] = mapped_column(String(24), nullable=False)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reservado_ate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "tipo IN ('VISITA_PRESENCIAL','REUNIAO_REMOTA')", name="ck_agendamentos_tipo"
        ),
        CheckConstraint(
            "status IN ('RESERVADO','CONFIRMADO','EXPIRADO')", name="ck_agendamentos_status"
        ),
        CheckConstraint("inicio < fim", name="ck_agendamentos_intervalo"),
    )
```

(Se o import de `Imovel` ou `Corretor` criar ciclo de import, relate; o `noqa: F401` é porque só o efeito de registro importa.)

- [ ] **Step 4: A migration** — `alembic/versions/0044_agendamentos.py`:

```python
"""os agendamentos, e a exclusao por intervalo que impede dois no mesmo horario

TEC-168, RN-11.4, RT-07.

**A garantia do RT-07 e esta constraint, e nao o codigo.** `EXCLUDE USING
gist` recusa, na mesma transacao que tenta gravar, qualquer par de linhas do
mesmo corretor cujos intervalos se sobreponham -- inclusive duas transacoes
concorrentes: a segunda espera a primeira e reprova se ela commitar.

**`'[)'`: encostar nao conflita.** 10h-11h convive com 11h-12h, a mesma regra
do motor de janelas da TEC-165.

**O WHERE tira EXPIRADO, e nao olha o relogio.** Predicado de constraint tem
de ser imutavel e `now()` nao e; a reserva vencida sai da exclusao quando o
repositorio a marca EXPIRADO, antes de gravar por cima (D3 do desenho).

**`btree_gist` e o que deixa `corretor_id WITH =` entrar num indice gist.**
Como o `vector` da 0017, o downgrade nao a remove: outra coisa pode ter
passado a depender dela.

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "agendamentos",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("corretor_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("imovel_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("tipo", sa.String(24), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reservado_ate", sa.DateTime(timezone=True), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmado_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_agendamentos"),
        sa.ForeignKeyConstraint(
            ["corretor_id"], ["corretores.id"], name="fk_agendamentos_corretor"
        ),
        sa.ForeignKeyConstraint(["imovel_id"], ["imoveis.id"], name="fk_agendamentos_imovel"),
        sa.CheckConstraint(
            "tipo IN ('VISITA_PRESENCIAL','REUNIAO_REMOTA')", name="ck_agendamentos_tipo"
        ),
        sa.CheckConstraint(
            "status IN ('RESERVADO','CONFIRMADO','EXPIRADO')", name="ck_agendamentos_status"
        ),
        sa.CheckConstraint("inicio < fim", name="ck_agendamentos_intervalo"),
    )
    op.execute(
        "ALTER TABLE agendamentos ADD CONSTRAINT ex_agendamentos_sem_sobreposicao"
        " EXCLUDE USING gist (corretor_id WITH =, tstzrange(inicio, fim, '[)') WITH &&)"
        " WHERE (status IN ('RESERVADO', 'CONFIRMADO'))"
    )
    op.create_index("ix_agendamentos_conversa", "agendamentos", ["channel", "conversation_key"])


def downgrade() -> None:
    op.drop_table("agendamentos")
```

- [ ] **Step 5: `TABELAS` e o teste de migration** — em `tests/conftest.py`, acrescente `"agendamentos"` ao fim de `TABELAS`, com um comentário no estilo dos vizinhos (mutável, e com a constraint de exclusão: sem o truncate, o agendamento de um teste barra o horário do próximo). Em `tests/integration/test_migrations.py`, acrescente `test_a_0044_desce_e_sobe_de_novo` copiando a forma de `test_a_0037_desce_e_sobe_de_novo`: desce para `0043`, confere que `agendamentos` não existe e que a extensão `btree_gist` continua (`SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'`), sobe para `head` e confere que a tabela voltou.

- [ ] **Step 6: Rodar e ver passar** — `./.venv/Scripts/python.exe -m pytest tests/integration/test_agendamento_schema.py tests/integration/test_migrations.py --tb=short -q`.

**Atenção aos bancos dos workers:** se depois você rodar com `-n`, os bancos `mobia_gw*` precisam receber a 0044; o `migrar_banco` cuida disso quando o carimbo está atrás. Se aparecer `relation "agendamentos" does not exist` em dezenas de testes, é o caso descrito no `CLAUDE.md` ("carimbo adiantado"), não defeito seu.

- [ ] **Step 7: Gates e commit**

```bash
git add src/mobia/domain/agendamento/models.py alembic/versions/0044_agendamentos.py tests/conftest.py tests/integration/test_agendamento_schema.py tests/integration/test_migrations.py
git commit -m "feat(TEC-168): agendamentos com exclusao por intervalo, e o banco recusa dois no mesmo horario

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `reservar`, `confirmar` e a agenda real

**Files:**
- Create: `src/mobia/domain/agendamento/repositorio.py`
- Create: `tests/integration/test_agendamento_repositorio.py`

**Interfaces:**
- Consumes: `Agendamento`, `StatusDoAgendamento`, `EXCLUSAO_DE_SOBREPOSICAO` (Task 1); `Intervalo`, `TipoDeCompromisso`, `AgendaDoCorretor` (`domain/agendamento/janelas.py`).
- Produces: `DURACAO_DA_RESERVA`, `Reserva(id, janela, reservado_ate)`, `Conflito()`, `Confirmado(id, janela)`, `Expirado()`, `reservar(...)`, `confirmar(...)`, `AgendaPostgres(session_factory)`. Task 3 usa `reservar`, `Reserva`, `Conflito`, `AgendaPostgres`.

- [ ] **Step 1: Testes que falham** — `tests/integration/test_agendamento_repositorio.py`:

```python
"""Reservar, confirmar e ler a agenda do corretor. TEC-168, RN-11.4.

`agora` e literal: os cenarios "reservado ha 5 minutos" e "ha 2 minutos"
sao aritmetica sobre ele, sem dormir.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from mobia.domain.agendamento.janelas import (
    Intervalo,
    TipoDeCompromisso,
    propor_janelas_do_corretor,
)
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.repositorio import (
    DURACAO_DA_RESERVA,
    AgendaPostgres,
    Confirmado,
    Conflito,
    Expirado,
    Reserva,
    confirmar,
    reservar,
)

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 8, 25, 14, 0, tzinfo=SP)
VISITA = TipoDeCompromisso.VISITA_PRESENCIAL


def _qui(hora: int, minuto: int = 0) -> Intervalo:
    inicio = datetime(2026, 8, 27, hora, minuto, tzinfo=SP)
    return Intervalo(inicio, inicio + timedelta(hours=1))


async def _reservar(session, corretor_id, janela, *, agora=AGORA, chave="5511911111111"):
    return await reservar(
        session,
        corretor_id=corretor_id,
        channel="whatsapp",
        conversation_key=chave,
        janela=janela,
        tipo=VISITA,
        imovel_id=None,
        agora=agora,
    )


async def _status(session, reserva_id) -> str:
    session.expire_all()
    return await session.scalar(select(Agendamento.status).where(Agendamento.id == reserva_id))


async def test_reservar_grava_reservado_por_5_minutos(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    resultado = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(resultado, Reserva)
    assert resultado.janela == _qui(10)
    assert resultado.reservado_ate == AGORA + DURACAO_DA_RESERVA
    assert await _status(session, resultado.id) == StatusDoAgendamento.RESERVADO


async def test_confirmacao_dentro_do_prazo_mantem_a_reserva(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    resultado = await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=2))
    await session.commit()
    assert resultado == Confirmado(reserva.id, _qui(10))
    session.expire_all()
    linha = await session.get(Agendamento, reserva.id)
    assert linha is not None
    assert linha.status == StatusDoAgendamento.CONFIRMADO
    assert linha.confirmado_em == AGORA + timedelta(minutes=2)


async def test_confirmar_depois_do_prazo_e_expirado_e_nao_grava(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    resultado = await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=5))
    await session.commit()
    assert resultado == Expirado()
    assert await _status(session, reserva.id) == StatusDoAgendamento.RESERVADO


async def test_confirmar_duas_vezes_nao_regrava(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=1))
    await session.commit()
    segunda = await confirmar(session, reserva_id=reserva.id, agora=AGORA + timedelta(minutes=2))
    assert segunda == Expirado()


async def test_confirmar_id_inexistente_e_expirado(session) -> None:
    assert await confirmar(session, reserva_id=uuid.uuid4(), agora=AGORA) == Expirado()


async def test_reserva_valida_do_mesmo_slot_e_conflito(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    resultado = await _reservar(
        session, corretor.id, _qui(10), agora=AGORA + timedelta(minutes=1), chave="5511922222222"
    )
    assert resultado == Conflito()


async def test_sessao_continua_utilizavel_depois_do_conflito(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    await _reservar(session, corretor.id, _qui(10), chave="5511922222222")
    outra = await _reservar(session, corretor.id, _qui(15), chave="5511922222222")
    await session.commit()
    assert isinstance(outra, Reserva)


async def test_reservar_sobre_reserva_vencida_sucede_e_expira_a_antiga(
    session, semear_corretor
) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    antiga = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(antiga, Reserva)
    nova = await _reservar(
        session, corretor.id, _qui(10), agora=AGORA + timedelta(minutes=5), chave="5511922222222"
    )
    await session.commit()
    assert isinstance(nova, Reserva)
    assert await _status(session, antiga.id) == StatusDoAgendamento.EXPIRADO


async def test_reservar_nao_expira_reserva_vencida_de_outro_corretor(
    session, semear_corretor
) -> None:
    paulo = await semear_corretor(email="paulo@teste.com")
    ana = await semear_corretor(email="ana@teste.com")
    dela = await _reservar(session, ana.id, _qui(10))
    await session.commit()
    assert isinstance(dela, Reserva)
    await _reservar(session, paulo.id, _qui(10), agora=AGORA + timedelta(minutes=10))
    await session.commit()
    assert await _status(session, dela.id) == StatusDoAgendamento.RESERVADO


async def test_ocupados_conta_confirmado_e_reserva_valida(
    session, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    confirmada = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(confirmada, Reserva)
    await confirmar(session, reserva_id=confirmada.id, agora=AGORA)
    await _reservar(session, corretor.id, _qui(15), chave="5511922222222")
    await session.commit()
    agenda = AgendaPostgres(session_factory)
    ocupados = await agenda.ocupados(
        corretor.id, AGORA + timedelta(minutes=1), AGORA + timedelta(days=7)
    )
    assert ocupados == [_qui(10), _qui(15)]


async def test_reserva_vencida_some_da_agenda_e_volta_as_propostas(
    session, session_factory, semear_corretor
) -> None:
    """O cenario "reserva expira sem confirmacao" da card.

    Jornada de uma hora (10h-11h): cada dia tem uma janela so, e a de quinta
    so pode aparecer nas propostas se a reserva dela tiver vencido. Com a
    jornada inteira, o motor espalharia por dia e ofereceria quinta 9h -- e o
    teste passaria sem provar nada.
    """
    corretor = await semear_corretor(email="paulo@teste.com", horario_inicio=10, horario_fim=11)
    await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    agenda = AgendaPostgres(session_factory)
    ate = datetime(2026, 8, 27, 12, 0, tzinfo=SP)

    antes = await propor_janelas_do_corretor(
        corretor=corretor, agenda=agenda, agora=AGORA + timedelta(minutes=1), ate=ate, tipo=VISITA
    )
    depois = await propor_janelas_do_corretor(
        corretor=corretor, agenda=agenda, agora=AGORA + timedelta(minutes=5), ate=ate, tipo=VISITA
    )
    assert _qui(10) not in antes
    assert _qui(10) in depois


async def test_ocupados_devolve_o_que_sobrepoe_e_nao_so_o_contido(
    session, session_factory, semear_corretor
) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    reserva = await _reservar(session, corretor.id, _qui(10))
    await session.commit()
    assert isinstance(reserva, Reserva)
    await confirmar(session, reserva_id=reserva.id, agora=AGORA)
    await session.commit()
    agenda = AgendaPostgres(session_factory)
    meio = datetime(2026, 8, 27, 10, 30, tzinfo=SP)
    assert await agenda.ocupados(corretor.id, meio, meio + timedelta(hours=2)) == [_qui(10)]
```

O `semear_corretor` cria o corretor com jornada 9h–18h; os horários acima cabem nela. Se algum teste esperar valor que não bate por causa da jornada ou da antecedência, confira contra a D3/D4 e relate antes de mexer.

- [ ] **Step 2: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/integration/test_agendamento_repositorio.py --tb=short -q` → `ModuleNotFoundError: mobia.domain.agendamento.repositorio`.

- [ ] **Step 3: Implementar** — `src/mobia/domain/agendamento/repositorio.py`:

```python
"""Reservar, confirmar e ler a agenda do corretor. TEC-168, RN-11.4, RT-07.

Recebe a sessao e **nao commita** -- o commit e de quem chama, como em
`registrar_handoff` e `criar_corretor`. A exclusao por intervalo e do banco
(migration 0044); este modulo so traduz a recusa dele em `Conflito` e faz a
expiracao preguicosa que o banco nao consegue fazer sozinho (D3 do desenho).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.models import (
    EXCLUSAO_DE_SOBREPOSICAO,
    Agendamento,
    StatusDoAgendamento,
)

# RN-11.4. Regra do SRS, nao configuracao -- o argumento da D4 da TEC-285.
DURACAO_DA_RESERVA = timedelta(minutes=5)


@dataclass(frozen=True)
class Reserva:
    id: uuid.UUID
    janela: Intervalo
    reservado_ate: datetime


@dataclass(frozen=True)
class Conflito:
    pass


@dataclass(frozen=True)
class Confirmado:
    id: uuid.UUID
    janela: Intervalo


@dataclass(frozen=True)
class Expirado:
    pass


def _e_sobreposicao(exc: IntegrityError) -> bool:
    """Distingue a recusa da exclusao de qualquer outra falha de integridade.

    Mesma forma de `_e_email_duplicado` (`corretores/repositorio.py`): pelo
    NOME da constraint, com o texto como fallback para driver que nao expoe
    `constraint_name`. Tratar todo IntegrityError como conflito esconderia
    um CHECK violado atras de "horario ocupado".
    """
    original = exc.orig
    nome = getattr(original, "constraint_name", None)
    if nome is not None:
        return bool(nome == EXCLUSAO_DE_SOBREPOSICAO)
    return EXCLUSAO_DE_SOBREPOSICAO in str(original)


async def reservar(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    channel: str,
    conversation_key: str,
    janela: Intervalo,
    tipo: TipoDeCompromisso,
    imovel_id: uuid.UUID | None,
    agora: datetime,
) -> Reserva | Conflito:
    """Reserva `janela` por `DURACAO_DA_RESERVA`, ou devolve `Conflito`.

    Antes de inserir, marca EXPIRADO as reservas vencidas **deste corretor**
    que sobrepoem a janela: a constraint nao olha o relogio, e sem isso uma
    reserva morta barraria o lugar para sempre.

    **Em `Conflito`, a sessao ja voltou (`rollback`).** Um flush recusado deixa
    a sessao inutilizavel; devolve-la assim transferiria o problema a quem
    chama. O custo e declarado: o rollback desfaz tambem qualquer escrita
    pendente que quem chama tivesse feito nesta sessao antes de chamar aqui.
    """
    await session.execute(
        update(Agendamento)
        .where(
            Agendamento.corretor_id == corretor_id,
            Agendamento.status == StatusDoAgendamento.RESERVADO,
            Agendamento.reservado_ate <= agora,
            Agendamento.inicio < janela.fim,
            Agendamento.fim > janela.inicio,
        )
        .values(status=StatusDoAgendamento.EXPIRADO)
    )
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id,
        channel=channel,
        conversation_key=conversation_key,
        imovel_id=imovel_id,
        tipo=str(tipo),
        inicio=janela.inicio,
        fim=janela.fim,
        status=StatusDoAgendamento.RESERVADO,
        reservado_ate=agora + DURACAO_DA_RESERVA,
        criado_em=agora,
        confirmado_em=None,
    )
    session.add(agendamento)
    try:
        await session.flush()
    except IntegrityError as erro:
        await session.rollback()
        if _e_sobreposicao(erro):
            return Conflito()
        raise
    return Reserva(agendamento.id, janela, agendamento.reservado_ate)


async def confirmar(session: AsyncSession, *, reserva_id: uuid.UUID, agora: datetime) -> Confirmado | Expirado:
    """Confirma a reserva se ela ainda vale; senao `Expirado`, sem gravar nada.

    Um UPDATE so, com a condicao inteira no WHERE: nao ha janela entre ler
    "ainda vale" e gravar "confirmado" em que a reserva possa vencer ou ser
    atropelada. Vencida, ja confirmada, ja expirada ou inexistente -- as quatro
    viram `Expirado`, e quem chama oferece de novo.
    """
    resultado = await session.execute(
        update(Agendamento)
        .where(
            Agendamento.id == reserva_id,
            Agendamento.status == StatusDoAgendamento.RESERVADO,
            Agendamento.reservado_ate > agora,
        )
        .values(status=StatusDoAgendamento.CONFIRMADO, confirmado_em=agora)
        .returning(Agendamento.inicio, Agendamento.fim)
    )
    linha = resultado.first()
    if linha is None:
        return Expirado()
    return Confirmado(reserva_id, Intervalo(linha.inicio, linha.fim))


class AgendaPostgres:
    """A implementacao real de `AgendaDoCorretor` (TEC-165).

    Abre a propria sessao: e porta de leitura, chamada pelo motor de janelas,
    e le so o que ja foi commitado -- que e o que importa para propor horario.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ocupados(self, corretor_id: uuid.UUID, de: datetime, ate: datetime) -> list[Intervalo]:
        # Sobrepoe `[de, ate]`, e nao "contido nele": um compromisso que comecou
        # antes de `de` ainda ocupa. E as reservas contam so se ainda valem em
        # `de` -- a leitura e a outra metade da expiracao preguicosa.
        async with self._session_factory() as session:
            linhas = await session.execute(
                select(Agendamento.inicio, Agendamento.fim)
                .where(
                    Agendamento.corretor_id == corretor_id,
                    Agendamento.inicio < ate,
                    Agendamento.fim > de,
                    or_(
                        Agendamento.status == StatusDoAgendamento.CONFIRMADO,
                        and_(
                            Agendamento.status == StatusDoAgendamento.RESERVADO,
                            Agendamento.reservado_ate > de,
                        ),
                    ),
                )
                .order_by(Agendamento.inicio)
            )
            return [Intervalo(inicio, fim) for inicio, fim in linhas.all()]
```

Notas: os `datetime` que voltam do banco vêm em UTC; `Intervalo` compara instantes, então `_qui(10) == Intervalo(utc...)` é verdadeiro. Se o `ruff format` quebrar as assinaturas longas, aceite. Se `mypy` reclamar de `linha.inicio` no `Row`, use índices ou `resultado.one_or_none()` tipado e relate.

- [ ] **Step 4: Rodar e ver passar** — o arquivo novo e o da Task 1.

- [ ] **Step 5: Gates, `tests/unit` e commit**

```bash
git add src/mobia/domain/agendamento/repositorio.py tests/integration/test_agendamento_repositorio.py
git commit -m "feat(TEC-168): reservar e confirmar com expiracao preguicosa, e a agenda real do corretor

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Quem perde a disputa recebe alternativas

**Files:**
- Modify: `src/mobia/domain/agendamento/repositorio.py` (acrescentar `reservar_ou_alternativas`)
- Test: `tests/integration/test_agendamento_repositorio.py`
- Modify: `src/mobia/domain/agendamento/janelas.py` — só as docstrings que ficaram falsas: `AgendaDoCorretor` diz que "a implementacao real nasce com a TEC-168; ate la o unico implementador e o fake dos testes" (agora existe `AgendaPostgres`), e `propor_janelas_do_corretor` diz que é a costura "no lugar em que a TEC-168 a usara" (agora usa). Reescreva só o necessário para ficarem verdadeiras.

**Interfaces:**
- Consumes: `reservar`, `Reserva`, `Conflito` (Task 2); `propor_janelas_do_corretor`, `AgendaDoCorretor` (TEC-165).
- Produces: `reservar_ou_alternativas(session, *, corretor, agenda, channel, conversation_key, janela, tipo, imovel_id, agora, ate) -> Reserva | list[Intervalo]`.

- [ ] **Step 1: Teste que falha** — acrescente ao fim de `tests/integration/test_agendamento_repositorio.py` (imports: `asyncio`, `from sqlalchemy import text`, e `reservar_ou_alternativas`):

```python
async def test_dois_leads_disputam_o_mesmo_horario(
    session, session_factory, semear_corretor
) -> None:
    """O primeiro cenario da card: um reserva, o outro recebe alternativas.

    Duas sessoes reais, cada uma commitando a sua -- a segunda gravacao espera
    a primeira na exclusao do banco e e recusada quando ela commita. Nenhuma
    das duas ve erro tecnico.
    """
    corretor = await semear_corretor(email="paulo@teste.com")
    agenda = AgendaPostgres(session_factory)
    ate = datetime(2026, 8, 29, 19, 0, tzinfo=SP)

    async def disputar(chave: str) -> Reserva | list[Intervalo]:
        async with session_factory() as propria:
            resultado = await reservar_ou_alternativas(
                propria,
                corretor=corretor,
                agenda=agenda,
                channel="whatsapp",
                conversation_key=chave,
                janela=_qui(10),
                tipo=VISITA,
                imovel_id=None,
                agora=AGORA,
                ate=ate,
            )
            await propria.commit()
            return resultado

    resultados = await asyncio.gather(disputar("5511911111111"), disputar("5511922222222"))

    reservas = [r for r in resultados if isinstance(r, Reserva)]
    alternativas = [r for r in resultados if isinstance(r, list)]
    assert len(reservas) == 1
    assert len(alternativas) == 1
    assert alternativas[0]
    assert not any(janela.sobrepoe(_qui(10)) for janela in alternativas[0])
    total = await session.scalar(text("SELECT count(*) FROM agendamentos"))
    assert total == 1


async def test_sem_disputa_devolve_a_reserva(session, session_factory, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    resultado = await reservar_ou_alternativas(
        session,
        corretor=corretor,
        agenda=AgendaPostgres(session_factory),
        channel="whatsapp",
        conversation_key="5511911111111",
        janela=_qui(10),
        tipo=VISITA,
        imovel_id=None,
        agora=AGORA,
        ate=datetime(2026, 8, 29, 19, 0, tzinfo=SP),
    )
    assert isinstance(resultado, Reserva)
```

- [ ] **Step 2: Rodar e ver falhar** — `ImportError: cannot import name 'reservar_ou_alternativas'`.

- [ ] **Step 3: Implementar** — em `repositorio.py` (imports: `from mobia.domain.agendamento.janelas import AgendaDoCorretor, propor_janelas_do_corretor` e `from mobia.domain.corretores.models import Corretor`):

```python
async def reservar_ou_alternativas(
    session: AsyncSession,
    *,
    corretor: Corretor,
    agenda: AgendaDoCorretor,
    channel: str,
    conversation_key: str,
    janela: Intervalo,
    tipo: TipoDeCompromisso,
    imovel_id: uuid.UUID | None,
    agora: datetime,
    ate: datetime,
) -> Reserva | list[Intervalo]:
    """A reserva, ou as janelas que sobraram -- nunca um erro tecnico.

    Em `Conflito`, quem venceu ja commitou (foi o commit dele que fez esta
    gravacao ser recusada), entao a agenda que o motor le ja o enxerga e as
    alternativas nao incluem o horario perdido. `ate` e o horizonte das
    alternativas e vem de quem chama, como no motor.
    """
    resultado = await reservar(
        session,
        corretor_id=corretor.id,
        channel=channel,
        conversation_key=conversation_key,
        janela=janela,
        tipo=tipo,
        imovel_id=imovel_id,
        agora=agora,
    )
    if isinstance(resultado, Reserva):
        return resultado
    return await propor_janelas_do_corretor(
        corretor=corretor, agenda=agenda, agora=agora, ate=ate, tipo=tipo
    )
```

E as duas docstrings de `janelas.py` listadas em **Files**.

- [ ] **Step 4: Rodar e ver passar** — `./.venv/Scripts/python.exe -m pytest tests/integration/test_agendamento_repositorio.py tests/integration/test_agendamento_schema.py tests/unit/test_janelas_de_agendamento.py --tb=short -q`. Rode o teste da disputa **10 vezes** (`--count` não existe aqui; use um laço de shell) e relate as 10 saídas: corrida que passa uma vez não prova nada. Se alguma falhar com `[WinError 64]`, é o ambiente — ver Global Constraints.

- [ ] **Step 5: Gates, `tests/unit` e commit**

```bash
git add src/mobia/domain/agendamento/repositorio.py src/mobia/domain/agendamento/janelas.py tests/integration/test_agendamento_repositorio.py
git commit -m "feat(TEC-168): quem perde a disputa pelo horario recebe as janelas que sobraram

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

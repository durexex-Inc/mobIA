# TEC-152 — Auditoria de recálculo de score: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o lead score rodar em produção a cada turno e gravar uma trilha imutável de cada vez que ele muda, com os cinco fatores e as causas.

**Architecture:** Uma função pura deriva as causas comparando dois `Score`; uma tabela append-only com trigger de imutabilidade guarda os registros; um orquestrador no repositório trava a linha de qualificação, relê o estado, calcula, compara com o último registro e grava se houve movimento; o turno o chama dentro da transação que já grava o estado.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic, Postgres (`ARRAY`, `CHECK`, trigger plpgsql), pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-09-02-tec-152-auditoria-de-recalculo-de-score-design.md`](../specs/2026-09-02-tec-152-auditoria-de-recalculo-de-score-design.md) — leia antes da Task 1. O plano argumenta a partir dela.

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter nenhum. Prosa em `docs/` leva acento normalmente.
- **Os três gates estáticos, nesta ordem, antes de cada commit.** O formatador é um gate separado do linter:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
- **O escopo é `src tests alembic evals`, não `src tests`.**
- **TDD, e cada teste verificado por mutação.** Depois de ficar verde, quebre de propósito a linha que o teste cobre e confirme que ele fica vermelho — e vermelho *naquele* teste. Nas cards anteriores, toda rodada de revisão perdida foi teste que passava com o código certo ou errado.
- **Comentário explica o porquê, não o quê, e comentário desatualizado é defeito.** Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **A suíte é lenta e lentidão aqui parece travamento.** `tests/unit` sozinho leva ~7 min; a suíte inteira ~7,5 min. Rode o arquivo ou o teste específico durante o ciclo, e a suíte inteira só no fim.
- **Testes de integração flakeiam sob carga, não isolados.** Antes de atribuir uma falha a uma mudança sua, rode o arquivo sozinho.
- **Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` mesmo com o container `healthy`.** Espere e retente antes de diagnosticar.
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-152): o que passou a ser verdade`.
- **Nada de FK** de `lead_score_audit` para `messages` ou `lead_qualification` — ver D1 da spec.

## File Structure

| arquivo | responsabilidade |
|---|---|
| `src/mobia/domain/context/auditoria.py` | **Criar.** Puro: o vocabulário de causas e `causas_do_recalculo`. Sem I/O, no molde de `score.py` e `qualificacao.py`. |
| `src/mobia/domain/context/models.py` | **Modificar.** Acrescenta `LeadScoreAudit` ao lado de `LeadQualification`. |
| `alembic/versions/0012_auditoria_de_score.py` | **Criar.** Tabela, `CHECK`, índice e a trigger de imutabilidade. |
| `src/mobia/domain/context/repositorio.py` | **Modificar.** Acrescenta `contar_mensagens_do_lead` e `registrar_recalculo`. É o único lugar com SQL desta card. |
| `src/mobia/domain/agente/turno.py` | **Modificar.** Três linhas: a chamada dentro da transação que já existe. |
| `tests/conftest.py` | **Modificar.** `lead_score_audit` entra em `TABELAS`, senão a trilha vaza entre testes. |
| `tests/unit/test_auditoria_score.py` | **Criar.** A função pura, sem banco. |
| `tests/integration/test_auditoria_score.py` | **Criar.** Tabela, trigger, `CHECK`, contagem, orquestrador e o gancho no turno. |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | **Modificar.** A emenda E-01 sob a RN-06.4. |

**Por que `auditoria.py` é separado de `repositorio.py`:** o repo separa regra pura de I/O em toda parte (`score.py`, `qualificacao.py`, `janela.py` são puros; `repositorio.py` tem o SQL). `repositorio.py` já tem 21,6K — misturar a regra nova ali a esconderia e tiraria o teste dela do `tests/unit`.

---

### Task 1: A função pura que deriva as causas

**Files:**
- Create: `src/mobia/domain/context/auditoria.py`
- Test: `tests/unit/test_auditoria_score.py`

**Interfaces:**
- Consumes: `Score` de `mobia.domain.context.score` — dataclass frozen com os campos `completude`, `urgencia`, `catalogo`, `engajamento`, `capacidade` (todos `int`) e a property `total`.
- Produces: `causas_do_recalculo(anterior: Score | None, novo: Score) -> tuple[str, ...]` e as constantes `CAUSA_PRIMEIRO_CALCULO`, `CAUSA_CAMPOS_OBRIGATORIOS`, `CAUSA_URGENCIA`, `CAUSA_CATALOGO`, `CAUSA_ENGAJAMENTO`, `CAUSA_FORMA_DE_PAGAMENTO`, `CAUSA_EDICAO_MANUAL`, `CAUSA_NAO_COMPARECIMENTO`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/unit/test_auditoria_score.py`:

```python
"""As causas de um recalculo, derivadas do diff entre dois Score.

TEC-152. Sem banco: a funcao e pura.
"""

from dataclasses import fields

import pytest

from mobia.domain.context.auditoria import (
    CAUSA_CAMPOS_OBRIGATORIOS,
    CAUSA_CATALOGO,
    CAUSA_ENGAJAMENTO,
    CAUSA_FORMA_DE_PAGAMENTO,
    CAUSA_PRIMEIRO_CALCULO,
    CAUSA_URGENCIA,
    _CAUSA_POR_FATOR,
    causas_do_recalculo,
)
from mobia.domain.context.score import Score


def score(**ajustes: int) -> Score:
    """Um Score com os cinco fatores zerados, menos os que o teste ajusta."""
    base = {
        "completude": 0,
        "urgencia": 0,
        "catalogo": 0,
        "engajamento": 0,
        "capacidade": 0,
    }
    return Score(**{**base, **ajustes})


@pytest.mark.parametrize(
    ("fator", "causa"),
    [
        ("completude", CAUSA_CAMPOS_OBRIGATORIOS),
        ("urgencia", CAUSA_URGENCIA),
        ("catalogo", CAUSA_CATALOGO),
        ("engajamento", CAUSA_ENGAJAMENTO),
        ("capacidade", CAUSA_FORMA_DE_PAGAMENTO),
    ],
)
def test_cada_fator_movendo_sozinho_produz_a_sua_causa_e_so_ela(fator: str, causa: str) -> None:
    assert causas_do_recalculo(score(), score(**{fator: 5})) == (causa,)


def test_o_fator_caindo_produz_a_mesma_causa_que_subindo() -> None:
    """O vocabulario e do dominio, nao da direcao: subiu ou caiu se le nos numeros."""
    assert causas_do_recalculo(score(urgencia=25), score(urgencia=8)) == (CAUSA_URGENCIA,)


def test_duas_causas_no_mesmo_passo() -> None:
    """A mensagem que informa a forma de pagamento tambem move o engajamento."""
    anterior = score(capacidade=6, engajamento=10)
    novo = score(capacidade=15, engajamento=15)
    assert causas_do_recalculo(anterior, novo) == (
        CAUSA_ENGAJAMENTO,
        CAUSA_FORMA_DE_PAGAMENTO,
    )


def test_total_identico_com_composicao_diferente_produz_causas() -> None:
    """O caso da D3, e o unico em que comparar totais devolveria "nada aconteceu".

    O lead so tinha informado urgencia (completude 5, urgencia 15) e diz "quero
    comprar apto ate 500 mil na Vila Mariana, mas sem pressa": intencao, faixa
    de preco e regiao entram de uma vez (+15) e a urgencia cai para SEM_PRESSA
    (-15). O total nao se move e o lead passou de quase anonimo a quase
    completo.
    """
    anterior = score(completude=5, urgencia=15)
    novo = score(completude=20, urgencia=0)

    assert anterior.total == novo.total
    assert causas_do_recalculo(anterior, novo) == (
        CAUSA_CAMPOS_OBRIGATORIOS,
        CAUSA_URGENCIA,
    )


def test_nada_se_movendo_devolve_vazio() -> None:
    """Tupla vazia e o sinal de "nao grave" -- a regra da D3 mora aqui, e nao
    num `if` do chamador."""
    igual = score(completude=20, urgencia=15, engajamento=10, capacidade=6)
    assert causas_do_recalculo(igual, igual) == ()


def test_sem_anterior_e_primeiro_calculo_e_so_ele() -> None:
    """Nao a lista dos fatores diferentes de zero: nao houve movimento a explicar."""
    novo = score(completude=20, urgencia=15, engajamento=10, capacidade=6)
    assert causas_do_recalculo(None, novo) == (CAUSA_PRIMEIRO_CALCULO,)


def test_o_mapa_cobre_exatamente_os_cinco_fatores_do_Score() -> None:
    """Um sexto fator no Score sem causa correspondente tem de deixar isto
    vermelho, e nao passar em silencio -- e a mesma defesa que a TEC-150 deu aos
    dois mapas de pontos, amarrando-os aos seus enums.
    """
    assert {fator for fator, _ in _CAUSA_POR_FATOR} == {campo.name for campo in fields(Score)}
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_score.py -v
```

Esperado: erro de coleta, `ModuleNotFoundError: No module named 'mobia.domain.context.auditoria'`.

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/context/auditoria.py`:

```python
"""As causas de um recalculo de score, derivadas do que se moveu.

TEC-152. Pura de proposito: sem I/O, sem banco, sem chamada ao modelo --
mesma forma de `score.py` e `qualificacao.py`. Quem grava e o repositorio;
aqui so se decide o que mudou.

**Tupla vazia e o sinal de "nao grave".** A regra da RN-06.4 emendada -- so
grava quando o resultado muda -- nao e um `if` no chamador: e a ausencia de
causa. Assim a regra de QUANDO gravar mora no mesmo lugar que a de O QUE
gravar, e as duas nao tem como divergir.
"""

from mobia.domain.context.score import Score

CAUSA_PRIMEIRO_CALCULO = "PRIMEIRO_CALCULO"
CAUSA_CAMPOS_OBRIGATORIOS = "CAMPOS_OBRIGATORIOS"
CAUSA_URGENCIA = "URGENCIA"
CAUSA_CATALOGO = "CATALOGO"
CAUSA_ENGAJAMENTO = "ENGAJAMENTO"
CAUSA_FORMA_DE_PAGAMENTO = "FORMA_DE_PAGAMENTO"

# Sem produtor hoje, e de proposito. Nao sao derivaveis de diff nenhum: sao
# fatos sobre a ORIGEM do gatilho, e nao sobre o que se moveu. O chamador
# futuro os informa -- o dashboard da TEC-192 para a edicao manual, a TEC-172
# para o nao comparecimento. Entram agora porque acrescenta-los depois nao
# custaria migration (a coluna e um ARRAY de texto), mas custaria uma segunda
# lista de vocabulario em outro arquivo.
CAUSA_EDICAO_MANUAL = "EDICAO_MANUAL"
CAUSA_NAO_COMPARECIMENTO = "NAO_COMPARECIMENTO"

# Os nomes sao do dominio e nao da direcao: um vocabulario com _SUBIU/_CAIU
# dobraria de tamanho para dizer o que as colunas de fator ja dizem.
#
# `capacidade` vira FORMA_DE_PAGAMENTO porque e o que o leitor da trilha
# reconhece -- "capacidade" e nome interno do fator, e o campo que se moveu
# tem nome proprio no produto.
#
# A ordem e a de `Score`, e a tupla de saida a respeita: duas execucoes com o
# mesmo diff devolvem a mesma tupla, e o teste pode comparar por igualdade em
# vez de por conjunto.
_CAUSA_POR_FATOR: tuple[tuple[str, str], ...] = (
    ("completude", CAUSA_CAMPOS_OBRIGATORIOS),
    ("urgencia", CAUSA_URGENCIA),
    ("catalogo", CAUSA_CATALOGO),
    ("engajamento", CAUSA_ENGAJAMENTO),
    ("capacidade", CAUSA_FORMA_DE_PAGAMENTO),
)


def causas_do_recalculo(anterior: Score | None, novo: Score) -> tuple[str, ...]:
    """O que mudou entre dois calculos. Vazio quando nada mudou.

    Compara os cinco fatores, e **nao** o total. O total pode ficar identico
    com a composicao mudando -- completude +15 e urgencia -15 no mesmo turno --
    e e justamente o caso em que a trilha explica algo que ninguem deduz do
    estado atual.

    `anterior is None` e o primeiro registro do lead, e devolve so
    `PRIMEIRO_CALCULO`: nao houve movimento a explicar, e listar os fatores
    diferentes de zero fingiria que houve.
    """
    if anterior is None:
        return (CAUSA_PRIMEIRO_CALCULO,)

    return tuple(
        causa
        for fator, causa in _CAUSA_POR_FATOR
        if getattr(anterior, fator) != getattr(novo, fator)
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/unit/test_auditoria_score.py -v
```

Esperado: 11 passed (7 funções, uma delas parametrizada em 5).

- [ ] **Step 5: Verificar por mutação**

Troque `!=` por `==` em `causas_do_recalculo`. Esperado: `test_nada_se_movendo_devolve_vazio` fica vermelho e os de fator também. Desfaça. Depois remova a linha `("catalogo", CAUSA_CATALOGO),` do mapa: esperado, `test_o_mapa_cobre_exatamente_os_cinco_fatores_do_Score` fica vermelho. Desfaça.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/auditoria.py tests/unit/test_auditoria_score.py
git commit -m "feat(TEC-152): a causa de um recalculo sai do diff dos cinco fatores"
```

---

### Task 2: A tabela, o `CHECK`, o índice e a trigger de imutabilidade

**Files:**
- Create: `alembic/versions/0012_auditoria_de_score.py`
- Modify: `src/mobia/domain/context/models.py`
- Modify: `tests/conftest.py` (a tupla `TABELAS`, linhas 32-40)
- Test: `tests/integration/test_auditoria_score.py`

**Interfaces:**
- Consumes: `Base` de `mobia.domain.messages.models` (já importado em `context/models.py`).
- Produces: `LeadScoreAudit`, com os atributos `id`, `channel`, `conversation_key`, `total_anterior`, `total_novo`, `completude`, `urgencia`, `catalogo`, `engajamento`, `capacidade`, `causas`, `autor`, `created_at`. Migration `0012`, revisão anterior `0011`.

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/integration/test_auditoria_score.py`:

```python
"""A trilha de recalculos de score: tabela, imutabilidade e o gancho no turno.

TEC-152.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from mobia.domain.context.models import LeadScoreAudit

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def linha(**ajustes: object) -> LeadScoreAudit:
    """Um registro valido, com os cinco fatores somando o total."""
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "total_anterior": None,
        "total_novo": 51,
        "completude": 20,
        "urgencia": 15,
        "catalogo": 0,
        "engajamento": 10,
        "capacidade": 6,
        "causas": ["PRIMEIRO_CALCULO"],
    }
    return LeadScoreAudit(**{**base, **ajustes})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    session.add(linha())
    await session.commit()

    gravado = (await session.scalars(select(LeadScoreAudit))).one()
    assert gravado.total_novo == 51
    assert gravado.total_anterior is None
    assert gravado.causas == ["PRIMEIRO_CALCULO"]
    assert gravado.autor is None
    assert gravado.created_at is not None


async def test_o_check_recusa_um_total_que_nao_soma(session) -> None:
    """O total e denormalizado de proposito -- e por ele que se ordena --, e a
    restricao e o que impede a denormalizacao de mentir."""
    session.add(linha(total_novo=99))

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_update_e_recusado_pela_trigger(session) -> None:
    """Cenario 3 da card: "quando se tenta altera-lo, a operacao e recusada"."""
    session.add(linha())
    await session.commit()

    with pytest.raises(DBAPIError, match="imutavel"):
        await session.execute(text("UPDATE lead_score_audit SET total_novo = 99"))

    # A transacao fica abortada depois da excecao do Postgres; sem isto o
    # teardown da fixture reclama em vez de fechar limpo.
    await session.rollback()


async def test_delete_continua_livre(session) -> None:
    """Imutavel e "nao se altera o que foi registrado". A RNF-18 pede retencao
    de 12 meses, ou seja, pede que apagar seja possivel."""
    session.add(linha())
    await session.commit()

    await session.execute(text("DELETE FROM lead_score_audit"))
    await session.commit()

    assert (await session.scalars(select(LeadScoreAudit))).all() == []
```

E acrescente `lead_score_audit` à tupla `TABELAS` em `tests/conftest.py`, em ordem alfabética entre `lead_qualification` e `message_telemetry`:

```python
TABELAS = (
    "conversation_intent",
    "conversation_summaries",
    "lead_qualification",
    # A trilha e append-only e nada a apaga em producao: sem o truncate, os
    # registros de um teste viram o "ultimo recalculo" do proximo.
    "lead_score_audit",
    "message_telemetry",
    "outbound_dispatches",
    "optout_events",
    "messages",
)
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v
```

Esperado: erro de coleta, `ImportError: cannot import name 'LeadScoreAudit'`.

- [ ] **Step 3: Escrever o modelo**

Em `src/mobia/domain/context/models.py`, acrescente ao final do arquivo (e `ARRAY` já está importado de `sqlalchemy.dialects.postgresql`; acrescente `Index` e `text` a `from sqlalchemy import ...`):

```python
class LeadScoreAudit(Base):
    """Um registro por recalculo que mudou o score. Append-only e imutavel.

    TEC-152, RN-06.4. Mesmo molde de `optout_events`: uma linha por evento,
    `server_default` no carimbo porque a ORDEM e o que torna a trilha legivel,
    e sem FK para `messages` nem para `lead_qualification` -- a retencao da
    trilha (12 meses, RNF-18) nao pode ser encurtada por cascata da limpeza de
    outra tabela.

    **So os fatores do score NOVO sao gravados.** Como o registro so entra
    quando o resultado muda, o registro anterior da mesma conversa **e** o
    score anterior; guardar os dois criaria duas fontes para o mesmo fato, que
    e o defeito que a TEC-146 gastou uma card inteira consertando.
    `total_anterior` fica mesmo assim porque e o que a card nomeia e poupa a
    segunda leitura de quem so quer o delta.
    """

    __tablename__ = "lead_score_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Nulo no primeiro registro do lead, e nao zero. O `score.py` ja faz essa
    # distincao: "o zero e a ausencia de sujeito, nao uma nota sobre ele". Um
    # lead cujo primeiro calculo deu 51 nunca teve score 0, e dizer que teve
    # inventaria uma subida de 51 pontos que nao aconteceu.
    total_anterior: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_novo: Mapped[int] = mapped_column(Integer, nullable=False)

    completude: Mapped[int] = mapped_column(Integer, nullable=False)
    urgencia: Mapped[int] = mapped_column(Integer, nullable=False)
    catalogo: Mapped[int] = mapped_column(Integer, nullable=False)
    engajamento: Mapped[int] = mapped_column(Integer, nullable=False)
    capacidade: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nunca NULL e nunca vazio: tupla vazia e o sinal de nao gravar, entao uma
    # linha sem causa nao deveria ter chegado ao INSERT. O vocabulario mora em
    # `context/auditoria.py`.
    causas: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)

    # So na edicao manual pelo dashboard (TEC-192), que ainda nao existe --
    # hoje e sempre nulo. Mesma forma de `optout_events.autor`, nulo no
    # opt-out pela mesma razao: o ato e do lead, nao de um humano nosso.
    autor: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # A consulta quente e "qual o ultimo registro deste lead?", uma vez por
        # turno. DESC no indice para o LIMIT 1 nao ordenar em memoria. Mesmo
        # formato do `ix_optout_events_lead` e do `ix_messages_timeline`.
        Index(
            "ix_lead_score_audit_lead",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )
```

- [ ] **Step 4: Escrever a migration**

Crie `alembic/versions/0012_auditoria_de_score.py`:

```python
"""trilha append-only e imutavel dos recalculos de score

TEC-152, RN-06.4. Uma linha por recalculo que mudou o resultado.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0010: a
retencao da trilha (12 meses, RNF-18) nao pode ser encurtada por cascata da
limpeza de outra tabela.

O CHECK existe porque `total_novo` e denormalizado de proposito -- e por ele
que se ordena e se filtra --, e sem a restricao um fator esquecido na soma
produz uma trilha que parece consistente e nao e.

**A trigger recusa UPDATE e nao DELETE.** Imutavel significa "nao se altera o
que foi registrado"; expurgo por politica de retencao e ato deliberado, nao
alteracao -- e a RNF-18, que pede 12 meses, pede que apagar seja possivel.
Bloquear os dois obrigaria a retencao a passar por um caminho privilegiado que
nao existe neste repo.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_FUNCAO_DA_TRIGGER = """
CREATE FUNCTION lead_score_audit_recusa_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'lead_score_audit e imutavel: UPDATE recusado';
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER = """
CREATE TRIGGER lead_score_audit_imutavel
    BEFORE UPDATE ON lead_score_audit
    FOR EACH ROW EXECUTE FUNCTION lead_score_audit_recusa_update()
"""


def upgrade() -> None:
    op.create_table(
        "lead_score_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("total_anterior", sa.Integer(), nullable=True),
        sa.Column("total_novo", sa.Integer(), nullable=False),
        sa.Column("completude", sa.Integer(), nullable=False),
        sa.Column("urgencia", sa.Integer(), nullable=False),
        sa.Column("catalogo", sa.Integer(), nullable=False),
        sa.Column("engajamento", sa.Integer(), nullable=False),
        sa.Column("capacidade", sa.Integer(), nullable=False),
        sa.Column("causas", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("autor", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "total_novo = completude + urgencia + catalogo + engajamento + capacidade",
            name="ck_lead_score_audit_total",
        ),
    )
    op.create_index(
        "ix_lead_score_audit_lead",
        "lead_score_audit",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )
    op.execute(_FUNCAO_DA_TRIGGER)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS lead_score_audit_imutavel ON lead_score_audit")
    op.execute("DROP FUNCTION IF EXISTS lead_score_audit_recusa_update()")
    op.drop_index("ix_lead_score_audit_lead", table_name="lead_score_audit")
    op.drop_table("lead_score_audit")
```

- [ ] **Step 5: Aplicar a migration e rodar os testes**

```
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v
```

Esperado: 4 passed. Se aparecer `ConnectionResetError [WinError 64]`, espere alguns segundos e retente — o banco demora mais que o healthcheck diz.

- [ ] **Step 6: Testar o ciclo da migration**

Acrescente a `tests/integration/test_migrations.py`:

```python
async def test_a_0012_desce_e_sobe_de_novo() -> None:
    """A trilha some no downgrade e a trigger volta no upgrade.

    A trigger e a funcao sao criadas com `op.execute` e nao pelo autogenerate,
    entao nada garante que o downgrade as derrube -- uma funcao orfa faria o
    upgrade seguinte reprovar com "function already exists".
    """
    await dispose_engine()
    alembic("downgrade", "0011")
    try:
        async with get_sessionmaker()() as sessao:
            assert await sessao.scalar(text("SELECT to_regclass('public.lead_score_audit')")) is None
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert await sessao.scalar(text("SELECT to_regclass('public.lead_score_audit')")) is not None
        assert await sessao.scalar(
            text("SELECT count(*) FROM pg_trigger WHERE tgname = 'lead_score_audit_imutavel'")
        ) == 1
```

Rode: `./.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py -v`. Esperado: todos passam.

- [ ] **Step 7: Verificar por mutação**

Comente a linha `sa.CheckConstraint(...)` da migration, rode `alembic downgrade 0011 && alembic upgrade head`, e rode o arquivo: esperado, `test_o_check_recusa_um_total_que_nao_soma` fica vermelho. Depois comente `op.execute(_TRIGGER)` e repita: esperado, `test_update_e_recusado_pela_trigger` fica vermelho. Desfaça as duas e reaplique.

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0012_auditoria_de_score.py src/mobia/domain/context/models.py tests/conftest.py tests/integration/test_auditoria_score.py tests/integration/test_migrations.py
git commit -m "feat(TEC-152): a trilha existe, soma confere e UPDATE e recusado pelo banco"
```

---

### Task 3: A contagem de mensagens do lead, com uma implementação só

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py`
- Test: `tests/integration/test_auditoria_score.py`

**Interfaces:**
- Consumes: `Message` e `MessageDirection` de `mobia.domain.messages`.
- Produces: `contar_mensagens_do_lead(session: AsyncSession, *, channel: str, conversation_key: str) -> int`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/integration/test_auditoria_score.py` (e junte os imports novos aos que já existem no topo):

```python
from datetime import UTC, datetime

from mobia.domain.context.repositorio import contar_mensagens_do_lead
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt


async def _mensagem(
    session,
    *,
    direction: MessageDirection = MessageDirection.INBOUND,
    bloqueada: bool = False,
) -> None:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD
            if direction is MessageDirection.INBOUND
            else MessageRole.AGENTE,
            direction=direction,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            bloqueada_em=datetime.now(UTC) if bloqueada else None,
        )
    )
    await session.commit()


async def test_a_contagem_ignora_a_fala_do_agente(session) -> None:
    """Fala do agente nao e engajamento do lead, e contar as duas direcoes
    quase dobra o numero e empurra MORNO para QUENTE de graca."""
    await _mensagem(session)
    await _mensagem(session, direction=MessageDirection.OUTBOUND)

    assert await contar_mensagens_do_lead(
        session, channel=CANAL, conversation_key=CONVERSA
    ) == 1


async def test_a_contagem_ignora_a_fala_bloqueada(session) -> None:
    """Um turno que o resto do produto trata como nao-dito nao pode virar ponto
    aqui: `literais_apos` ja filtra `bloqueada_em IS NULL` desde a TEC-236."""
    await _mensagem(session)
    await _mensagem(session, bloqueada=True)

    assert await contar_mensagens_do_lead(
        session, channel=CANAL, conversation_key=CONVERSA
    ) == 1


async def test_a_contagem_de_um_lead_sem_mensagem_e_zero(session) -> None:
    assert await contar_mensagens_do_lead(
        session, channel=CANAL, conversation_key="ninguem"
    ) == 0
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v -k contagem
```

Esperado: `ImportError: cannot import name 'contar_mensagens_do_lead'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/context/repositorio.py`, acrescente aos imports:

```python
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
```

E a função, ao final do arquivo:

```python
async def contar_mensagens_do_lead(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> int:
    """As falas de ENTRADA do lead que a moderacao nao bloqueou.

    **Esta e a unica implementacao do contrato, e existe para que a TEC-151
    nao escreva a segunda.** A docstring de `calcular_score` fixa a definicao
    palavra por palavra e nomeia o risco: tres leituras eram defensaveis, e
    duas fontes para o mesmo fato divergiriam em silencio -- que e o defeito
    que a TEC-146 gastou uma card inteira consertando. Quem precisar da
    contagem chama daqui.

    `status` nao entra: RECEIVED, QUEUED e PROCESSED descrevem o pipeline de
    ingestao, nao se o lead falou, e filtrar por eles faria a contagem oscilar
    com retentativa.

    Inclui a mensagem do turno corrente -- a ingestao a persiste antes de o job
    rodar.
    """
    total = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.channel == channel,
            Message.conversation_key == conversation_key,
            Message.direction == MessageDirection.INBOUND,
            Message.bloqueada_em.is_(None),
        )
    )
    return total or 0
```

- [ ] **Step 4: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v
```

Esperado: 7 passed.

- [ ] **Step 5: Verificar por mutação**

Remova a cláusula `Message.direction == MessageDirection.INBOUND`: esperado, só `test_a_contagem_ignora_a_fala_do_agente` fica vermelho. Desfaça. Remova `Message.bloqueada_em.is_(None)`: esperado, só `test_a_contagem_ignora_a_fala_bloqueada` fica vermelho. Desfaça.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/repositorio.py tests/integration/test_auditoria_score.py
git commit -m "feat(TEC-152): a contagem de mensagens do lead ganha a implementacao unica que o contrato pedia"
```

---

### Task 4: O orquestrador que trava, recalcula e grava

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py`
- Test: `tests/integration/test_auditoria_score.py`

**Interfaces:**
- Consumes: `calcular_score` e `Score` de `mobia.domain.context.score`; `causas_do_recalculo` de `mobia.domain.context.auditoria`; `contar_mensagens_do_lead` (Task 3); `LeadScoreAudit` e `LeadQualification` de `mobia.domain.context.models`.
- Produces: `registrar_recalculo(session: AsyncSession, *, channel: str, conversation_key: str) -> LeadScoreAudit | None` — devolve a linha gravada, ou `None` quando não havia estado ou o score não mudou. **Não commita:** a sessão é emprestada, como em `gravar_estado`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/integration/test_auditoria_score.py`:

```python
from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import registrar_recalculo


async def _qualificacao(session, **ajustes: object) -> None:
    """Os quatro obrigatorios preenchidos, menos o que o teste mudar."""
    base: dict[str, object] = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.ATE_3_MESES.value,
    }
    session.add(LeadQualification(**{**base, **ajustes}))
    await session.commit()


async def test_o_primeiro_recalculo_grava_com_anterior_nulo(session) -> None:
    """Quatro obrigatorios (20), ATE_3_MESES (15), uma mensagem (10), sem forma
    de pagamento (6) = 51."""
    await _qualificacao(session)
    await _mensagem(session)

    gravada = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA
    )
    await session.commit()

    assert gravada is not None
    assert gravada.total_anterior is None
    assert gravada.total_novo == 51
    assert (gravada.completude, gravada.urgencia, gravada.catalogo) == (20, 15, 0)
    assert (gravada.engajamento, gravada.capacidade) == (10, 6)
    assert gravada.causas == ["PRIMEIRO_CALCULO"]


async def test_o_recalculo_que_nao_move_nada_nao_grava(session) -> None:
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA
    ) is None
    await session.commit()

    assert len((await session.scalars(select(LeadScoreAudit))).all()) == 1


async def test_informar_a_vista_grava_o_delta_da_capacidade(session) -> None:
    """O cenario 1 da card, no equivalente alcancavel: 51 -> 60.

    A card diz 48 -> 63, um delta de 15. A vista move `capacidade` de 6 para
    15 -- delta de 9 --, e na escala da TEC-150 nenhum dos dois numeros e
    alcancavel hoje: 63 nao existe com `imoveis_compativeis=0`, e 48 so existe
    para quem JA paga a vista. Ver a secao correspondente do desenho.
    """
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    estado = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert estado is not None
    estado.forma_pagamento = FormaPagamento.A_VISTA.value
    await session.commit()

    gravada = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA
    )
    await session.commit()

    assert gravada is not None
    assert (gravada.total_anterior, gravada.total_novo) == (51, 60)
    assert gravada.causas == ["FORMA_DE_PAGAMENTO"]


async def test_sem_linha_de_qualificacao_nao_ha_o_que_auditar(session) -> None:
    """`calcular_score(None)` devolve zerado, e o `score.py` distingue a
    ausencia de sujeito de uma nota igual a zero."""
    await _mensagem(session)

    assert await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA
    ) is None
    assert (await session.scalars(select(LeadScoreAudit))).all() == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v -k recalculo
```

Esperado: `ImportError: cannot import name 'registrar_recalculo'`.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/context/repositorio.py`, acrescente aos imports:

```python
from mobia.domain.context.auditoria import causas_do_recalculo
from mobia.domain.context.models import LeadScoreAudit
from mobia.domain.context.score import Score, calcular_score
```

(`LeadScoreAudit` entra na linha de import que já traz `ConversationSummary, LeadQualification, aad_do_resumo`.)

E as funções, ao final do arquivo:

```python
def _score_do_registro(registro: LeadScoreAudit | None) -> Score | None:
    """Reconstroi o `Score` de um registro da trilha.

    Existe porque a comparacao da RN-06.4 emendada e sobre os cinco fatores, e
    nao sobre o total: um registro guarda os cinco em colunas, e compara-los
    exige remonta-los no tipo que `causas_do_recalculo` recebe.
    """
    if registro is None:
        return None
    return Score(
        completude=registro.completude,
        urgencia=registro.urgencia,
        catalogo=registro.catalogo,
        engajamento=registro.engajamento,
        capacidade=registro.capacidade,
    )


async def registrar_recalculo(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> LeadScoreAudit | None:
    """Recalcula o score do lead e grava a trilha se ele mudou.

    Devolve a linha gravada, ou `None` quando nao havia estado a pontuar ou
    quando o resultado foi identico ao ultimo registrado.

    Nao commita -- a sessao e emprestada, como em `gravar_estado`, e quem chama
    e dono da fronteira da transacao. A trilha tem de entrar no MESMO commit
    que o estado: uma trilha que registrasse um score calculado sobre um estado
    que o rollback desfez seria pior que trilha nenhuma, porque e lida
    justamente por quem ja desconfia do numero.

    **O estado vem do `SELECT ... FOR UPDATE` daqui, e nao de fora.** Reusar o
    retorno de `gravar_estado` ou o `contexto.estado` do turno pareceria mais
    barato -- os dois ja estao em maos -- e seria errado no caminho sem campos:
    `contexto.estado` foi lido por `montar_contexto` numa OUTRA sessao, antes
    deste bloco, e um turno concorrente da mesma conversa pode ter commitado
    uma alteracao no intervalo. Como o lock precisa do statement de qualquer
    jeito, deixa-lo devolver a linha custa zero e apaga a questao.

    **O lock nao e decorativo: turnos da mesma conversa NAO sao
    serializados.** A deduplicacao do ARQ e por mensagem (`_job_id =
    msg:<id>`), nao por conversa, e a protecao contra paralelismo e uma
    invariante de tempo (`job_timeout` < `sweep_inflight_after_seconds`), nao
    um lock. Sem ele, dois recalculos concorrentes leem o mesmo ultimo
    registro, ambos veem mudanca e ambos gravam -- dois registros com o mesmo
    `total_anterior`, e a cadeia deixa de reconstruir a evolucao. No turno COM
    campos o lock ja foi tomado pelo `ON CONFLICT DO UPDATE` de
    `gravar_estado` e este e redundante; no turno SEM campos nao ha upsert, e e
    exatamente o caminho em que a unica mudanca vem da contagem de mensagens.
    """
    estado = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
            # Mesma razao do `populate_existing` de `gravar_estado`: no turno
            # com campos a sessao ACABOU de carregar esta linha pelo RETURNING
            # do upsert, e sem a opcao o identity map devolve a instancia que a
            # sessao ja tem em vez da linha que o banco mandou. A releitura que
            # existe justamente para nao usar estado velho devolveria estado
            # velho, com o lock tomado e tudo parecendo certo.
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if estado is None:
        return None

    novo = calcular_score(
        estado,
        mensagens_do_lead=await contar_mensagens_do_lead(
            session, channel=channel, conversation_key=conversation_key
        ),
        # Explicito, e nao pelo default: a busca de imoveis (TEC-158) nao
        # existe, e a TEC-150 prescreve que ate la o fator contribua zero.
        # Quando ela existir, este e o unico ponto que muda.
        imoveis_compativeis=0,
    )

    ultimo = (
        await session.scalars(
            select(LeadScoreAudit)
            .where(
                LeadScoreAudit.channel == channel,
                LeadScoreAudit.conversation_key == conversation_key,
            )
            .order_by(LeadScoreAudit.created_at.desc())
            .limit(1)
        )
    ).first()

    causas = causas_do_recalculo(_score_do_registro(ultimo), novo)
    if not causas:
        return None

    linha = LeadScoreAudit(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        total_anterior=ultimo.total_novo if ultimo is not None else None,
        total_novo=novo.total,
        completude=novo.completude,
        urgencia=novo.urgencia,
        catalogo=novo.catalogo,
        engajamento=novo.engajamento,
        capacidade=novo.capacidade,
        causas=list(causas),
    )
    session.add(linha)
    # Flush e nao commit: a linha precisa existir no banco para o proximo
    # `registrar_recalculo` da mesma transacao a enxergar como "ultimo", e o
    # commit e de quem chamou.
    await session.flush()
    return linha
```

- [ ] **Step 4: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v
```

Esperado: 11 passed.

- [ ] **Step 5: Verificar por mutação**

Troque `if not causas: return None` por `if False: return None`: esperado, `test_o_recalculo_que_nao_move_nada_nao_grava` fica vermelho. Desfaça. Troque `total_anterior=ultimo.total_novo if ultimo is not None else None` por `total_anterior=0`: esperado, `test_o_primeiro_recalculo_grava_com_anterior_nulo` fica vermelho. Desfaça.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/repositorio.py tests/integration/test_auditoria_score.py
git commit -m "feat(TEC-152): o recalculo trava a linha, rele o estado e grava so quando muda"
```

---

### Task 5: O gancho no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (o bloco de `async with session_factory()` que hoje termina em `await session.commit()`, por volta da linha 300)
- Test: `tests/integration/test_auditoria_score.py`

**Interfaces:**
- Consumes: `registrar_recalculo` (Task 4).
- Produces: nada de novo — o comportamento passa a existir em produção.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `tests/integration/test_auditoria_score.py`:

```python
from decimal import Decimal

from mobia.domain.agente.schemas import Extracao


async def test_o_turno_grava_a_trilha(
    session, session_factory, rodar_turno, classificador_fake, outbound_fake,
    resumidor_fake, contador_fake,
) -> None:
    """O turno passa a recalcular, e o primeiro registro do lead aparece."""
    await rodar_turno(
        session,
        classificador_fake(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            extracao=Extracao(regiao="vila mariana", urgencia=Urgencia.ATE_3_MESES),
        ),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    registros = (await session.scalars(select(LeadScoreAudit))).all()
    assert len(registros) == 1
    assert registros[0].total_anterior is None
    assert registros[0].causas == ["PRIMEIRO_CALCULO"]
    # Tres dos quatro obrigatorios -- intencao, regiao, urgencia; falta
    # `faixa_preco` -- sao 15 de completude, mais urgencia ATE_3_MESES (15),
    # uma mensagem (10) e nenhuma forma de pagamento (6).
    assert registros[0].total_novo == 46


async def test_o_turno_que_nao_move_o_score_nao_grava_de_novo(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake,
    contador_fake,
) -> None:
    """A partir da segunda mensagem o engajamento ja esta em 10 e nao sobe de
    novo antes da sexta, entao um turno que repete a mesma extracao nao move
    fator nenhum."""
    def turno():
        return rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA,
                confianca=Decimal("0.95"),
                extracao=Extracao(regiao="vila mariana", urgencia=Urgencia.ATE_3_MESES),
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    await turno()
    antes = len((await session.scalars(select(LeadScoreAudit))).all())
    await turno()
    depois = len((await session.scalars(select(LeadScoreAudit))).all())

    assert antes == 1
    assert depois == 1


async def test_a_trilha_reconstroi_a_evolucao_em_ordem(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake,
    contador_fake,
) -> None:
    """Cenario 4 da card: os registros aparecem em ordem cronologica com os
    respectivos motivos."""
    extracoes = [
        Extracao(regiao="vila mariana"),
        Extracao(urgencia=Urgencia.ATE_3_MESES),
        Extracao(forma_pagamento=FormaPagamento.A_VISTA),
    ]
    for extracao in extracoes:
        await rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA, confianca=Decimal("0.95"), extracao=extracao
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    registros = (
        await session.scalars(
            select(LeadScoreAudit).order_by(LeadScoreAudit.created_at)
        )
    ).all()

    assert [r.causas for r in registros][0] == ["PRIMEIRO_CALCULO"]
    assert [r.total_novo for r in registros] == sorted(r.total_novo for r in registros)
    assert registros[-1].causas == ["FORMA_DE_PAGAMENTO"]
    # A cadeia fecha: o `total_novo` de cada registro e o `total_anterior` do
    # seguinte.
    for anterior, seguinte in zip(registros, registros[1:], strict=False):
        assert seguinte.total_anterior == anterior.total_novo
```

Junte os imports novos aos que o arquivo já tem no topo — `Intencao`, `Urgencia` e `FormaPagamento` chegaram na Task 4, e aqui só `Extracao` e `Decimal` são novos.

- [ ] **Step 2: Rodar e confirmar que falha**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v -k turno
```

Esperado: os três falham porque nenhum registro é criado — `assert len(registros) == 1` recebe 0.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/agente/turno.py`, acrescente ao import que já traz `gravar_estado`:

```python
from mobia.domain.context.repositorio import gravar_estado, marcar_perguntados, registrar_recalculo
```

E, no bloco transacional, entre `gravar_estado` e o `commit`:

```python
        depois_do_estado = await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
        )
        # A trilha entra no mesmo commit que o estado, pela mesma razao que a
        # intencao e a extracao entram: ou os dois fatos existem, ou nenhum.
        #
        # Chamada em cada turno com estado, e nao so quando `gravar_estado`
        # devolveu linha: o engajamento depende da contagem de mensagens, que
        # sobe em todo turno, e as travessias de faixa dele podem cair num
        # turno sem campo nenhum. Amarrar o recalculo a escrita de campo
        # deixaria essas subidas fora da trilha.
        #
        # Nao recebe `depois_do_estado`: `registrar_recalculo` rele a linha sob
        # lock, e o motivo esta na docstring dele. `depois_do_estado` continua
        # valendo abaixo -- a releitura acontece na mesma sessao e na mesma
        # transacao, entao as duas referencias apontam para a mesma linha.
        await registrar_recalculo(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
        )
        await session.commit()
```

- [ ] **Step 4: Rodar e confirmar que passa**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_auditoria_score.py -v
```

Esperado: 14 passed.

- [ ] **Step 5: Rodar os testes de turno que já existiam**

O gancho entra num caminho que muitos testes exercitam. Rode, um de cada vez para não confundir flake de carga com regressão:

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_optout.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_extracao_no_turno.py -v
```

Esperado: todos passam. Se algum falhar com `ConnectionResetError` ou erro de Redis, rode o arquivo sozinho de novo antes de investigar.

- [ ] **Step 6: Verificar por mutação**

Comente a chamada a `registrar_recalculo`: esperado, os três testes de turno da Task 5 ficam vermelhos e os das Tasks 1–4 seguem verdes. Desfaça.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/integration/test_auditoria_score.py
git commit -m "feat(TEC-152): o score sai do limbo e passa a ser recalculado a cada turno"
```

---

### Task 6: A emenda ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (a linha 198, `RN-06.4`)

**Interfaces:**
- Consumes: nada. Produces: nada. É documentação, e o repo trata emenda como parte da entrega.

- [ ] **Step 1: Acrescentar a emenda**

A convenção do repo: emendas entram como item **aninhado** abaixo da regra que alteram, **nunca** reescrevendo o texto de 22/08/2026. A numeração é por regra, e a RN-06.4 não tem emendas — logo, `E-01`. Veja as duas emendas existentes (linhas 145 e 172) para o formato exato.

Abaixo da linha da `RN-06.4`, acrescente:

```markdown
  - **Emenda E-01 (TEC-152, 02/09/2026):** o registro é gravado quando o resultado do recálculo **difere do último registrado**, e não a cada recálculo. A comparação é sobre os cinco fatores, não sobre o total — completude +15 com urgência −15 deixa o total igual e é justamente o caso que a trilha existe para explicar. O gancho roda a cada turno com estado, e a maioria dos recálculos não move nada: uma linha por mensagem de entrada enterraria as transições no meio das duplicatas. A consequência declarada é que a trilha não prova que um recálculo *aconteceu*, só que o resultado *mudou*.
```

- [ ] **Step 2: Conferir que o texto original ficou intacto**

```
git diff docs/srs/srs-agente-sdr-imobiliario-v1.0.md
```

Esperado: só linhas acrescentadas (`+`), nenhuma removida. Se aparecer um `-`, você reescreveu a regra em vez de emendá-la.

- [ ] **Step 3: Rodar a suíte inteira**

Agora, e não antes — ela leva ~7,5 minutos e imprime só no fim:

```
./.venv/Scripts/python.exe -u -m pytest -v
```

Esperado: 857 + os 14 novos, todos passando. Falha isolada em `test_montagem.py`, `test_sweep_stalled.py` ou `test_dedup_por_message_id.py` sob carga não é regressão desta card — rode o arquivo sozinho para confirmar.

- [ ] **Step 4: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-152): a RN-06.4 passa a admitir que so o recalculo que muda algo e gravado"
```

---

## Checklist de fechamento

- [ ] Os três gates estáticos passam com o escopo `src tests alembic evals`.
- [ ] A suíte inteira passa.
- [ ] `alembic downgrade 0011 && alembic upgrade head` funciona duas vezes seguidas (a trigger e a função não ficam órfãs).
- [ ] Nenhum comentário descreve código que mudou.
- [ ] A emenda no SRS só acrescentou linhas.
- [ ] Abrir PR contra `main` a partir de `feat/tec-152-auditoria-de-recalculo-de-score`.

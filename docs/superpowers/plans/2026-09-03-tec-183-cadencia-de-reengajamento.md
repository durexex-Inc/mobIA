# TEC-183 — Cadência de reengajamento: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decidir, a cada cinco minutos, quais leads estão devidos de follow-up segundo a régua da RN-13.1, registrar cada disparo numa trilha append-only, e emitir o evento que a TEC-184 vai consumir para gerar e enviar a mensagem.

**Architecture:** Nada é agendado. Uma função pura calcula, a partir da última fala do lead (a **âncora**) e da temperatura de hoje, qual tentativa está vencida agora. Um job `cron` varre os candidatos, consulta o opt-out, grava a tentativa e loga. As três regras dinâmicas da card — resposta reinicia, temperatura recalcula, intervalo vem de configuração — saem como consequência aritmética, sem caminho de escrita próprio.

**Tech Stack:** Python 3.12+, SQLAlchemy async, Alembic, Postgres, ARQ (`cron`), pytest, structlog, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md`

**Branch:** `feat/tec-183-cadencia-de-reengajamento` (já criada).

## Global Constraints

- **Os três gates estáticos, nesta ordem, antes de cada commit.** O formatador é gate separado do linter; passar num não diz nada sobre o outro:
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals`
  - `./.venv/Scripts/python.exe -m mypy`
  - O escopo do ruff é `src tests alembic evals`, **não** `src tests`. O mypy roda sem argumento de caminho e cobre só `src`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento. Convenção do repo, nenhum linter checa.
- **Comentário desatualizado é defeito.** Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **Mensagem de commit:** português sem acento no assunto, formato `tipo(TEC-183): o que passou a ser verdade`.
- **A suíte é lenta.** A completa leva ~12 minutos e ~1078 testes. Com `-q` a saída só aparece no fim; use `-u -m pytest -v` quando precisar de progresso. Rode a suíte inteira só onde o plano mandar.
- **O banco demora mais que o healthcheck diz.** Depois de subir os containers, o `alembic upgrade head` e a fixture `migrar_banco` podem reprovar por vários segundos com `ConnectionResetError [WinError 64]` na negociação SSL, com o container já `healthy`, produzindo centenas de `ERROR` de setup que parecem catástrofe. **Não é.** Espere e retente antes de investigar qualquer coisa.
- **Testes de integração flakeiam sob carga** e passam isolados. Rode o arquivo sozinho antes de culpar sua mudança.
- **Basename de teste nunca colide entre `tests/unit` e `tests/integration`.** Colisão aborta a coleta da suíte inteira e não aparece no arquivo isolado; já custou duas cards. Os basenames deste plano (`test_cadencia.py`, `test_followups_model.py`, `test_sweep_followups.py`) não existem em nenhum dos dois diretórios — confira antes de renomear.
- **Não toque no prompt.** Nada aqui acrescenta texto a `SISTEMA_DO_AGENTE` nem campo a `SCHEMA_DA_RESPOSTA`. A margem é 6,2 tokens sobre o teto fixo de 655.
- **Nada nesta card envia mensagem ao lead.** Se você se pegar chamando `outbound.send`, pare e releia o Objetivo da spec: o texto é da TEC-184, e a RN-13.2 proíbe improvisar um.

## File Structure

**Criados:**

| arquivo | responsabilidade |
|---|---|
| `src/mobia/domain/followup/__init__.py` | pacote novo, vazio |
| `src/mobia/domain/followup/cadencia.py` | a régua da RN-13.1: `CADENCIA`, `INTERVALO_MINIMO`, `tentativa_devida`. Pura |
| `src/mobia/domain/followup/models.py` | o modelo `FollowUp` da tabela append-only |
| `src/mobia/domain/followup/repositorio.py` | a consulta de candidatos e o registro do disparo |
| `alembic/versions/0015_cadencia_de_followup.py` | tabela `followups`, com `UNIQUE` e `CHECK` |
| `src/mobia/workers/jobs/sweep_followups.py` | o job `cron` que orquestra |
| `tests/unit/test_cadencia.py` | a régua, sem banco |
| `tests/integration/test_followups_model.py` | `UNIQUE`, `CHECK` e a consulta de candidatos |
| `tests/integration/test_sweep_followups.py` | o job ponta a ponta |

**Modificados:**

| arquivo | mudança |
|---|---|
| `src/mobia/workers/main.py` | importa e registra `sweep_followups` em `functions` e `cron_jobs` |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | emenda `E-01` à RN-13.4, mais linha na tabela do topo |
| `docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md` | linha de status |

---

### Task 1: A régua, como função pura

**Files:**
- Create: `src/mobia/domain/followup/__init__.py` (vazio), `src/mobia/domain/followup/cadencia.py`
- Test: `tests/unit/test_cadencia.py`

**Interfaces:**
- Consumes: `Temperatura` de `mobia.domain.context.temperatura` — StrEnum com `QUENTE`/`MORNO`/`FRIO`, já no repo.
- Produces: `CADENCIA: dict[Temperatura, tuple[timedelta, ...]]`, `INTERVALO_MINIMO: timedelta`, e `tentativa_devida(*, temperatura: Temperatura, ultima_fala: datetime, ja_disparada: int, agora: datetime) -> int | None`. As Tasks 3 e 4 importam os três.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_cadencia.py`:

```python
"""A regua da RN-13.1: qual tentativa de follow-up esta vencida agora.

TEC-183. Sem banco: a funcao e pura.
"""

from datetime import UTC, datetime, timedelta

import pytest

from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA, INTERVALO_MINIMO, tentativa_devida

ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def devida(temperatura: Temperatura, passado: timedelta, ja_disparada: int = 0) -> int | None:
    return tentativa_devida(
        temperatura=temperatura,
        ultima_fala=ANCORA,
        ja_disparada=ja_disparada,
        agora=ANCORA + passado,
    )


@pytest.mark.parametrize(
    ("temperatura", "tentativas"),
    [(Temperatura.QUENTE, 4), (Temperatura.MORNO, 3), (Temperatura.FRIO, 2)],
)
def test_o_numero_de_tentativas_por_temperatura(
    temperatura: Temperatura, tentativas: int
) -> None:
    """A tabela da RN-13.1, e o criterio de aceite que a repete."""
    assert len(CADENCIA[temperatura]) == tentativas


def test_os_intervalos_sao_os_do_srs() -> None:
    """Se estes numeros mudarem, foi decisao de alguem -- nao deixe passar em
    silencio. A RN-13.1 fixa os tres conjuntos."""
    assert CADENCIA[Temperatura.QUENTE] == (
        timedelta(hours=2),
        timedelta(hours=24),
        timedelta(days=3),
        timedelta(days=7),
    )
    assert CADENCIA[Temperatura.MORNO] == (
        timedelta(hours=24),
        timedelta(days=4),
        timedelta(days=10),
    )
    assert CADENCIA[Temperatura.FRIO] == (timedelta(days=3), timedelta(days=14))


def test_a_primeira_tentativa_do_quente_vence_em_duas_horas() -> None:
    """A CA-13.1: parou as 18h, follow-up as 20h."""
    assert devida(Temperatura.QUENTE, timedelta(hours=2)) == 1


def test_um_minuto_antes_nao_vence() -> None:
    assert devida(Temperatura.QUENTE, timedelta(hours=1, minutes=59)) is None


def test_a_borda_e_inclusiva() -> None:
    """`>=` e nao `>`: no instante exato do deslocamento a tentativa vence.
    Com `>` um disparo poderia escorregar para a varredura seguinte por um
    microssegundo, e a diferenca so apareceria em producao."""
    assert devida(Temperatura.QUENTE, CADENCIA[Temperatura.QUENTE][0]) == 1


def test_os_deslocamentos_sao_desde_a_ancora_e_nao_encadeados() -> None:
    """A RN-13.1 diz "contada a partir da ultima mensagem do lead". A segunda
    tentativa do QUENTE vence em +24h desde a ANCORA, nao 24h depois da
    primeira -- se fosse encadeada, venceria so em +26h."""
    assert devida(Temperatura.QUENTE, timedelta(hours=24), ja_disparada=1) == 2
    assert devida(Temperatura.QUENTE, timedelta(hours=23), ja_disparada=1) is None


def test_o_lead_muito_atrasado_recebe_so_a_ultima_vencida() -> None:
    """A decisao mais facil de errar do desenho.

    Dez dias de silencio deixam as quatro tentativas do QUENTE vencidas ao
    mesmo tempo. Devolvendo "a proxima", este lead receberia quatro follow-ups
    em vinte minutos (uma por varredura de 5 min). Devolve a MAIOR vencida, e a
    cadencia fecha de uma vez.
    """
    assert devida(Temperatura.QUENTE, timedelta(days=10)) == 4


def test_depois_do_salto_nao_sobra_nada_para_tras() -> None:
    """O motivo de `ja_disparada` ser o MAX e nao um COUNT.

    Com contagem, o lead do teste acima teria `ja_disparada=1` na varredura
    seguinte, a regua acharia que so uma foi feita e disparia a 2 -- refazendo
    para tras uma tentativa que o salto ja tornou obsoleta.
    """
    assert devida(Temperatura.QUENTE, timedelta(days=10), ja_disparada=4) is None


def test_a_cadencia_esgotada_devolve_none() -> None:
    assert devida(Temperatura.FRIO, timedelta(days=30), ja_disparada=2) is None


def test_esfriar_encurta_a_cadencia_restante() -> None:
    """"Mudanca de temperatura recalcula a cadencia restante": um lead que
    recebeu tres tentativas como QUENTE e esfriou para MORNO nao recebe a
    quarta, porque MORNO tem tres."""
    assert devida(Temperatura.MORNO, timedelta(days=30), ja_disparada=3) is None


def test_esquentar_alonga_a_cadencia_restante() -> None:
    """O outro lado da mesma regra: MORNO esgotado que esquenta ganha a quarta
    do QUENTE."""
    assert devida(Temperatura.QUENTE, timedelta(days=30), ja_disparada=3) == 4


def test_o_intervalo_minimo_e_derivado_e_nao_escrito_a_mao() -> None:
    """A varredura usa este valor como corte barato: nada abaixo dele pode
    estar devido em temperatura nenhuma. Derivado de `CADENCIA` para nao virar
    uma segunda fonte que diverge quando alguem mexer na tabela."""
    assert INTERVALO_MINIMO == timedelta(hours=2)
    assert INTERVALO_MINIMO == min(intervalos[0] for intervalos in CADENCIA.values())


def test_os_argumentos_sao_keyword_only() -> None:
    """`ultima_fala` e `agora` sao dois `datetime` adjacentes: trocar a ordem
    nao levanta, nao e erro de tipo, nao e visivel ao mypy, e devolve a
    tentativa errada em silencio. Mesma razao dos flags de `temperatura_de`."""
    with pytest.raises(TypeError):
        tentativa_devida(Temperatura.QUENTE, ANCORA, 0, ANCORA)  # type: ignore[misc]
```

- [ ] **Step 2: Rode o teste para confirmar que ele falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_cadencia.py -v`
Expected: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.followup'`.

- [ ] **Step 3: Escreva a implementação mínima**

Crie `src/mobia/domain/followup/__init__.py` vazio, e `src/mobia/domain/followup/cadencia.py`:

```python
"""A regua da cadencia de reengajamento: quem esta devido, e de qual tentativa.

TEC-183, RN-13.1. Pura de proposito: sem I/O, sem banco, sem chamada ao
modelo -- mesma forma de `score.py`, `temperatura.py` e `gatilhos.py`. Quem
consulta o banco e decide gravar e o repositorio; aqui so se faz a conta.

**Os deslocamentos sao contados desde a ancora, e nao encadeados.** A RN-13.1
diz "contada a partir da ultima mensagem do lead", e a CA-13.1 confirma com
numero: parou as 18h, follow-up as 20h. Entao a tentativa N vence em
`ultima_fala + CADENCIA[temperatura][N-1]`, e nao "24h depois do follow-up
anterior". A diferenca e observavel: encadeando, um atraso na varredura
empurraria toda a cauda; ancorando, um disparo atrasado nao desloca os
seguintes.

**Constantes de modulo, e nao configuracao.** A card pede intervalos
ajustaveis sem deploy; isso e um subsistema (persistir, autorizar, invalidar
cache) e pertence ao epico de configuracao (RF-19), exatamente como a TEC-150
decidiu para os pesos do score. Lacuna declarada no desenho.
"""

from datetime import datetime, timedelta

from mobia.domain.context.temperatura import Temperatura

# A tabela da RN-13.1, literal. A ordem dentro de cada tupla e a ordem das
# tentativas, e o indice N-1 e o deslocamento da tentativa N.
CADENCIA: dict[Temperatura, tuple[timedelta, ...]] = {
    Temperatura.QUENTE: (
        timedelta(hours=2),
        timedelta(hours=24),
        timedelta(days=3),
        timedelta(days=7),
    ),
    Temperatura.MORNO: (
        timedelta(hours=24),
        timedelta(days=4),
        timedelta(days=10),
    ),
    Temperatura.FRIO: (
        timedelta(days=3),
        timedelta(days=14),
    ),
}

# O corte barato da varredura: nada abaixo disto pode estar devido em
# temperatura nenhuma, entao a consulta descarta o lead sem olhar mais nada.
#
# Derivado e nao escrito a mao de proposito. Escrito a mao, seria uma segunda
# fonte para um fato que `CADENCIA` ja guarda -- e quem mexesse na tabela
# deixaria o corte para tras em silencio, filtrando leads que agora estariam
# devidos mais cedo.
INTERVALO_MINIMO: timedelta = min(intervalos[0] for intervalos in CADENCIA.values())


def tentativa_devida(
    *,
    temperatura: Temperatura,
    ultima_fala: datetime,
    ja_disparada: int,
    agora: datetime,
) -> int | None:
    """A MAIOR tentativa vencida que ainda nao disparou. `None` se nao ha.

    **Devolve a maior vencida, e nao a proxima.** Um lead QUENTE calado ha dez
    dias tem as quatro vencidas ao mesmo tempo; devolvendo "a proxima", ele
    receberia uma por varredura -- quatro follow-ups em vinte minutos, para
    alguem que sumiu ha dez dias. As tres que passaram nao sao "perdidas": os
    deslocamentos sao absolutos desde a ancora, entao o momento de mandar a de
    +2h acabou ha dez dias, e manda-la agora entregaria uma mensagem cujo
    pressuposto de tempo ja e falso.

    **`ja_disparada` e o MAIOR numero de tentativa ja gravado sob esta ancora,
    e nao uma contagem.** Com contagem, o lead do exemplo receberia a 4
    (contagem 0) e, na varredura seguinte, a regua acharia que so uma foi feita
    e dispararia a 2 -- refazendo para tras. Com o maximo, a 4 fecha a cadencia
    inteira. A diferenca so aparece quando ha salto.

    **Zero e o valor de "nunca disparou sob esta ancora"**, e e o que o
    repositorio devolve quando nao ha linha -- a numeracao das tentativas e
    1-based.

    **A borda e inclusiva (`>=`).** No instante exato do deslocamento a
    tentativa vence; com `>` um disparo escorregaria para a varredura seguinte
    por um microssegundo.

    Tudo keyword-only: `ultima_fala` e `agora` sao dois `datetime` adjacentes,
    e trocar a ordem nao levanta, nao e erro de tipo, nao e visivel ao mypy, e
    devolve a tentativa errada em silencio. Mesma razao das duas contagens de
    `calcular_score` e dos dois flags de `temperatura_de`.
    """
    decorrido = agora - ultima_fala
    for numero in range(len(CADENCIA[temperatura]), ja_disparada, -1):
        if decorrido >= CADENCIA[temperatura][numero - 1]:
            return numero
    return None
```

**Sobre o laço:** ele percorre de trás para frente e para na primeira vencida, que é a maior; o limite inferior `ja_disparada` (exclusivo em `range`) é o que garante `N > ja_disparada` sem um segundo `if`.

- [ ] **Step 4: Rode o teste para confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_cadencia.py -v`
Expected: PASS, 15 testes (3 da parametrização + 12 avulsos).

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. Se o `format --check` reclamar, rode `./.venv/Scripts/python.exe -m ruff format src tests alembic evals` e confira o diff.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/followup/ tests/unit/test_cadencia.py
git commit -m "feat(TEC-183): a regua da RN-13.1 passa a dizer qual tentativa esta vencida"
```

---

### Task 2: A tabela `followups` e o modelo

**Files:**
- Create: `alembic/versions/0015_cadencia_de_followup.py`, `src/mobia/domain/followup/models.py`
- Test: `tests/integration/test_followups_model.py`

**Interfaces:**
- Consumes: `Base` de `mobia.domain.messages.models` (é de onde `OptoutEvent` e `LeadScoreAudit` herdam).
- Produces: `FollowUp`, mapeado em `followups`, com `id`, `channel`, `conversation_key`, `tentativa_numero`, `temperatura`, `ancora_em`, `devido_em`, `created_at`. As Tasks 3 e 4 leem e escrevem.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/integration/test_followups_model.py`:

```python
"""A trilha de follow-ups, e as duas invariantes que o banco garante.

TEC-183. Integracao: o UNIQUE e o CHECK vivem no banco.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.followup.models import FollowUp

CANAL = "whatsapp"
CONVERSA = "5511955554444"
ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _linha(**campos) -> FollowUp:
    base = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "tentativa_numero": 1,
        "temperatura": "QUENTE",
        "ancora_em": ANCORA,
        "devido_em": ANCORA + timedelta(hours=2),
    }
    return FollowUp(**{**base, **campos})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    linha = _linha()
    session.add(linha)
    await session.commit()

    gravada = await session.get(FollowUp, linha.id)
    assert gravada is not None
    assert gravada.tentativa_numero == 1
    assert gravada.ancora_em == ANCORA
    # `server_default=clock_timestamp()`: o banco carimba, nao o cliente.
    assert gravada.created_at is not None


async def test_o_unique_recusa_a_mesma_tentativa_sob_a_mesma_ancora(session) -> None:
    """A defesa contra duas varredura concorrentes.

    Nao da para usar `FOR UPDATE SKIP LOCKED` sobre a agregacao que produz os
    candidatos, entao a exclusao mora aqui -- mesmo espirito dos CHECK da 0014
    e da 0012: a invariante no banco, e nao na esperanca de que so um worker
    rode.
    """
    session.add(_linha())
    await session.commit()

    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_mesma_tentativa_sob_outra_ancora_e_permitida(session) -> None:
    """O reinicio da RN-13.4: o lead respondeu, a ancora mudou, e a tentativa 1
    volta a ser legitima."""
    session.add(_linha())
    await session.commit()

    session.add(_linha(ancora_em=ANCORA + timedelta(days=1)))
    await session.commit()

    todas = (await session.scalars(select(FollowUp))).all()
    assert len(todas) == 2


async def test_o_check_recusa_tentativa_zero(session) -> None:
    """1-based e contrato, nao convencao: `ja_disparada = 0` significa "nenhuma
    disparou", e uma linha numero 0 tornaria os dois indistinguiveis."""
    session.add(_linha(tentativa_numero=0))
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Rode o teste para confirmar que ele falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py -v`
Expected: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.followup.models'`.

Se em vez disso você vir centenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`, o banco ainda está subindo — espere e retente.

- [ ] **Step 3: Escreva a migration**

Confirme que `0014` é a head (`ls alembic/versions/`) e crie `alembic/versions/0015_cadencia_de_followup.py`:

```python
"""a trilha append-only dos follow-ups disparados

TEC-183, RN-13.1 e RN-13.4. Uma linha por tentativa que venceu e foi
registrada. Nao ha linha PENDENTE: a cadencia e derivada da ancora a cada
varredura, e o SRS descrevia um agendamento persistido -- ver a emenda a
RN-13.4.

**`ancora_em` e a coluna que torna a trilha legivel.** Ela guarda a ultima
fala do lead que gerou este disparo, entao "ate que tentativa a cadencia ja
foi desde que o lead falou pela ultima vez" e um MAX filtrado por igualdade
nela. Quando o lead responde, a ancora muda e a regua recomeca sozinha -- o
reinicio da RN-13.4 fica auditavel, com as duas series lado a lado, em vez de
implicito.

**`temperatura` e redundante com `lead_qualification` de proposito.** Ela
explica POR QUE foram N tentativas, e a coluna viva ja tera mudado quando
alguem for ler a trilha. Mesmo raciocinio dos cinco fatores em
`lead_score_audit`.

**O UNIQUE e a defesa contra varredura concorrente.** Duas passagens veriam o
mesmo candidato devido e ambas inseririam; nao da para usar FOR UPDATE SKIP
LOCKED sobre a agregacao que produz os candidatos, entao a exclusao mora na
restricao.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0010 e da
0012: a retencao da trilha nao pode ser encurtada por cascata da limpeza de
outra tabela.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("tentativa_numero", sa.SmallInteger(), nullable=False),
        sa.Column("temperatura", sa.String(8), nullable=False),
        sa.Column("ancora_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("devido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint("tentativa_numero > 0", name="ck_followups_tentativa"),
        sa.UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_followups_tentativa_por_ancora",
        ),
    )
    op.create_index(
        "ix_followups_lead",
        "followups",
        ["channel", "conversation_key", "ancora_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_followups_lead", table_name="followups")
    op.drop_table("followups")
```

**Sobre `clock_timestamp()` e não `now()`:** é a mesma razão da `0012` e da `0014` — `now()` é `transaction_timestamp()`, congelado no primeiro statement; a varredura insere várias linhas numa transação e todas sairiam com o mesmo carimbo.

- [ ] **Step 4: Escreva o modelo**

Crie `src/mobia/domain/followup/models.py`:

```python
"""A trilha dos follow-ups que a cadencia disparou.

TEC-183. Append-only: uma linha por tentativa vencida e registrada. Nao ha
estado PENDENTE nem CANCELADO -- a cadencia e derivada, e o que nao aconteceu
nao tem linha. Ver a emenda a RN-13.4 no SRS.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class FollowUp(Base):
    __tablename__ = "followups"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # 1-based. Zero seria indistinguivel de "nenhuma disparou", que e o que a
    # ausencia de linha ja significa -- por isso o CHECK.
    tentativa_numero: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # A temperatura NO MOMENTO do disparo, e nao a de agora. Redundante com
    # `lead_qualification` de proposito: e ela que explica por que foram N
    # tentativas, e a coluna viva ja tera mudado quando alguem ler a trilha.
    temperatura: Mapped[str] = mapped_column(String(8), nullable=False)

    # A ultima fala do lead que gerou este disparo -- o `created_at` daquela
    # mensagem, exato e nao aproximado. E contra a igualdade nesta coluna que
    # se conta ate onde a cadencia ja foi; quando o lead responde, a ancora
    # muda e a contagem zera sozinha.
    ancora_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # `ancora_em + CADENCIA[temperatura][n-1]`. Calculado, nao agendado -- e
    # **nao** esta ajustado a janela de 9h-20h, ao contrario do que o modelo de
    # dados do SRS diz sobre `agendado_para`. Isso e a TEC-185.
    devido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint("tentativa_numero > 0", name="ck_followups_tentativa"),
        # Duas varreduras concorrentes veriam o mesmo candidato devido e ambas
        # inseririam. Nao da para usar FOR UPDATE SKIP LOCKED sobre a agregacao
        # que produz os candidatos, entao a exclusao mora aqui.
        UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_followups_tentativa_por_ancora",
        ),
        Index("ix_followups_lead", "channel", "conversation_key", "ancora_em"),
    )
```

- [ ] **Step 5: Aplique a migration**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: `Running upgrade 0014 -> 0015`. `ConnectionResetError` aqui é o banco ainda subindo — espere e retente.

- [ ] **Step 6: Rode os testes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py tests/integration/test_migrations.py -v`
Expected: PASS nos quatro novos e em `test_migrations.py`.

- [ ] **Step 7: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos. `alembic` está no escopo do ruff — a migration nova é checada e formatada.

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/0015_cadencia_de_followup.py src/mobia/domain/followup/models.py tests/integration/test_followups_model.py
git commit -m "feat(TEC-183): a trilha de followup ganha tabela, e o banco recusa tentativa repetida"
```

---

### Task 3: A consulta de candidatos e o registro do disparo

**Files:**
- Create: `src/mobia/domain/followup/repositorio.py`
- Test: `tests/integration/test_followups_model.py` (acrescenta)

**Interfaces:**
- Consumes: `CADENCIA`/`INTERVALO_MINIMO` da Task 1, `FollowUp` da Task 2, `Temperatura` de `mobia.domain.context.temperatura`.
- Produces:
  - `@dataclass(frozen=True) class Candidato` com `channel: str`, `conversation_key: str`, `temperatura: Temperatura`, `ancora_em: datetime`, `ja_disparada: int`.
  - `async def candidatos_a_followup(session, *, agora: datetime, limite: int = 500) -> list[Candidato]`
  - `async def registrar_followup(session, *, candidato: Candidato, tentativa: int, devido_em: datetime) -> FollowUp | None`
  A Task 4 chama os três.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente a `tests/integration/test_followups_model.py`. Precisa dos imports novos no topo do arquivo:

```python
from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.repositorio import (
    candidatos_a_followup,
    registrar_followup,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt
```

E os testes:

```python
AGORA = ANCORA + timedelta(days=30)


async def _qualificacao(session, *, temperatura: str | None = "QUENTE") -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    await session.commit()


async def _fala_do_lead(session, *, quando, bloqueada: bool = False) -> None:
    """Uma fala de ENTRADA. `bloqueada` marca o que a moderacao recusou.

    Copia do helper de `test_auditoria_score.py`, com `created_at` explicito
    porque a ancora deste desenho e exatamente esse valor. As quatro colunas de
    identificacao do provedor nao sao decorativas: a tabela as exige.
    """
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=quando,
            bloqueada_em=quando if bloqueada else None,
        )
    )
    await session.commit()


async def test_o_candidato_traz_a_ancora_e_zero_disparos(session) -> None:
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert len(candidatos) == 1
    assert candidatos[0].conversation_key == CONVERSA
    assert candidatos[0].temperatura is Temperatura.QUENTE
    assert candidatos[0].ancora_em == ANCORA
    assert candidatos[0].ja_disparada == 0


async def test_lead_sem_temperatura_nao_e_candidato(session) -> None:
    """A D3: `NULL` e "linha anterior a TEC-151" ou "lead que nunca disse nada
    qualificavel". A RN-13.1 so prescreve cadencia para as tres temperaturas."""
    await _qualificacao(session, temperatura=None)
    await _fala_do_lead(session, quando=ANCORA)

    assert await candidatos_a_followup(session, agora=AGORA) == []


async def test_lead_que_falou_ha_pouco_nao_e_candidato(session) -> None:
    """O corte por `INTERVALO_MINIMO`: nada abaixo de 2h pode estar devido em
    temperatura nenhuma."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=AGORA - timedelta(hours=1))

    assert await candidatos_a_followup(session, agora=AGORA) == []


async def test_lead_sem_linha_de_qualificacao_nao_e_candidato(session) -> None:
    """Sem linha nao ha temperatura, e sem temperatura nao ha regua."""
    await _fala_do_lead(session, quando=ANCORA)

    assert await candidatos_a_followup(session, agora=AGORA) == []


async def test_a_ancora_ignora_a_fala_bloqueada_pela_moderacao(session) -> None:
    """Mesma definicao de fala do lead que `contar_mensagens_do_lead` fixou:
    `direction = INBOUND` e `bloqueada_em IS NULL`. Um turno que o resto do
    produto trata como nao-dito nao pode adiar o follow-up."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    await _fala_do_lead(session, quando=ANCORA + timedelta(days=1), bloqueada=True)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ancora_em == ANCORA


async def test_ja_disparada_e_o_maximo_sob_a_ancora(session) -> None:
    """MAX e nao COUNT -- ver a docstring de `tentativa_devida`."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    session.add(_linha(tentativa_numero=3))
    await session.commit()

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ja_disparada == 3


async def test_a_resposta_do_lead_zera_a_regua(session) -> None:
    """O reinicio da RN-13.4, e o teste que morre se `ja_disparada` olhar a
    vida inteira em vez de por ancora."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    session.add(_linha(tentativa_numero=4))
    await session.commit()

    nova_ancora = ANCORA + timedelta(days=5)
    await _fala_do_lead(session, quando=nova_ancora)

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert candidatos[0].ancora_em == nova_ancora
    assert candidatos[0].ja_disparada == 0


async def test_registrar_devolve_none_na_corrida(session) -> None:
    """A segunda varredura nao levanta: o `ON CONFLICT DO NOTHING` absorve, e o
    `None` diz ao chamador que outra passagem chegou primeiro."""
    await _qualificacao(session)
    await _fala_do_lead(session, quando=ANCORA)
    candidato = (await candidatos_a_followup(session, agora=AGORA))[0]

    primeira = await registrar_followup(
        session, candidato=candidato, tentativa=1, devido_em=ANCORA + timedelta(hours=2)
    )
    await session.commit()
    segunda = await registrar_followup(
        session, candidato=candidato, tentativa=1, devido_em=ANCORA + timedelta(hours=2)
    )
    await session.commit()

    assert primeira is not None
    assert segunda is None
```

- [ ] **Step 2: Rode os testes para confirmar que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py -v`
Expected: os quatro da Task 2 passam; os oito novos falham com `ImportError: cannot import name 'candidatos_a_followup'`.

- [ ] **Step 3: Escreva a implementação**

Crie `src/mobia/domain/followup/repositorio.py`:

```python
"""Quem esta devido de follow-up, e o registro de que disparou.

TEC-183. A cadencia nao e agendada: nao ha linha PENDENTE, e a pergunta "quem
esta devido agora?" e refeita a cada varredura. Ver a D1 do desenho.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import INTERVALO_MINIMO
from mobia.domain.followup.models import FollowUp


@dataclass(frozen=True)
class Candidato:
    """Um lead que calou tempo suficiente para valer a pena consultar a regua.

    `ja_disparada` e o MAIOR numero de tentativa gravado sob `ancora_em`, ou
    zero quando nao ha nenhuma -- e nao uma contagem. A razao esta na docstring
    de `tentativa_devida`, e o resumo e que um lead muito atrasado recebe uma
    tentativa so, a ultima, e com contagem a regua refaria as anteriores.
    """

    channel: str
    conversation_key: str
    temperatura: Temperatura
    ancora_em: datetime
    ja_disparada: int


# A ancora usa a MESMA definicao de fala do lead que `contar_mensagens_do_lead`
# fixou -- `direction = 'INBOUND'` e `bloqueada_em IS NULL`. Nao e uma segunda
# leitura desse fato: e a mesma regra, e a docstring daquela funcao existe
# precisamente para que a proxima card nao escreva uma terceira.
#
# O `HAVING` e o corte barato: nada abaixo de `INTERVALO_MINIMO` pode estar
# devido em temperatura nenhuma, entao o lead sai antes de qualquer outro
# trabalho. `temperatura IS NOT NULL` e o outro corte (D3).
#
# O subselect de `ja_disparada` roda por linha ja filtrada, e o indice
# `ix_followups_lead` o atende.
#
# **Esta consulta agrega `messages` a cada passagem.** E varredura, e o
# `ix_messages_timeline` serve "a ultima mensagem de UMA conversa", nao "todas
# as conversas cuja ultima fala e antiga". Aceitavel a cada 5 minutos no volume
# de MVP; a saida, quando doer, e uma coluna de ancora denormalizada em
# `lead_qualification` -- que o turno ja tem sob lock. Lacuna declarada.
_SELECIONAR_CANDIDATOS = text(
    """
    WITH ultima_fala AS (
        SELECT channel, conversation_key, MAX(created_at) AS ancora
          FROM messages
         WHERE direction = 'INBOUND'
           AND bloqueada_em IS NULL
         GROUP BY channel, conversation_key
        HAVING MAX(created_at) <= :corte
    )
    SELECT lq.channel,
           lq.conversation_key,
           lq.temperatura,
           u.ancora,
           COALESCE(
               (SELECT MAX(f.tentativa_numero)
                  FROM followups f
                 WHERE f.channel = lq.channel
                   AND f.conversation_key = lq.conversation_key
                   AND f.ancora_em = u.ancora),
               0
           ) AS ja_disparada
      FROM lead_qualification lq
      JOIN ultima_fala u
        ON u.channel = lq.channel
       AND u.conversation_key = lq.conversation_key
     WHERE lq.temperatura IS NOT NULL
     ORDER BY u.ancora
     LIMIT :limite
    """
)


async def candidatos_a_followup(
    session: AsyncSession, *, agora: datetime, limite: int = 500
) -> list[Candidato]:
    """Os leads que calaram tempo bastante para a regua valer a pena.

    Ser candidato NAO significa estar devido: o corte aqui e o menor intervalo
    que existe em qualquer temperatura, e quem decide de fato e
    `tentativa_devida`. Separar as duas coisas mantem a regra no modulo puro,
    onde da para testa-la sem banco.

    `agora` entra por parametro e nao sai de `datetime.now()` aqui dentro: sem
    isso nenhum teste consegue posicionar o relogio, e a cadencia inteira e
    sobre tempo.

    `ORDER BY u.ancora` faz o `LIMIT` cortar os mais recentes quando ha mais
    candidatos que o teto -- ou seja, quem esta esperando ha mais tempo passa
    primeiro. A proxima varredura pega o resto cinco minutos depois.
    """
    resultado = await session.execute(
        _SELECIONAR_CANDIDATOS,
        {"corte": agora - INTERVALO_MINIMO, "limite": limite},
    )
    return [
        Candidato(
            channel=linha.channel,
            conversation_key=linha.conversation_key,
            temperatura=Temperatura(linha.temperatura),
            ancora_em=linha.ancora,
            ja_disparada=linha.ja_disparada,
        )
        for linha in resultado
    ]


async def registrar_followup(
    session: AsyncSession, *, candidato: Candidato, tentativa: int, devido_em: datetime
) -> FollowUp | None:
    """Grava a tentativa. Devolve `None` quando outra varredura chegou primeiro.

    `ON CONFLICT DO NOTHING` e nao `try/except IntegrityError`: a excecao
    envenenaria a transacao inteira, e a varredura processa varios candidatos
    numa so -- um conflito no terceiro derrubaria os dois primeiros junto.

    Nao commita: a sessao e emprestada, e quem chama e dono da fronteira da
    transacao, como em `gravar_estado` e `registrar_recalculo`.
    """
    statement = (
        pg_insert(FollowUp)
        .values(
            id=uuid.uuid4(),
            channel=candidato.channel,
            conversation_key=candidato.conversation_key,
            tentativa_numero=tentativa,
            temperatura=candidato.temperatura.value,
            ancora_em=candidato.ancora_em,
            devido_em=devido_em,
        )
        .on_conflict_do_nothing(constraint="uq_followups_tentativa_por_ancora")
        .returning(FollowUp)
    )
    return (await session.scalars(statement)).first()
```

- [ ] **Step 4: Rode os testes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_followups_model.py -v`
Expected: PASS nos doze.

Se `test_a_ancora_ignora_a_fala_bloqueada_pela_moderacao` falhar, confira se o helper está passando `bloqueada_em` — é a coluna que `contar_mensagens_do_lead` filtra, e o nome é esse.

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/followup/repositorio.py tests/integration/test_followups_model.py
git commit -m "feat(TEC-183): o banco passa a dizer quem calou tempo bastante para a regua"
```

---

### Task 4: O job de varredura

**Files:**
- Create: `src/mobia/workers/jobs/sweep_followups.py`
- Modify: `src/mobia/workers/main.py` (import, `functions`, `cron_jobs`)
- Test: `tests/integration/test_sweep_followups.py`

**Interfaces:**
- Consumes: `Candidato`, `candidatos_a_followup`, `registrar_followup` da Task 3; `CADENCIA`, `tentativa_devida` da Task 1; `esta_em_optout(session, *, channel, conversation_key) -> bool` de `mobia.domain.optout.repositorio` (já no repo).
- Produces: `async def sweep_followups(ctx: dict[str, Any], limite: int = 500) -> int`, devolvendo quantas tentativas registrou. Registrado no worker.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_sweep_followups.py`:

```python
"""A varredura da cadencia, ponta a ponta.

TEC-183. Integracao: a decisao mora na funcao pura, mas quem entra na
varredura e o que ela grava so da para verificar contra o banco.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.followup.models import FollowUp
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_followups import sweep_followups

CANAL = "whatsapp"
CONVERSA = "5511944443333"


async def _lead(session, *, temperatura: str = "QUENTE", calado_ha: timedelta) -> None:
    """Um lead com temperatura e uma fala de entrada com a idade pedida."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura=temperatura,
        )
    )
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=datetime.now(UTC) - calado_ha,
        )
    )
    await session.commit()


def _ctx() -> dict:
    return {"session_factory": get_sessionmaker()}


async def test_o_quente_calado_ha_duas_horas_recebe_a_primeira(session, caplog) -> None:
    """A CA-13.1, ponta a ponta."""
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5))

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx())

    assert gravadas == 1
    linhas = (await session.scalars(select(FollowUp))).all()
    assert len(linhas) == 1
    assert linhas[0].tentativa_numero == 1
    assert linhas[0].temperatura == "QUENTE"
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 1


async def test_o_lead_com_optout_nao_recebe_nada(session, caplog) -> None:
    """O criterio de aceite do opt-out. `esta_em_optout` e a unica
    implementacao desse fato, e a varredura a consulta em vez de reescrever a
    regra em SQL."""
    await _lead(session, calado_ha=timedelta(days=30))
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            evento=EVENTO_OPT_OUT,
        )
    )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx())

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0


async def test_o_lead_muito_atrasado_recebe_uma_tentativa_so(session) -> None:
    """A guarda contra a rajada: dez dias de silencio dao as quatro do QUENTE
    vencidas, e a varredura grava so a quarta. Rodar de novo nao grava mais
    nada."""
    await _lead(session, calado_ha=timedelta(days=10))

    assert await sweep_followups(_ctx()) == 1
    assert await sweep_followups(_ctx()) == 0

    linhas = (await session.scalars(select(FollowUp))).all()
    assert [linha.tentativa_numero for linha in linhas] == [4]


async def test_a_varredura_e_idempotente_na_mesma_passagem(session) -> None:
    """Duas varreduras concorrentes veriam o mesmo candidato. O UNIQUE absorve,
    e o job nao levanta -- devolve zero na segunda."""
    await _lead(session, calado_ha=timedelta(hours=3))

    assert await sweep_followups(_ctx()) == 1
    assert await sweep_followups(_ctx()) == 0


async def test_o_lead_que_falou_ha_pouco_nao_entra(session) -> None:
    await _lead(session, calado_ha=timedelta(minutes=30))

    assert await sweep_followups(_ctx()) == 0


async def test_o_lead_sem_temperatura_nao_entra(session) -> None:
    """A D3, ponta a ponta."""
    await _lead(session, temperatura=None, calado_ha=timedelta(days=30))

    assert await sweep_followups(_ctx()) == 0
```

**Nota sobre a fixture `session` e a sessão do job:** o job abre a sua própria sessão por `session_factory`, então o que ele grava só aparece na sessão do teste depois de um `expire_all()` ou numa consulta nova. As asserções acima usam `select(...)` novo, que já vai ao banco — não use `session.get` sobre uma instância que o teste tenha adicionado.

- [ ] **Step 2: Rode os testes para confirmar que falham**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -v`
Expected: FAIL na coleta, `ModuleNotFoundError: No module named 'mobia.workers.jobs.sweep_followups'`.

- [ ] **Step 3: Escreva o job**

Crie `src/mobia/workers/jobs/sweep_followups.py`:

```python
"""A varredura da cadencia de reengajamento.

TEC-183, RN-13.1 e RN-13.4. Molde do `sweep_stalled`: um job `cron` que
consulta trabalho vencido e age. A diferenca esta no relogio -- ver o
comentario do registro em `workers/main.py`.

**Nada e enviado ao lead.** A card grava a tentativa e emite `followup.devido`;
o texto e a entrega sao da TEC-184, e a RN-13.2 proibe follow-up sem
informacao nova, entao um texto provisorio violaria a regra de frente. Lacuna
declarada no desenho.
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from mobia.domain.followup.cadencia import CADENCIA, tentativa_devida
from mobia.domain.followup.repositorio import candidatos_a_followup, registrar_followup
from mobia.domain.optout.repositorio import esta_em_optout

log = structlog.get_logger(__name__)


async def sweep_followups(ctx: dict[str, Any], limite: int = 500) -> int:
    """Registra as tentativas de follow-up que venceram. Devolve quantas.

    O opt-out e consultado por candidato, e nao juntado na consulta:
    `esta_em_optout` e a unica implementacao daquele fato, e escreve-lo uma
    segunda vez em SQL criaria duas fontes que divergem em silencio -- o
    defeito que a TEC-146 gastou uma card inteira consertando. O preco e uma
    consulta por candidato, e os candidatos sao poucos por construcao: so quem
    tem temperatura, calou ha mais de duas horas e ainda nao esgotou.

    **A conversa silenciada NAO e checada, e o criterio de aceite pede.** O
    estado nao existe -- e a TEC-179, e nada no produto o produz hoje. Quando
    ela existir, o predicado entra nesta mesma lista de guardas, ao lado do
    opt-out. Lacuna declarada.

    Um `registrar_followup` que devolve `None` significa que outra varredura
    chegou primeiro (o `ON CONFLICT DO NOTHING` absorveu). Nao e erro e nao
    entra na contagem.

    Tudo numa transacao so: a varredura nao tem efeito externo, entao nao ha o
    risco que faz o `sweep_stalled` soltar os locks antes do I/O de rede.
    """
    session_factory = ctx["session_factory"]
    agora = datetime.now(UTC)
    gravadas = 0

    async with session_factory() as session:
        candidatos = await candidatos_a_followup(session, agora=agora, limite=limite)

        for candidato in candidatos:
            if await esta_em_optout(
                session,
                channel=candidato.channel,
                conversation_key=candidato.conversation_key,
            ):
                continue

            tentativa = tentativa_devida(
                temperatura=candidato.temperatura,
                ultima_fala=candidato.ancora_em,
                ja_disparada=candidato.ja_disparada,
                agora=agora,
            )
            if tentativa is None:
                continue

            devido_em = candidato.ancora_em + CADENCIA[candidato.temperatura][tentativa - 1]
            linha = await registrar_followup(
                session, candidato=candidato, tentativa=tentativa, devido_em=devido_em
            )
            if linha is None:
                continue

            gravadas += 1
            # O texto do lead nao entra: a regra de PII que
            # `moderacao.entrada_bloqueada` respeita vale igual aqui.
            log.info(
                "followup.devido",
                channel=candidato.channel,
                tentativa=tentativa,
                temperatura=candidato.temperatura.value,
                ancora_em=candidato.ancora_em.isoformat(),
                devido_em=devido_em.isoformat(),
            )

        await session.commit()

    return gravadas
```

- [ ] **Step 4: Registre o job no worker**

Em `src/mobia/workers/main.py`:

1. Acrescente o import ao lado do `sweep_stalled`:

```python
from mobia.workers.jobs.sweep_followups import sweep_followups
```

2. Acrescente às duas listas de `WorkerSettings`:

```python
    functions = [func(process_message, keep_result=0), sweep_stalled, sweep_followups]
    cron_jobs = [
        cron(sweep_stalled, second={0, 30}, run_at_startup=False),
        # De 5 em 5 minutos, e nao de 30 em 30 segundos como o irmao: o menor
        # intervalo da RN-13.1 e de DUAS HORAS, entao precisao de segundos nao
        # compra nada e custa uma varredura que agrega `messages` a cada
        # passagem. O erro maximo de disparo fica em cinco minutos sobre uma
        # janela de duas horas.
        cron(
            sweep_followups,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
    ]
```

**`run_at_startup=False` como o irmão:** subir o worker não deve disparar uma varredura antes de o resto do contexto estar quente, e nada aqui é urgente ao segundo.

- [ ] **Step 5: Rode os testes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py tests/integration/test_followups_model.py -v`
Expected: PASS nos dezoito.

- [ ] **Step 6: Rode os testes do worker, que este passo pode quebrar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_worker_startup.py tests/integration/test_sweep_stalled.py -v`
Expected: PASS. `test_worker_startup.py` é quem verifica o registro de funções e cron do `WorkerSettings` — se ele reclamar de contagem, é porque asserta o conjunto de jobs e precisa incluir o novo.

- [ ] **Step 7: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 8: Commit**

```bash
git add src/mobia/workers/jobs/sweep_followups.py src/mobia/workers/main.py tests/integration/test_sweep_followups.py
git commit -m "feat(TEC-183): a cadencia passa a rodar sozinha de cinco em cinco minutos"
```

---

### Task 5: A emenda ao SRS

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (a tabela de emendas perto da linha 15; a RN-13.4, perto da linha 320)
- Modify: `docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md` (linha 3, o status)

**Interfaces:** nenhuma. Esta task não muda comportamento e não tem teste novo.

- [ ] **Step 1: Acrescente a linha à tabela de emendas**

No topo do SRS, depois da última linha da tabela:

```
> | E-01 | RN-13.4 | [TEC-183](https://eduardodurieuxlopes.atlassian.net/browse/TEC-183) | 03/09/2026 |
```

**A numeração é por regra, não global.** O documento já contém várias `E-01`, cada uma de uma regra diferente. A `RN-13.4` nunca foi emendada, então esta é `E-01`. Confira isso no arquivo antes de escrever, em vez de confiar nesta frase.

- [ ] **Step 2: Acrescente a emenda aninhada sob a RN-13.4**

Logo abaixo da RN-13.4, **sem reescrever o texto de 22/08/2026**, no mesmo formato das emendas vizinhas:

```
  - **Emenda E-01 (TEC-183, 03/09/2026):** não há cadência pendente a cancelar, porque não há agendamento persistido. A cadência é derivada da **âncora** — a última fala não bloqueada do lead — a cada varredura, e a resposta do lead move essa âncora, o que faz a régua recomeçar por aritmética. O efeito observável da regra é idêntico ao descrito: as tentativas restantes não acontecem, e o ciclo recomeça a partir do novo estado. O motivo da mudança de forma são as outras duas regras da mesma card, que um horário gravado no banco tornaria mentirosas: *"mudança de temperatura recalcula a cadência restante"* e *"os intervalos vêm de configuração e podem ser ajustados sem deploy"* — um `agendado_para` persistido congela o intervalo no instante do agendamento e fica imune às duas. **Consequência declarada:** a entidade `FollowUp` da seção 5 perde `PENDENTE` e `CANCELADO` do enum de status, e `agendado_para` passa a ser `devido_em`, calculado no momento do disparo e **não** ajustado à janela da RN-13.3 (isso é a TEC-185).
```

- [ ] **Step 3: Atualize o status do desenho**

Em `docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md`, linha 3:

```
**Status:** desenhado em 2026-09-03, implementado em 2026-09-03 na branch `feat/tec-183-cadencia-de-reengajamento`.
```

- [ ] **Step 4: Rode a suíte inteira**

Run: `./.venv/Scripts/python.exe -u -m pytest -v`

**Rode em PRIMEIRO PLANO, com timeout de 600000 ms, e não encerre o turno enquanto ela estiver pendente.** Leva cerca de 12 minutos e passavam 1078 testes antes desta card; com os 33 deste plano, espere 1111. **Lentidão aqui parece exatamente travamento — não é.** Se a chamada for para segundo plano por exceder o timeout, bloqueie na saída dela no mesmo turno com `until grep -qE "passed|failed|error" <arquivo>; do sleep 20; done; tail -40 <arquivo>`.

`test_montagem.py`, `test_sweep_stalled.py` e `test_dedup_por_message_id.py` flakeiam sob carga e passam isolados — rode o arquivo sozinho antes de culpar sua mudança, e relate qualquer re-execução.

- [ ] **Step 5: Rode os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```
Expected: os três limpos.

- [ ] **Step 6: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-03-tec-183-cadencia-de-reengajamento-design.md
git commit -m "docs(TEC-183): a RN-13.4 passa a dizer que o cancelamento e a ancora se movendo"
```

---

## Cobertura da spec

| item da spec | task |
|---|---|
| D1 — cadência derivada, sem linha `PENDENTE` | 3 (a consulta), 4 (o job) |
| D2 — deslocamentos desde a âncora, maior vencida, `MAX` e não `COUNT` | 1 |
| D2 — constantes de módulo, keyword-only, `INTERVALO_MINIMO` derivado | 1 |
| D3 — lead sem temperatura fora da cadência | 3 (`WHERE temperatura IS NOT NULL`), testado em 3 e 4 |
| D4 — a tabela, `ancora_em`, `UNIQUE`, `CHECK`, colunas do SRS que ficam de fora | 2 |
| D5 — cron de 5 em 5 minutos, os dois cortes, opt-out por candidato, o evento | 4 |
| Fluxo — a ordem das guardas e a corrida absorvida pelo `UNIQUE` | 4 |
| Testes — basenames distintos, os cenários da card, os quatro extras | 1, 3, 4 |
| Emenda `E-01` à RN-13.4 + tabela | 5 |
| Lacuna 1 — nada é enviado | 4 (docstring do módulo e do job) |
| Lacuna 2 — conversa silenciada não checada | 4 (docstring de `sweep_followups`) |
| Lacuna 3 — `devido_em` não respeita a janela | 2 (comentário da coluna), 5 (emenda) |
| Lacunas 4 e 5 — teto anti-spam, `DORMENTE`, configuração viva | 1 (docstring do módulo), spec |
| Lacuna 6 — a varredura agrega `messages` | 3 (comentário da consulta) |
| Lacuna 8 — fala bloqueada não é âncora | 3 (comentário da consulta e teste próprio) |

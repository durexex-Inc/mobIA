# TEC-138 — Encerrar conversa após três mensagens fora de escopo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Três mensagens `FORA_DE_ESCOPO` seguidas encerram a conversa com uma despedida fixa; o agente fica mudo por 30 dias sem pagar chamada nenhuma; qualquer mensagem dentro do escopo zera o contador antes disso.

**Architecture:** Um contador em `conversation_intent` — a única tabela escrita em todo turno — sobe ou zera dentro do `ON CONFLICT DO UPDATE` que já existe, e o `RETURNING` devolve o valor novo. Ao bater três, o turno grava `status = ENCERRADA` numa entidade nova `conversas`, **zera o contador na mesma transação**, e entrega a despedida em lugar da prosa. Uma guarda no topo do turno, depois das duas de silêncio que já existem e antes da chamada paga, devolve `"fora_de_escopo"` enquanto a janela de 30 dias valer.

**Tech Stack:** Python 3.13, SQLAlchemy async, Postgres, Alembic, pytest. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-16-tec-138-encerrar-fora-de-escopo-design.md`

## O detalhe que faz a máquina de estado fechar

**O encerramento zera o contador**, e é isso que dispensa qualquer escrita na reabertura. Sem isso, um lead que volta depois de 30 dias com outra mensagem fora de escopo iria de 3 para 4 e seria encerrado no primeiro turno, sem direito às três tentativas que a regra lhe dá.

Com o zero no encerramento, a sequência fecha sozinha: durante a janela a guarda devolve antes de `gravar_intencao`, então o contador não se mexe; passada a janela, o status volta para `ATIVA` e a contagem recomeça do zero que já está lá.

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado, que segue o valor.
- **Texto que o lead recebe: português COM acento** (TEC-267). Vale para a despedida.
- **Prosa em `docs/`: COM acento.**
- **Nenhum texto pode afirmar que alguém foi avisado.** `notificacao/envio.py` proíbe nominalmente e termina com *"Nao reintroduza a promessa"*. Três cards já tropeçaram nisso.
- **O log do encerramento não carrega o texto das mensagens** (D7), pela mesma razão que a prosa bloqueada da TEC-161 não entra no log.
- **A guarda nova perde para opt-out e para o silêncio de atendimento humano**, e ganha de tudo que vem depois. Ver a D5.
- **`TETO_DE_FORA_DE_ESCOPO` é escrito uma vez só**, no molde de `TETO_DE_PERGUNTAS`, cujo comentário diz "O unico lugar em que este numero esta escrito."
- **30 dias vem de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`** (`domain/agente/identificacao.py`), não de um literal novo. É a D1.
- **Mensagem de commit:** `tipo(TEC-138): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Os três gates, com este escopo exato, antes de qualquer commit:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Testes:** `tests/unit/` não precisa de Docker; `tests/integration/` exige `docker compose` de pé. Rode o arquivo inteiro, sem `-k`.

---

## File Structure

| arquivo | responsabilidade |
| --- | --- |
| `src/mobia/domain/conversa/__init__.py` (cria) | pacote novo |
| `src/mobia/domain/conversa/models.py` (cria) | a entidade `Conversa` e os vocabulários de status e motivo |
| `src/mobia/domain/conversa/regras.py` (cria) | `TETO_DE_FORA_DE_ESCOPO` e `deve_encerrar`, puros |
| `src/mobia/domain/conversa/repositorio.py` (cria) | `encerrar_conversa`, `esta_encerrada`, `reabrir_conversa` |
| `src/mobia/domain/agente/models.py` (modifica) | a coluna `fora_de_escopo_seguidas` |
| `src/mobia/domain/agente/repositorio.py` (modifica) | `gravar_intencao` conta e devolve |
| `src/mobia/domain/agente/turno.py` (modifica) | a despedida, a guarda, a substituição, o log |
| `alembic/versions/0036_conversa_e_contador_fora_de_escopo.py` (cria) | coluna e tabela |
| `tests/unit/test_regras_de_escopo.py` (cria) | a regra pura |
| `tests/integration/test_conversa_encerrada.py` (cria) | contador, encerramento, guarda e reabertura |

---

### Task 1: O schema

**Files:**
- Create: `src/mobia/domain/conversa/__init__.py`, `src/mobia/domain/conversa/models.py`
- Modify: `src/mobia/domain/agente/models.py` (a coluna, depois de `desambiguado_em`)
- Create: `alembic/versions/0036_conversa_e_contador_fora_de_escopo.py`
- Modify: `tests/conftest.py` (a tupla `TABELAS`)

**Interfaces:**
- Consumes: nada
- Produces: `Conversa`, `STATUS_ATIVA`, `STATUS_ENCERRADA`, `MOTIVO_FORA_DE_ESCOPO`; a coluna `ConversationIntent.fora_de_escopo_seguidas`

- [ ] **Step 1: O modelo da conversa**

Crie `src/mobia/domain/conversa/models.py`:

```python
"""O ciclo de vida da conversa. TEC-138, RN-03.5 e RN-02.3.

**Esta tabela e a entidade que este sistema nao tinha.** Ate a TEC-138 a
conversa era o par `(channel, conversation_key)` espalhado por oito tabelas --
`atendimento/models.py` diz isso por extenso -- e o encerramento era uma regra
do SRS sem implementacao, reservada para a TEC-130. A TEC-138 chegou antes e
precisou do status, entao a entidade nasce aqui.

**Consequencia para quem pegar a TEC-130:** ela ESTENDE isto, nao cria.
Encerrar por inatividade e acrescentar um motivo ao vocabulario abaixo e um
escritor novo; nao e uma segunda tabela nem uma segunda nocao de encerrado. A
Emenda da RN-02.3 registra isso no SRS.

`motivo_do_encerramento` e vocabulario e nao booleano justamente para essa
extensao: a regra da card pede que o motivo seja "proprio, separado do
encerramento por inatividade", e uma booleana `encerrada` obrigaria a TEC-130
a inventar onde guardar o dela.

Uma linha por conversa, com UPDATE -- e nao append-only como `optout_events`.
O historico de encerramentos nao existe por esta card, e a lacuna esta
declarada no desenho: quem precisar da serie acrescenta a tabela de eventos.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base

STATUS_ATIVA = "ATIVA"
STATUS_ENCERRADA = "ENCERRADA"

# Unico motivo por enquanto. A TEC-130 acrescenta INATIVIDADE aqui.
MOTIVO_FORA_DE_ESCOPO = "FORA_DE_ESCOPO"


class Conversa(Base):
    __tablename__ = "conversas"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_ATIVA)

    # Os dois andam juntos e sao nulos juntos: `status = ATIVA` significa
    # nenhum dos dois preenchido. Nao ha booleana `encerrada` ao lado, pela
    # razao que `atendimento_humano` ja escreve para si -- uma segunda
    # representacao do mesmo fato e duas coisas que podem divergir.
    motivo_do_encerramento: Mapped[str | None] = mapped_column(String(16), nullable=True)
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`__init__.py` vazio, no molde dos outros pacotes de `domain/`.

- [ ] **Step 2: A coluna do contador**

Em `src/mobia/domain/agente/models.py`, dentro de `ConversationIntent`, depois de `desambiguado_em`:

```python
    # Quantas mensagens FORA_DE_ESCOPO seguidas. RN-03.5, TEC-138.
    #
    # Mora aqui, e nao em `lead_qualification`, por um motivo mecanico: aquela
    # tabela NAO ganha linha em turno fora de escopo -- `campos_a_gravar`
    # devolve {} e `gravar_estado` retorna cedo com "Deliberadamente NAO cria
    # linha" --, entao um lead cujo historico inteiro e fora de escopo nunca
    # teria onde ser contado. Esta tabela e a unica escrita em TODO turno.
    #
    # Sobe ou zera dentro do proprio `ON CONFLICT DO UPDATE` de
    # `gravar_intencao`: o reset e o `ELSE 0` do mesmo CASE, e por isso o
    # "voltar ao assunto zera" da card nao tem codigo proprio.
    #
    # **O encerramento zera este contador.** Sem isso o lead que volta depois
    # dos 30 dias iria de 3 para 4 e seria encerrado na primeira mensagem, sem
    # as tres tentativas que a regra lhe da.
    fora_de_escopo_seguidas: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
```

**Confira o import de `SmallInteger`** no topo do arquivo; `lead_qualification` já o usa para `perguntas_feitas`, mas este é outro módulo.

- [ ] **Step 3: A migration**

Crie `alembic/versions/0036_conversa_e_contador_fora_de_escopo.py`. Uma migration só para as duas mudanças, porque são o schema de uma card só e sobem juntas.

```python
"""a conversa ganha status, e a intencao ganha contador de fora de escopo

TEC-138, RN-03.5 e RN-02.3.

`conversas` e a entidade que a TEC-130 ia criar e que esta card precisou
antes. A TEC-130 estende: acrescenta motivo e escritor, nao tabela.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0010 e da
0012: a retencao desta tabela nao pode ser encurtada por cascata da limpeza de
outra.

O `server_default='0'` do contador existe para as linhas que ja estao la: a
coluna e NOT NULL e `conversation_intent` tem linha para toda conversa ja
atendida. Sem o default o ALTER falha.

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_intent",
        sa.Column("fora_de_escopo_seguidas", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "conversas",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ATIVA"),
        sa.Column("motivo_do_encerramento", sa.String(16), nullable=True),
        sa.Column("encerrada_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("conversas")
    op.drop_column("conversation_intent", "fora_de_escopo_seguidas")
```

- [ ] **Step 4: A tabela nova entra no TRUNCATE dos testes**

Em `tests/conftest.py`, acrescente `"conversas"` à tupla `TABELAS`, com uma linha de comentário dizendo por quê — sem o truncate, uma conversa encerrada por um teste chega encerrada no próximo e a guarda do topo cala o turno antes de qualquer asserta.

- [ ] **Step 5: Rodar a migration nos dois sentidos**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: os três sem erro. Se o primeiro reprovar com `ConnectionResetError [WinError 64]` na negociação SSL, espere e retente — é conhecido neste repo e não é defeito de código.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/integration/test_repositorio_intencao.py --tb=short
git add src/mobia/domain/conversa/ src/mobia/domain/agente/models.py alembic/versions/0036_conversa_e_contador_fora_de_escopo.py tests/conftest.py
git commit -m "feat(TEC-138): a conversa tem status e a intencao tem contador de fora de escopo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A regra pura e o contador

**Files:**
- Create: `src/mobia/domain/conversa/regras.py`
- Modify: `src/mobia/domain/agente/repositorio.py` (`gravar_intencao`)
- Test: `tests/unit/test_regras_de_escopo.py` (cria); acrescenta a `tests/integration/test_repositorio_intencao.py`

**Interfaces:**
- Consumes: a coluna da Task 1
- Produces: `TETO_DE_FORA_DE_ESCOPO`, `deve_encerrar(seguidas: int) -> bool`; `gravar_intencao` passa a devolver `int`

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_regras_de_escopo.py`:

```python
"""Quando tres mensagens fora de escopo encerram a conversa. TEC-138.

Puro: nao toca banco nem modelo.
"""

import pytest

from mobia.domain.conversa.regras import TETO_DE_FORA_DE_ESCOPO, deve_encerrar


@pytest.mark.parametrize("seguidas", [0, 1, 2])
def test_abaixo_do_teto_a_conversa_segue(seguidas: int) -> None:
    """As duas primeiras sao redirecionadas, nao encerradas.

    O zero entra porque e o estado de toda conversa que nunca teve mensagem
    fora de escopo, e a guarda roda em todo turno.
    """
    assert deve_encerrar(seguidas) is False


def test_no_teto_a_conversa_encerra() -> None:
    """A TERCEIRA encerra -- a card conta mensagens, nao turnos depois delas."""
    assert deve_encerrar(TETO_DE_FORA_DE_ESCOPO) is True


def test_acima_do_teto_continua_encerrando() -> None:
    """Defensivo, e o caso existe: um turno concorrente pode ter passado do
    teto entre a contagem deste e a decisao dele. Encerrar de novo e
    idempotente; parar de encerrar seria perder o caso.
    """
    assert deve_encerrar(TETO_DE_FORA_DE_ESCOPO + 1) is True


def test_o_teto_e_tres() -> None:
    """A card diz tres, e este e o unico lugar em que o numero esta escrito."""
    assert TETO_DE_FORA_DE_ESCOPO == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_regras_de_escopo.py --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.conversa.regras'`

- [ ] **Step 3: Write minimal implementation**

Crie `src/mobia/domain/conversa/regras.py`:

```python
"""A regra de quando a conversa fora de escopo acaba. RN-03.5, TEC-138.

Pura de proposito, no molde de `context/qualificacao.py`: sem I/O, sem banco,
sem chamada ao modelo. Quem grava e o repositorio; aqui so se decide.
"""

# RN-03.5. O unico lugar em que este numero esta escrito, como o
# TETO_DE_PERGUNTAS da RN-05.5.
TETO_DE_FORA_DE_ESCOPO = 3


def deve_encerrar(seguidas: int) -> bool:
    """Esta contagem de mensagens fora de escopo seguidas encerra a conversa?

    `>=` e nao `==`: dois turnos concorrentes da mesma conversa podem passar do
    teto entre a contagem de um e a decisao do outro, e encerrar uma conversa
    ja encerrada e idempotente. Parar de encerrar acima do teto perderia o
    caso em silencio.
    """
    return seguidas >= TETO_DE_FORA_DE_ESCOPO
```

- [ ] **Step 4: O contador em `gravar_intencao`**

O `set_` de hoje é `{chave: statement.excluded[chave] for chave in ("intencao", "confianca", "modelo", "updated_at")}`, com `desambiguado_em` acrescentado condicionalmente. Acrescente a contagem e faça a função devolver o valor novo:

```python
    # RN-03.5, TEC-138. Sobe quando a intencao deste turno e FORA_DE_ESCOPO e
    # ZERA em qualquer outra -- o "voltar ao assunto zera o contador" da card e
    # este `ELSE`, e por isso nao tem codigo proprio em lugar nenhum.
    #
    # A aritmetica mora no SQL pela razao que `contar_perguntas` e a uniao de
    # `perguntados_sem_resposta` ja registram: ler o valor, somar em Python e
    # gravar abre a janela em que dois turnos concorrentes da mesma conversa
    # leem o mesmo numero e o mais lento sobrescreve o mais rapido.
    #
    # `Intencao` e StrEnum e esta funcao grava `str(intencao)`, entao a coluna
    # guarda o literal e a comparacao com `excluded` e direta.
    atualizacoes["fora_de_escopo_seguidas"] = case(
        (
            statement.excluded.intencao == Intencao.FORA_DE_ESCOPO.value,
            ConversationIntent.fora_de_escopo_seguidas + 1,
        ),
        else_=0,
    )
```

E o retorno, no mesmo statement:

```python
    resultado = await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_=atualizacoes,
        ).returning(ConversationIntent.fora_de_escopo_seguidas)
    )
    return resultado.scalar_one()
```

A assinatura passa de `-> None` para `-> int`, e a docstring ganha uma frase dizendo o que o número é e por que ele volta daqui: **é o valor pós-incremento, e devolvê-lo pelo `RETURNING` evita a segunda consulta que teria de reler a linha que este statement acabou de escrever.**

**São dois sítios de chamada** (`turno.py` e `tests/integration/test_repositorio_intencao.py`). O de `turno.py` passa a guardar o retorno; a Task 4 o usa.

- [ ] **Step 5: Run test to verify it passes**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_regras_de_escopo.py --tb=short
```
Expected: 6 passed

- [ ] **Step 6: Teste de integração do contador**

Acrescente a `tests/integration/test_repositorio_intencao.py` — o arquivo que já exercita o upsert desta tabela:

- duas chamadas seguidas com `FORA_DE_ESCOPO` devolvem 1 e depois 2;
- uma chamada com `COMPRA` logo em seguida devolve 0;
- a primeira chamada de uma conversa nova com `FORA_DE_ESCOPO` devolve 1, e não 0 — o `INSERT` tem de contar também, e não só o `ON CONFLICT`.

**O terceiro é o que pega o erro mais provável desta task:** o `CASE` vive no `set_`, que só roda no conflito. Confirme o que o `INSERT` grava na primeira vez e, se ele gravar 0, acrescente o valor certo a `valores` — a conversa cuja primeira mensagem é fora de escopo tem de sair dali com 1.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit/test_regras_de_escopo.py tests/integration/test_repositorio_intencao.py --tb=short
git add src/mobia/domain/conversa/regras.py src/mobia/domain/agente/repositorio.py tests/unit/test_regras_de_escopo.py tests/integration/test_repositorio_intencao.py
git commit -m "feat(TEC-138): o turno conta mensagens fora de escopo seguidas e zera ao voltar ao assunto

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: O repositório da conversa

**Files:**
- Create: `src/mobia/domain/conversa/repositorio.py`
- Test: `tests/integration/test_conversa_encerrada.py` (cria)

**Interfaces:**
- Consumes: `Conversa` e os vocabulários (Task 1)
- Produces: `encerrar_conversa(session, *, channel, conversation_key, motivo, agora) -> None`; `esta_encerrada(session, *, channel, conversation_key, agora) -> bool`; `reabrir_conversa(session, *, channel, conversation_key) -> None`

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_conversa_encerrada.py` com estes casos, no padrão de `tests/integration/test_turno_optout.py`:

1. Conversa sem linha nenhuma **não** está encerrada — é o estado default, como em `esta_em_optout`.
2. Depois de `encerrar_conversa`, `esta_encerrada` é `True` e a linha tem `status`, `motivo_do_encerramento` e `encerrada_em` preenchidos.
3. Com `agora` 31 dias depois do encerramento, `esta_encerrada` é `False` — **a janela expirou e a linha continua dizendo `ENCERRADA`**. Esta é a asserta que prova que a decisão é do tempo e não só do status.
4. Com `agora` 29 dias depois, ainda `True`. É a contraprova da anterior, sem a qual um `esta_encerrada` que ignorasse o tempo passaria.
5. `reabrir_conversa` põe `status` de volta em `ATIVA` e limpa motivo e carimbo.
6. `encerrar_conversa` duas vezes não levanta e deixa o carimbo da segunda — é idempotente por upsert, e o teste existe porque `deve_encerrar` usa `>=` justamente para admitir a repetição.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_conversa_encerrada.py --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.conversa.repositorio'`

- [ ] **Step 3: Write minimal implementation**

Crie `src/mobia/domain/conversa/repositorio.py`:

```python
"""Leitura e escrita do ciclo de vida da conversa. TEC-138.

Nenhuma das tres commita -- a sessao e emprestada e o dono da transacao e quem
chama, como em `gravar_estado` e `registrar_recalculo`.
"""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.conversa.models import STATUS_ATIVA, STATUS_ENCERRADA, Conversa


async def encerrar_conversa(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    motivo: str,
    agora: datetime,
) -> None:
    """Marca a conversa como encerrada, com o motivo e o carimbo.

    Upsert e nao INSERT: a conversa pode ja ter linha de um encerramento
    anterior que a janela dos 30 dias ja reabriu. Encerrar de novo e
    idempotente de proposito -- `deve_encerrar` usa `>=` pela mesma razao.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "status": STATUS_ENCERRADA,
        "motivo_do_encerramento": motivo,
        "encerrada_em": agora,
    }
    statement = pg_insert(Conversa).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                "status": statement.excluded.status,
                "motivo_do_encerramento": statement.excluded.motivo_do_encerramento,
                "encerrada_em": statement.excluded.encerrada_em,
            },
        )
    )


async def esta_encerrada(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    agora: datetime,
) -> bool:
    """A conversa esta encerrada AGORA?

    Sem linha, nao esta -- o estado default e "pode receber", igual ao de
    `esta_em_optout`.

    **A resposta e do tempo, e nao so do status.** Um encerramento mais velho
    que a janela devolve False com a coluna ainda dizendo ENCERRADA: quem
    reabre e o turno, e ele so roda quando chega mensagem. Ate la a linha fica
    como estava, e esta funcao ja conta a verdade.

    `agora` entra por parametro, e nao de `datetime.now()` aqui dentro, pelo
    mesmo motivo que `e_conversa_nova` o recebe: e o que torna a janela
    testavel sem congelar relogio.
    """
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.encerrada_em).where(
                Conversa.channel == channel,
                Conversa.conversation_key == conversation_key,
            )
        )
    ).one_or_none()
    if linha is None or linha.status != STATUS_ENCERRADA or linha.encerrada_em is None:
        return False
    return agora - linha.encerrada_em < timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)


async def reabrir_conversa(session: AsyncSession, *, channel: str, conversation_key: str) -> None:
    """Volta a conversa para ATIVA e limpa motivo e carimbo.

    Nao zera o contador de fora de escopo: ele ja esta em zero desde o
    encerramento, e essa e a razao de o encerramento o zerar. Ver o comentario
    da coluna em `agente/models.py`.
    """
    await session.execute(
        update(Conversa)
        .where(Conversa.channel == channel, Conversa.conversation_key == conversation_key)
        .values(status=STATUS_ATIVA, motivo_do_encerramento=None, encerrada_em=None)
    )
```

**Confira quatro coisas antes de commitar, porque o plano não as adivinha:**

1. O import de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` cruza `domain/conversa/` e `domain/agente/`. **Se criar ciclo de import, pare e relate** em vez de duplicar a constante — duplicá-la é exatamente o que a D1 recusou.
2. `select(...).one_or_none()` sobre duas colunas devolve `Row`; confirme que o acesso por atributo (`linha.status`) funciona na versão de SQLAlchemy deste repo, e use o que estiver no idioma dos vizinhos se não funcionar.
3. `Conversa` usa chave primária composta e não `UniqueConstraint`. Confirme que `index_elements=["channel", "conversation_key"]` casa com a PK — em `conversation_intent`, que tem a mesma forma, casa.
4. `reabrir_conversa` não cria linha se não houver: um `UPDATE` sem linha é no-op, e está certo — não havia o que reabrir.

Pontos que o plano fixa e que não são escolha do implementador:

- **`esta_encerrada` recebe `agora` por parâmetro**, e não chama `datetime.now` por dentro. É o que torna o teste da janela possível sem congelar relógio, e é o padrão de `e_conversa_nova`, que também recebe `agora`.
- **A janela vem de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`**, importada de `domain/agente/identificacao.py`. Não escreva `30` aqui. Se o import criar ciclo entre os pacotes, **pare e relate** em vez de duplicar a constante.
- **`encerrar_conversa` é upsert** (`ON CONFLICT DO UPDATE`), não INSERT: a conversa pode já ter linha de um encerramento anterior já reaberto.
- **Nenhuma das três commita.** A sessão é emprestada e o dono da transação é quem chama, como em `gravar_estado` e `registrar_recalculo`.
- `esta_encerrada` devolve `False` quando não há linha, e a docstring diz que o default é "pode receber", no molde do docstring de `esta_em_optout`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_conversa_encerrada.py --tb=short`
Expected: 6 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/conversa/repositorio.py tests/integration/test_conversa_encerrada.py
git commit -m "feat(TEC-138): encerrar, reabrir e perguntar se a conversa esta dentro da janela

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: O turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — a despedida junto das outras constantes; o valor novo em `ResultadoDoTurno`; a guarda perto da de `esta_silenciada`; o encerramento no bloco transacional; a substituição do texto
- Test: acrescenta a `tests/integration/test_conversa_encerrada.py`

**Interfaces:**
- Consumes: `deve_encerrar` (Task 2), o retorno de `gravar_intencao` (Task 2), as três funções da Task 3
- Produces: nada que tarefas posteriores consumam

- [ ] **Step 1: Write the failing test**

Acrescente ao arquivo da Task 3. **Confira `rodar_turno` e o `ClassificadorFake` em `tests/conftest.py` antes de escrever** — `test_turno_optout.py` e `test_encaminhamento_por_intencao.py` são os irmãos a copiar.

O primeiro caso, completo, serve de molde para os outros — copie a forma dele:

```python
async def test_a_terceira_fora_de_escopo_encerra_e_despede(
    session, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """O cenario central da card, e as tres assertas sao tres fatos distintos.

    O texto entregue e o do repo e nao a prosa do modelo; a conversa fica
    ENCERRADA com motivo proprio; e o contador volta a ZERO -- este ultimo e o
    que faz o lead que volta depois dos 30 dias ter as tres tentativas de novo,
    em vez de ser encerrado na primeira mensagem.
    """
    entregador = outbound_fake()
    for _ in range(3):
        await rodar_turno(
            session,
            ClassificadorFake(intencao=Intencao.FORA_DE_ESCOPO, resposta=PROSA_DO_MODELO),
            entregador,
            resumidor_fake(),
            contador_fake(),
            texto="qual a previsao do tempo para amanha?",
        )

    assert entregador.entregues[-1] == TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO
    assert PROSA_DO_MODELO not in entregador.entregues[-1]

    linha = await session.get(Conversa, (CANAL, CONVERSA))
    assert linha is not None
    assert linha.status == STATUS_ENCERRADA
    assert linha.motivo_do_encerramento == MOTIVO_FORA_DE_ESCOPO

    intencao = await session.get(ConversationIntent, (CANAL, CONVERSA))
    assert intencao is not None
    assert intencao.fora_de_escopo_seguidas == 0
```

**Confira dois pontos antes de rodar**, porque o molde não os adivinha: que as três chamadas de `rodar_turno` caem na **mesma** conversa (senão o contador nunca passa de 1 e o teste mede outra coisa), e como o arquivo irmão obtém `ClassificadorFake` — o idioma é `from conftest import ClassificadorFake`.

Os outros casos, no mesmo molde, e cada um tem de reprovar contra a árvore da Task 3:

1. **Primeira e segunda fora de escopo:** a prosa do modelo é entregue nas duas, e o contador chega a 2.
2. **Terceira:** a despedida fixa é entregue **em vez** da prosa; a conversa fica `ENCERRADA` com motivo; o contador volta a **zero**.
3. **Quarta, no mesmo dia:** nada é entregue, o turno devolve `"fora_de_escopo"`, e **o classificador não é chamado**. Use um dublê que levante se chamado — esta é a única asserta que prova a economia, e sem ela a card inteira pode estar entregando silêncio caro.
4. **Uma mensagem dentro do escopo depois de duas fora** zera o contador e o atendimento segue normalmente.
5. **Passados 30 dias**, uma mensagem nova é atendida **e** o status volta a `ATIVA`. As duas metades: um status que não volta deixaria a próxima mensagem fora de escopo encerrar uma conversa já encerrada.
6. **Opt-out e silêncio de atendimento humano vencem a guarda nova** — dois testes, um para cada, com a conversa já encerrada e o resultado do turno sendo o daquelas políticas.
7. **O turno que encerra entrega a despedida:** a guarda não morde a si mesma.
8. **A contraprova da lacuna de cobertura:** uma mensagem redigida como pergunta imobiliária classifica dentro do escopo e **zera** o contador, mesmo tendo cara de sondagem. Existe para que ninguém leia esta card como defesa contra injection.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_conversa_encerrada.py --tb=short`
Expected: FAIL — a prosa do modelo sai na terceira e o quarto turno responde normalmente

- [ ] **Step 3: A despedida**

Junto das outras constantes de `turno.py`, no molde de `TEXTO_DO_LIMITE_DE_PERGUNTAS`:

```python
# RN-03.5 (TEC-138). Substitui a prosa do modelo na TERCEIRA mensagem fora de
# escopo seguida, e e a ultima coisa que o lead ouve antes dos 30 dias de
# silencio da D1.
#
# **Nao promete que alguem foi avisado**, pela razao que o comentario de
# TEXTO_DO_LIMITE_DE_PERGUNTAS acima ja registra e que `notificacao/envio.py`
# proibe nominalmente. Nao ha corretor nenhum nesta trilha: a conversa nao vai
# para fila, ela para.
#
# **Diz que a porta continua aberta**, e isso e a D1 escrita em produto: o
# encerramento e janela de silencio e nao portao, entao prometer "pode voltar"
# e verdade. Se algum dia o encerramento virar permanente, esta frase mente.
#
# Sem kind proprio, como TEXTO_DO_LIMITE_DE_PERGUNTAS: e substituicao em
# lugar, nao mensagem adicional, entao nao ha segunda mensagem com que colidir
# na UNIQUE (message_id, kind).
TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO = (
    "Acho que não vou conseguir ajudar com isso — aqui eu falo de imóveis. "
    "Se precisar procurar, alugar ou anunciar um, é só me chamar de novo."
)
```

- [ ] **Step 4: O valor novo em `ResultadoDoTurno`**

Acrescente `"fora_de_escopo"` ao `Literal`, com comentário no molde dos que já estão lá — os três do opt-out e os dois da TEC-179 explicam por extenso por que não se reusa um valor vizinho. O argumento aqui: `"silenciado"` já significa opt-out e `"atendimento_humano"` significa corretor assumiu; somar este aos dois tornaria impossível saber, no log, se o agente calou por pedido do lead, por decisão humana ou por política de escopo.

- [ ] **Step 5: A guarda**

Imediatamente **depois** do bloco de `esta_silenciada` / `tem_handoff_de_humano_aberto` e **antes** do `if pedido_de_optout:`. A forma segue a do bloco vizinho: abre sessão própria, consulta, loga e devolve.

O comentário tem de escrever três coisas, porque nenhuma é óbvia no sítio:
1. **Por que perde para as duas de cima** — opt-out é LGPD e silêncio humano é decisão de pessoa, e as duas vencem política automática.
2. **Por que ganha de tudo abaixo** — o ponto da guarda é não pagar a chamada, e tudo abaixo leva a ela.
3. **Por que ela não morde o turno que encerra** — o encerramento é gravado depois da chamada, então na terceira mensagem esta guarda ainda vê `ATIVA`.

**A reabertura entra aqui:** quando há linha `ENCERRADA` mas a janela já passou, o turno chama `reabrir_conversa` e **segue** — não devolve. O comentário diz que o gatilho é a mensagem do lead e que não há job.

- [ ] **Step 6: O encerramento e a substituição**

No bloco transacional, `gravar_intencao` passa a devolver o contador. Quando `deve_encerrar(seguidas)`:

- `encerrar_conversa(...)` na **mesma sessão e mesma transação** que `gravar_intencao`, pela razão que o comentário de `registrar_recalculo` já escreve para a trilha: ou os dois fatos existem, ou nenhum;
- **zere o contador** — é o que a seção do topo deste plano explica, e sem isso o lead que volta em 30 dias é encerrado na primeira mensagem;
- `log.info("conversa.encerrada", ...)` com canal, motivo e a contagem, **sem o texto das mensagens** (D7);
- e `texto` passa a ser `TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO`.

**Onde fica a substituição do texto:** no mesmo trecho em que as outras acontecem, e a ordem importa. Leia o comentário que declara a precedência entre `TEXTO_DO_LIMITE_DE_PERGUNTAS`, a citação bloqueada da TEC-161, o zero pós-relaxamento da TEC-160 e o encaminhamento da TEC-137, decida onde esta entra, **e escreva a razão no comentário**. Uma guarda `not saida_bloqueada` provavelmente vale aqui pelo mesmo motivo que vale para as vizinhas; confirme lendo aquele bloco.

- [ ] **Step 7: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_conversa_encerrada.py --tb=short`
Expected: todos passando

- [ ] **Step 8: Gates, suíte inteira e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta. **Duas falhas conhecidas e alheias:** `test_pedido_de_humano.py` reprova fora do horário comercial porque não congela a janela de atendimento — é a TEC-288, não sua. Fora essas, se falhar, rode de novo sobre a mesma árvore antes de culpar a mudança; se persistir idêntica, **pare e relate**.

**Atenção especial:** esta task acrescenta uma guarda no topo do turno, que é o caminho por onde TODO teste de integração passa. `test_turno.py`, `test_turno_optout.py` e `test_turno_atendimento_humano.py` são os que mais provavelmente reprovam. Se algum reprovar, **não o relaxe sem entender**: ou ele fixa a ordem das guardas que esta card muda de propósito — e aí é atualizar e declarar no relatório — ou pegou regressão.

```bash
git add src/mobia/domain/agente/turno.py tests/integration/test_conversa_encerrada.py
git commit -m "feat(TEC-138): a terceira mensagem fora de escopo encerra a conversa e a quarta nao paga chamada

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A prosa e as duas emendas

**Files:**
- Modify: `src/mobia/domain/context/repositorio.py` e outros que a listagem apontar
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (emendas à RN-03.5 e à RN-02.3)

- [ ] **Step 1: Rodar a listagem, e o `--tudo` não é opcional**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main --tudo
```

**Leia o `--tudo`.** O teto de cinco por bloco escondeu um comentário falso dentro de `executar_turno` na TEC-136, e esta card mexe justamente naquela função. A listagem também é cega a docstring de módulo (TEC-283) — confira à mão a de cada arquivo tocado.

- [ ] **Step 2: Reconferir a prosa que fala de "conversa encerrada"**

Vários módulos afirmam hoje que a conversa não tem entidade e que o encerramento não existe. Pelo menos estes, e a listagem pode apontar mais:

- `domain/atendimento/models.py` — *"Nao existe entidade 'conversa' neste sistema -- ela e este par, espalhado por oito tabelas"*. **Passou a existir.**
- `domain/agente/identificacao.py` — a docstring de topo diz que a fronteira de conversa não existe e que *"A TEC-130 e quem a cria"*, e o comentário de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` diz que a constante sai quando aquela card chegar. A primeira metade mudou; a segunda continua valendo.

**Julgue cada uma**: algumas continuam verdadeiras num sentido estreito e a ressalva as pioraria. Diga no relatório quais mudou e quais deixou, com a razão.

- [ ] **Step 3: Emenda à RN-03.5**

Acrescente `Emenda E-nn (TEC-138, 16/09/2026)` aninhada abaixo da RN-03.5, com o próximo `nn` livre **naquela regra** — a RN-03.5 não tem emenda hoje, então confirme que é E-01. **Sem reescrever** o texto de 22/08/2026.

Declara: o encerramento é janela de silêncio de 30 dias e não estado terminal; a contagem é de mensagens `FORA_DE_ESCOPO` **seguidas** e qualquer outra intenção zera; a despedida é texto fixo do repo, mas as duas primeiras respostas continuam sendo prosa do modelo, sem garantia de redirecionamento; e a partir da quarta mensagem dentro da janela o turno não chama o modelo.

- [ ] **Step 4: Emenda à RN-02.3**

Esta é a que a D3 exige. A Emenda E-01 daquela regra diz hoje que *"o encerramento de conversa segue sendo só por inatividade (TEC-130, ainda a fazer) ou por opt-out"* e adverte que *"a TEC-130 tem de respeitar essa separação quando chegar"*. **As duas frases ficaram falsas.**

Acrescente a próxima emenda livre da RN-02.3 declarando: existe um terceiro motivo de encerramento, `FORA_DE_ESCOPO`; a entidade de conversa passou a existir nesta card, com `status` e `motivo_do_encerramento`; e **a TEC-130 estende essa entidade em vez de criá-la**, acrescentando o motivo `INATIVIDADE` e o escritor dele. Não reescreva a E-01: a advertência dela continua tendo valor histórico, e a emenda nova é quem diz o que mudou.

Prosa em `docs/` vai **COM** acento.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
git add src/ docs/srs/
git commit -m "docs(TEC-138): a conversa passou a ter entidade, e duas regras do SRS ganham emenda

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite da card

| cenário Gherkin | onde é exercitado |
| --- | --- |
| Primeira mensagem fora de escopo é redirecionada | **não exercitado** — é prosa do modelo, sem literal e sem instrução no prompt. Lacuna declarada na D6 |
| Encerrar após a terceira mensagem fora de escopo seguida | T4 teste 2 — despedida fixa, status `ENCERRADA`, motivo próprio |
| Voltar ao assunto zera o contador | T2 (integração) e T4 teste 4 |

**Lacunas declaradas** (todas no desenho, e vão no comentário da card): o redirecionamento das duas primeiras continua emergente; a economia só começa na quarta mensagem; um falso positivo do classificador em três turnos cala o lead por 30 dias, em silêncio; não há histórico de encerramentos; a cobertura contra prompt injection é parcial e acidental, e o teste 8 da Task 4 existe para provar isso.

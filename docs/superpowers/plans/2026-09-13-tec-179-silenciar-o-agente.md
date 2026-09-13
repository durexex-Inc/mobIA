# TEC-179 — Silenciar o agente quando o corretor assume — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando um corretor assume uma conversa, o agente para de enviar qualquer coisa nela — pelo turno, pela porta de saída e pelas automações — até alguém devolver explicitamente.

**Architecture:** Uma tabela `atendimento_humano` com uma linha por conversa (`UNIQUE (channel, conversation_key)`), silenciada enquanto `devolvido_em IS NULL`. Duas rotas administrativas escrevem esse estado com UPDATE condicionado no próprio `WHERE` e `RETURNING` decidindo a resposta. Quatro guardas leem: a saída barata no topo do turno, o recheque concorrente antes do log, a autoritativa dentro do `GuardedOutbound.send`, e a do `sweep_followups`. O molde inteiro é o do opt-out (TEC-182), que já resolveu este mesmo problema.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async (dialeto `postgresql` para `ON CONFLICT`), Alembic, ARQ, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-tec-179-silenciar-o-agente-design.md`

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `alembic/`: português SEM acento.** Prosa em `docs/`: com acento. Nenhum linter checa isto.
- **Comentário desatualizado é defeito, não sujeira.** Se você mudar código que um comentário descreve, o comentário muda junto ou some.
- **Nenhum conteúdo de lead pode sobreviver em log.** Nem corpo de mensagem, nem resumo. `channel`, `conversation_key`, `message_id` e ids são permitidos — é o que os logs existentes já carregam.
- **Os três gates do CI, nesta ordem e neste escopo:** `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`. **O formatador é gate separado do linter.** Local: `./.venv/Scripts/python.exe -m ruff check ...`.
- **`ruff format` NÃO quebra string longa.** Um literal comprido continua reprovando o `E501` (limite 100) depois de formatado — quebre à mão.
- Testes: `./.venv/Scripts/python.exe -m pytest tests/unit` (rápido, sem Docker). Integração exige `docker compose` de pé.
- Mensagens de commit em português sem acento no assunto, formato `tipo(TEC-179): o que passou a ser verdade`, terminando com a linha `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Emendas ao SRS** (`docs/srs/srs-agente-sdr-imobiliario-v1.0.md`) entram como item aninhado `Emenda E-nn (TEC-179, 13/09/2026)` **abaixo** da regra que alteram, nunca reescrevendo o texto de 22/08/2026.
- **Nunca use um dublê de teste como default de produção.** Nada de `ctx.get("x") or NoopX()` — ver a guarda em `workers/main.py`.
- **Nada de controle de fluxo por substring de mensagem de erro**, e nada de `assert` dentro de validador Pydantic (some sob `python -O`).

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `alembic/versions/0029_atendimento_humano.py` | a tabela; encadeia em `0028` |
| `src/mobia/domain/atendimento/__init__.py` | pacote novo |
| `src/mobia/domain/atendimento/models.py` | `AtendimentoHumano` |
| `src/mobia/domain/atendimento/repositorio.py` | `assumir`, `devolver`, `esta_silenciada`, `esta_silenciada_por_mensagem` |
| `src/mobia/api/routes/conversas.py` | as duas rotas |
| `src/mobia/domain/outbound/port.py` | guarda autoritativa (modificar) |
| `src/mobia/domain/agente/turno.py` | saída barata, recheque concorrente, dois desfechos (modificar) |
| `src/mobia/workers/jobs/sweep_followups.py` | guarda da automação (modificar) |
| `tests/conftest.py` | `atendimento_humano` em `TABELAS` (modificar) |

---

### Task 1: A tabela e o modelo

**Files:**
- Create: `alembic/versions/0029_atendimento_humano.py`
- Create: `src/mobia/domain/atendimento/__init__.py` (vazio)
- Create: `src/mobia/domain/atendimento/models.py`
- Modify: `tests/conftest.py` — acrescentar `"atendimento_humano"` ao final da tupla `TABELAS` (linha ~174, depois de `"corretores"`)
- Test: `tests/integration/test_atendimento_schema.py`

**Interfaces:**
- Consumes: `mobia.domain.messages.models.Base`; `mobia.domain.corretores.models.Corretor` (para a FK)
- Produces: `AtendimentoHumano` com os campos `id`, `channel`, `conversation_key`, `assumido_por`, `assumido_em`, `devolvido_por`, `devolvido_em`, `criado_em`, `atualizado_em`; `__tablename__ = "atendimento_humano"`

**Contexto que você precisa saber:**

A revisão `head` de hoje é `0028`. Confira com `./.venv/Scripts/python.exe -m alembic heads` antes de começar: se voltar algo diferente de `0028`, **pare e avise** — outra branch mexeu na cadeia.

A FK para `corretores.id` precisa usar **`ForeignKey(Corretor.id)` com o objeto importado**, e não a string `"corretores.id"`. A razão está escrita em `src/mobia/domain/handoff/models.py`: a string só resolve se **alguém mais** já tiver importado `Corretor` (o que a suíte inteira faz por acidente), e sem o import explícito o teste de schema reprova com `NoReferencedTableError` quando roda sozinho — que é justamente o procedimento de diagnóstico que o CLAUDE.md prescreve.

- [ ] **Step 1: Escreva o teste de schema que falha**

Crie `tests/integration/test_atendimento_schema.py`:

```python
"""A tabela que diz quem assumiu qual conversa. TEC-179, RN-16.4."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.atendimento.models import AtendimentoHumano
from mobia.domain.corretores.models import Corretor

pytestmark = pytest.mark.asyncio


async def test_uma_conversa_so_tem_uma_linha(session, semear_corretor, banco_limpo):
    """O UNIQUE e o que faz o 409 "ja assumida por outro" ser do banco.

    Sem ele, duas abas do painel clicando "assumir" ao mesmo tempo gravariam
    duas linhas e as duas se achariam vencedoras -- exatamente o padrao que a
    D6 da TEC-178 e a L4 da TEC-174 existem para eliminar.
    """
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    agora = datetime.now(UTC)
    for _ in range(2):
        session.add(
            AtendimentoHumano(
                id=uuid.uuid4(),
                channel="whatsapp",
                conversation_key="5511988887777",
                assumido_por=corretor_id,
                assumido_em=agora,
                criado_em=agora,
                atualizado_em=agora,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_devolvido_nasce_nulo_e_e_isso_que_significa_silenciada(session, semear_corretor, banco_limpo):
    """Nao ha coluna `ativo`: silenciada E `devolvido_em IS NULL` (D4).

    Uma booleana ao lado dos carimbos seria uma segunda representacao do
    mesmo fato, e as duas podem divergir -- a classe de defeito que a revisao
    final da TEC-177 encontrou em `notificado_em`/`aviso_manual_pendente`.
    """
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    agora = datetime.now(UTC)
    session.add(
        AtendimentoHumano(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511988887777",
            assumido_por=corretor_id,
            assumido_em=agora,
            criado_em=agora,
            atualizado_em=agora,
        )
    )
    await session.flush()

    linha = (await session.execute(select(AtendimentoHumano))).scalar_one()
    assert linha.devolvido_em is None
    assert linha.devolvido_por is None
    assert not hasattr(linha, "ativo"), "coluna `ativo` viola a D4 do desenho"
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_atendimento_schema.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.atendimento'`

- [ ] **Step 3: Crie o pacote e o modelo**

`src/mobia/domain/atendimento/__init__.py`: arquivo vazio.

`src/mobia/domain/atendimento/models.py`:

```python
"""Quem assumiu qual conversa, e ate quando o agente fica calado.

TEC-179, RN-16.4. Uma linha por conversa, e NAO um log append-only como
`optout_events` -- a D1 do desenho explica: o SRS especifica 409 "ja assumida
por outro", e com append-only responder isso exige ler antes de inserir. Duas
abas do painel clicando ao mesmo tempo gravariam dois eventos, ambos se
achando vencedores. O historico de todos os ciclos, que o append-only daria
de graca, e a trilha de auditoria da TEC-206.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.corretores.models import Corretor
from mobia.domain.messages.models import Base


class AtendimentoHumano(Base):
    __tablename__ = "atendimento_humano"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica a conversa, o mesmo de `optout_events` e
    # `handoffs`. Nao existe entidade "conversa" neste sistema -- ela e este
    # par, espalhado por oito tabelas (D9 do desenho).
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # `ForeignKey(Corretor.id)` em vez da string "corretores.id": o alvo
    # precisa estar no mesmo `MetaData` para o SQLAlchemy resolver a FK, e a
    # string so funciona se ALGUEM MAIS ja tiver importado `Corretor` antes.
    # Sem o import explicito acima, este teste de schema reprova com
    # `NoReferencedTableError` quando roda sozinho -- e "rodar o arquivo
    # sozinho" e o proprio procedimento de diagnostico do CLAUDE.md. Mesma
    # razao ja escrita em `handoff/models.py`.
    assumido_por: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Corretor.id), nullable=False
    )
    assumido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # **Nulos os dois sao o que significa "silenciada" -- nao ha coluna
    # `ativo`.** D4 do desenho: uma booleana ao lado destes carimbos seria uma
    # segunda representacao do mesmo fato, e as duas podem divergir. Esse e o
    # defeito que a revisao final da TEC-177 encontrou em
    # `notificado_em`/`aviso_manual_pendente` e que a D5 da TEC-176 preveniu.
    # Quem pergunta "esta silenciada?" pergunta `devolvido_em IS NULL`, e
    # `esta_silenciada` (repositorio.py) e a unica implementacao dessa frase.
    devolvido_por: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Corretor.id), nullable=True
    )
    devolvido_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # E o arbitro da corrida, nao um indice de performance: o `ON
        # CONFLICT` de `assumir` (repositorio.py) casa por ele.
        UniqueConstraint("channel", "conversation_key", name="uq_atendimento_conversa"),
    )
```

- [ ] **Step 4: Escreva a migration**

`alembic/versions/0029_atendimento_humano.py`:

```python
"""quem assumiu qual conversa, para o agente calar

TEC-179, RF-16 e RN-16.4.

**Uma linha por conversa, com UNIQUE -- e nao um log append-only.** O
`optout_events` resolve o problema vizinho pelo caminho oposto, e a D1 do
desenho explica a divergencia: la o append-only existe porque a LGPD exige o
registro como prova, e nada precisa recusar um segundo opt-out. Aqui o SRS
especifica 409 "ja assumida por outro", e essa recusa tem de ser arbitrada
pelo banco. O UNIQUE abaixo e o arbitro.

**Nao ha coluna `ativo`.** Silenciada e `devolvido_em IS NULL`. Uma booleana
ao lado dos carimbos seria uma segunda representacao do mesmo fato -- e duas
colunas que dizem o mesmo divergem, como `notificado_em` e
`aviso_manual_pendente` divergiam antes da revisao final da TEC-177.

**`assumido_por` e NOT NULL, `devolvido_por` e nulavel.** Nao ha linha sem
alguem tendo assumido: a linha nasce do ato de assumir. Devolver e o ato
posterior que pode nao ter acontecido ainda.

As duas FK apontam para `corretores.id` (TEC-196). Sem `ondelete`: apagar
corretor com conversa atribuida deve reprovar, nao apagar o registro de quem
atendeu.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "atendimento_humano",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column(
            "assumido_por",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corretores.id", name="fk_atendimento_assumido_por"),
            nullable=False,
        ),
        sa.Column("assumido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "devolvido_por",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corretores.id", name="fk_atendimento_devolvido_por"),
            nullable=True,
        ),
        sa.Column("devolvido_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("channel", "conversation_key", name="uq_atendimento_conversa"),
    )


def downgrade() -> None:
    op.drop_table("atendimento_humano")
```

Se o `import sqlalchemy.dialects.postgresql` não estiver acessível por `sa.dialects.postgresql`, importe explicitamente: `from sqlalchemy.dialects import postgresql` e use `postgresql.UUID(as_uuid=True)`. Confira como as migrations `0025_corretores.py` e `0028_sla_de_aceite.py` fazem e **siga o que já está lá**.

- [ ] **Step 5: Acrescente a tabela ao `TABELAS` do conftest**

Em `tests/conftest.py`, no final da tupla `TABELAS`, depois de `"corretores",`:

```python
    # TEC-179. Mutavel, como `handoffs`: o UNIQUE por (channel,
    # conversation_key) faz a conversa de um teste bloquear o assumir do
    # proximo, e a falha apareceria so a partir do segundo teste do arquivo.
    "atendimento_humano",
```

- [ ] **Step 6: Aplique e rode**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_atendimento_schema.py -v
```
Expected: `alembic heads` passa a mostrar `0029 (head)`; os dois testes PASSAM.

- [ ] **Step 7: Prove que o `downgrade` funciona**

```bash
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: os dois comandos terminam sem erro. Uma migration cujo `downgrade` nunca foi exercitado é uma migration que ninguém consegue reverter em produção.

- [ ] **Step 8: Rode o arquivo SOZINHO**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_atendimento_schema.py`
Expected: PASSA. Se reprovar com `NoReferencedTableError`, o import de `Corretor` não está sendo **usado** — releia o Step 3.

- [ ] **Step 9: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add alembic/versions/0029_atendimento_humano.py src/mobia/domain/atendimento/ tests/conftest.py tests/integration/test_atendimento_schema.py
git commit -m "feat(TEC-179): a conversa passa a saber quem a assumiu"
```

---

### Task 2: O repositório — as duas perguntas e as duas escritas

**Files:**
- Create: `src/mobia/domain/atendimento/repositorio.py`
- Test: `tests/integration/test_atendimento_repositorio.py`

**Interfaces:**
- Consumes: `AtendimentoHumano` (Task 1); `mobia.domain.messages.models.Message`
- Produces:
  - `async def esta_silenciada(session: AsyncSession, *, channel: str, conversation_key: str) -> bool`
  - `async def esta_silenciada_por_mensagem(session: AsyncSession, message_id: uuid.UUID) -> bool`
  - `async def assumir(session: AsyncSession, *, channel: str, conversation_key: str, corretor_id: uuid.UUID) -> Atendimento | None`
  - `async def devolver(session: AsyncSession, *, channel: str, conversation_key: str, corretor_id: uuid.UUID) -> Atendimento | None`
  - `@dataclass(frozen=True) class Atendimento: assumido_por: uuid.UUID; assumido_em: datetime`

**Contexto que você precisa saber:**

As duas assinaturas de consulta são deliberadamente **as mesmas do opt-out** (`src/mobia/domain/optout/repositorio.py`): `esta_em_optout(session, *, channel, conversation_key)` e `esta_em_optout_por_mensagem(session, message_id)`. Os sítios de chamada precisam exatamente dessas duas formas — a varredura tem o par, o `GuardedOutbound.send` só tem o id da mensagem. Abra aquele arquivo e espelhe.

`assumir` e `devolver` devolvem `None` quando a operação foi **recusada** (ninguém mudou), e o objeto quando ela valeu. Quem distingue 404 de 409 é a rota (Task 6), não este módulo.

**O `assumir` é um `ON CONFLICT DO UPDATE` com `where`, e o `assumido_em` não pode andar para frente.** Reassumir pela mesma pessoa é 200 idempotente (o SRS diz 409 "já assumida por **outro**"), mas o carimbo tem de continuar sendo o do primeiro assumir — mover faria o corretor parecer ter pegado a conversa mais tarde do que pegou. É o mesmo argumento da D8 da TEC-178 sobre `aceito_em`.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_atendimento_repositorio.py`:

```python
"""Assumir, devolver, e a pergunta que as quatro guardas fazem. TEC-179."""

import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.atendimento.repositorio import (
    assumir,
    devolver,
    esta_silenciada,
    esta_silenciada_por_mensagem,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message

pytestmark = pytest.mark.asyncio

CHANNEL = "whatsapp"
CHAVE = "5511988887777"


async def test_sem_linha_nenhuma_a_conversa_nao_esta_silenciada(session, semear_corretor, banco_limpo):
    """O estado default e "o agente pode falar" -- mesma forma do opt-out."""
    assert not await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_assumir_silencia(session, semear_corretor, banco_limpo):
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    assert await assumir(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    ) is not None
    assert await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_devolver_devolve_a_voz_ao_agente(session, semear_corretor, banco_limpo):
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
    assert await devolver(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    ) is not None
    assert not await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_outro_corretor_nao_assume_o_que_ja_tem_dono(session, semear_corretor, banco_limpo):
    """O 409 do SRS: "ja assumida por outro"."""
    paulo = (await semear_corretor(email=f"paulo-{uuid.uuid4().hex[:8]}@ex.com")).id
    marina = (await semear_corretor(email=f"marina-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=paulo)
    assert await assumir(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=marina
    ) is None


async def test_reassumir_pela_mesma_pessoa_nao_move_o_carimbo(session, semear_corretor, banco_limpo):
    """D3: idempotente, e `assumido_em` fica onde estava.

    Mesmo argumento que a D8 da TEC-178 faz sobre `aceito_em`: um carimbo que
    anda para frente faria o corretor parecer ter pegado a conversa mais tarde
    do que pegou. Este teste falharia se o `ON CONFLICT` gravasse `agora` sem
    condicao -- os dois `datetime.now(UTC)` das duas chamadas nao coincidem.
    """
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    primeiro = await assumir(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    )
    assert primeiro is not None
    segundo = await assumir(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    )
    assert segundo is not None
    assert segundo.assumido_em == primeiro.assumido_em


async def test_depois_de_devolvida_qualquer_um_reassume(session, semear_corretor, banco_limpo):
    """E a linha e reusada -- o UNIQUE impede uma segunda."""
    paulo = (await semear_corretor(email=f"paulo-{uuid.uuid4().hex[:8]}@ex.com")).id
    marina = (await semear_corretor(email=f"marina-{uuid.uuid4().hex[:8]}@ex.com")).id
    primeiro = await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=paulo)
    assert primeiro is not None
    await devolver(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=paulo)

    segundo = await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=marina)
    assert segundo is not None
    assert segundo.assumido_por == marina
    # O carimbo ANDA aqui, ao contrario do teste acima: e um assumir novo.
    assert segundo.assumido_em > primeiro.assumido_em
    assert await esta_silenciada(session, channel=CHANNEL, conversation_key=CHAVE)


async def test_devolver_o_que_ninguem_assumiu_e_recusado(session, semear_corretor, banco_limpo):
    """Nao e 200 silencioso: devolver exige que alguem tenha assumido."""
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    assert await devolver(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    ) is None


async def test_devolver_duas_vezes_e_recusado_na_segunda(session, semear_corretor, banco_limpo):
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
    assert await devolver(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    ) is not None
    assert await devolver(
        session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id
    ) is None


async def test_por_mensagem_resolve_o_par_e_responde_o_mesmo(session, semear_corretor, banco_limpo):
    """A forma que o `GuardedOutbound.send` precisa -- so tem o message_id."""
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    mensagem = Message(
        id=uuid.uuid4(),
        channel=CHANNEL,
        conversation_key=CHAVE,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status="PROCESSED",
    )
    session.add(mensagem)
    await session.flush()

    assert not await esta_silenciada_por_mensagem(session, mensagem.id)
    await assumir(session, channel=CHANNEL, conversation_key=CHAVE, corretor_id=corretor_id)
    assert await esta_silenciada_por_mensagem(session, mensagem.id)


async def test_mensagem_inexistente_nao_esta_silenciada(session, semear_corretor, banco_limpo):
    """Mesma decisao de `esta_em_optout_por_mensagem`: sem lead, nada a barrar.

    Recusar o envio aqui esconderia o defeito real -- um `message_id` que nao
    existe e problema de quem chamou, nao uma conversa assumida.
    """
    assert not await esta_silenciada_por_mensagem(session, uuid.uuid4())
```

**Antes de escrever a implementação**, confira os campos obrigatórios de `Message` em `src/mobia/domain/messages/models.py` e o enum em `src/mobia/domain/messages/enums.py`. Se `Message` exigir colunas que o teste acima não preenche, acrescente-as ao teste — **não** invente campos que não existem.

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_atendimento_repositorio.py -v`
Expected: FAIL com `ImportError: cannot import name 'assumir'`

- [ ] **Step 3: Escreva o repositório**

`src/mobia/domain/atendimento/repositorio.py`:

```python
"""Assumir, devolver, e a pergunta que as quatro guardas fazem. TEC-179.

As duas consultas espelham `optout/repositorio.py` de proposito, inclusive na
assinatura: os sitios de chamada precisam exatamente dessas duas formas -- o
`sweep_followups` tem o par do lead, e o `GuardedOutbound.send` so tem o id da
mensagem. Duplicar a forma ali era a escolha certa e continua sendo aqui.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.atendimento.models import AtendimentoHumano
from mobia.domain.messages.models import Message


@dataclass(frozen=True)
class Atendimento:
    """O que a rota precisa devolver depois de assumir ou devolver."""

    assumido_por: uuid.UUID
    assumido_em: datetime


async def esta_silenciada(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> bool:
    """Alguem assumiu esta conversa e ainda nao devolveu.

    Sem linha nenhuma, nao esta -- o estado default e "o agente pode falar",
    mesma forma que `esta_em_optout` ja usa para o estado default de la.

    A condicao e `devolvido_em IS NULL` e nao uma coluna `ativo`: ver a D4 do
    desenho e o comentario do modelo. Esta funcao e a UNICA implementacao da
    frase "esta silenciada", pela mesma razao que o docstring de
    `sweep_followups` da para `esta_em_optout`.
    """
    achou = (
        await session.execute(
            select(AtendimentoHumano.id)
            .where(
                AtendimentoHumano.channel == channel,
                AtendimentoHumano.conversation_key == conversation_key,
                AtendimentoHumano.devolvido_em.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return achou is not None


async def esta_silenciada_por_mensagem(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """A mesma pergunta, para quem so tem o id da mensagem.

    E o caso da guarda em `GuardedOutbound.send`, cuja assinatura nao carrega
    o par da conversa. Mensagem inexistente devolve False: se nao ha conversa,
    nao ha atendimento humano a respeitar, e recusar o envio por isso
    esconderia o defeito real. Mesma decisao de
    `esta_em_optout_por_mensagem`.
    """
    conversa = (
        await session.execute(
            select(Message.channel, Message.conversation_key).where(Message.id == message_id)
        )
    ).one_or_none()
    if conversa is None:
        return False
    return await esta_silenciada(
        session, channel=conversa.channel, conversation_key=conversa.conversation_key
    )


async def assumir(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    corretor_id: uuid.UUID,
) -> Atendimento | None:
    """O corretor assume a conversa. `None` quando outro ja a tem.

    **Um statement, e nao um SELECT seguido de INSERT.** O SRS especifica 409
    "ja assumida por outro", e quem arbitra essa recusa e o UNIQUE
    `uq_atendimento_conversa`, nao a ordem do codigo -- mesmo raciocinio do
    `ON CONFLICT` de `registrar_handoff` e do UPDATE condicionado da rota de
    aceite da TEC-178. Duas abas do painel clicando ao mesmo tempo nao podem
    as duas se achar vencedoras.

    O `where` do `ON CONFLICT` e quem define quando a atualizacao vale: a
    conversa ja foi devolvida (qualquer um reassume), ou quem pede e o mesmo
    que ja a tem (idempotente). Fora desses dois casos nenhuma linha muda, o
    RETURNING vem vazio, e a resposta e `None`.

    **`assumido_em` NAO anda no caso idempotente.** O `case` abaixo e o que
    garante isso: quando a linha esta silenciada (`devolvido_em IS NULL`), o
    `where` ja provou que o pedinte e o dono atual, entao o carimbo antigo
    fica. Mover faria o corretor parecer ter pegado a conversa mais tarde do
    que pegou -- o mesmo argumento que a D8 da TEC-178 faz sobre `aceito_em`.
    """
    agora = datetime.now(UTC)
    statement = pg_insert(AtendimentoHumano).values(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        assumido_por=corretor_id,
        assumido_em=agora,
        criado_em=agora,
        atualizado_em=agora,
    )
    linha = (
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_atendimento_conversa",
                set_={
                    "assumido_por": corretor_id,
                    "assumido_em": case(
                        (AtendimentoHumano.devolvido_em.is_(None), AtendimentoHumano.assumido_em),
                        else_=agora,
                    ),
                    "devolvido_por": None,
                    "devolvido_em": None,
                    "atualizado_em": agora,
                },
                where=or_(
                    AtendimentoHumano.devolvido_em.is_not(None),
                    AtendimentoHumano.assumido_por == corretor_id,
                ),
            ).returning(AtendimentoHumano.assumido_por, AtendimentoHumano.assumido_em)
        )
    ).first()

    if linha is None:
        return None
    return Atendimento(assumido_por=linha.assumido_por, assumido_em=linha.assumido_em)


async def devolver(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    corretor_id: uuid.UUID,
) -> Atendimento | None:
    """O corretor devolve a conversa ao agente. `None` quando nao havia o que devolver.

    `devolvido_em IS NULL` no proprio WHERE, e o RETURNING decide -- nunca um
    SELECT antes. Devolver duas vezes nao pode gravar duas vezes, pelo mesmo
    motivo que assumir duas vezes nao move o carimbo.

    **Qualquer corretor pode devolver, nao so quem assumiu.** Nao ha
    identidade provada (D2 do desenho: o `corretor_id` e afirmacao de quem
    chama), entao exigir que fosse o mesmo daria uma sensacao de controle que
    o sistema nao tem -- e travaria o caso real de um corretor que assumiu e
    saiu de ferias. Quem devolveu fica gravado.
    """
    agora = datetime.now(UTC)
    linha = (
        await session.execute(
            update(AtendimentoHumano)
            .where(
                AtendimentoHumano.channel == channel,
                AtendimentoHumano.conversation_key == conversation_key,
                AtendimentoHumano.devolvido_em.is_(None),
            )
            .values(devolvido_por=corretor_id, devolvido_em=agora, atualizado_em=agora)
            .returning(AtendimentoHumano.assumido_por, AtendimentoHumano.assumido_em)
        )
    ).first()

    if linha is None:
        return None
    return Atendimento(assumido_por=linha.assumido_por, assumido_em=linha.assumido_em)
```

- [ ] **Step 4: Rode os testes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_atendimento_repositorio.py -v`
Expected: os dez PASSAM.

Se o `constraint="uq_atendimento_conversa"` não for aceito, troque por `index_elements=["channel", "conversation_key"]` — as duas formas existem no SQLAlchemy e `registrar_handoff` usa a segunda. **Não** mude o nome do constraint na migration para acomodar o código.

- [ ] **Step 5: Falsifique o teste do carimbo**

Remova o `case(...)` e deixe `"assumido_em": agora`. Rode `test_reassumir_pela_mesma_pessoa_nao_move_o_carimbo`. Ele **tem** de reprovar. Restaure depois. Um teste que passa sem a guarda não é teste.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/atendimento/repositorio.py tests/integration/test_atendimento_repositorio.py
git commit -m "feat(TEC-179): assumir e devolver, com o banco arbitrando quem ganhou"
```

---

### Task 3: A guarda autoritativa, dentro da porta de saída

**Files:**
- Modify: `src/mobia/domain/outbound/port.py` — o bloco de guarda em `GuardedOutbound.send` (~linha 160) e o docstring de `OutboundPort`
- Test: `tests/unit/test_outbound_atendimento.py`

**Interfaces:**
- Consumes: `esta_silenciada_por_mensagem` (Task 2)
- Produces: nada novo — `send` continua devolvendo `False` sem levantar

**Contexto que você precisa saber:**

Esta é a guarda que importa. O docstring de `OutboundPort` já argumenta por que ela mora aqui: *"quem HERDA desta classe ganha a guarda de graça, sem precisar lembrar dela"*, e no turno *"ela protegeria o caminho de hoje e nada mais"*.

**A guarda de silêncio barra TUDO — não há escotilha por `kind`.** O opt-out abre exceção para `KIND_DA_CONFIRMACAO_DE_OPTOUT`; esta não abre nenhuma. A D5 do desenho explica: não existe caminho humano de envio para deixar passar (a rota `POST /conversas/{id}/mensagens` do SRS não existe), e construir a lista de exceções hoje seria construí-la para um chamador hipotético.

**Isto não sobreviveu à Task 3.** Ver a "Emenda à execução" ao fim da D5 no desenho: a guarda ganhou uma exceção, `KIND_DA_CONFIRMACAO_DE_OPTOUT`, pelo mesmo motivo que a do opt-out já tinha. O parágrafo acima descreve a decisão original, não o código entregue.

**Ordem:** a guarda de silêncio vai **depois** da de opt-out e **antes** da reserva. Antes da reserva pela razão que o comentário existente já dá — barrar depois deixaria linha órfã em `outbound_dispatches`, e o sweeper leria isso como tentativa feita.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_outbound_atendimento.py`. Abra `tests/unit/` e procure um teste existente de `GuardedOutbound` para copiar o formato do dublê (a subclasse que implementa `_deliver`). **Use o que já estiver lá**; se não houver, use este esqueleto e adapte:

```python
"""A guarda que cala o agente na porta de saida. TEC-179, RN-16.4."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.port import GuardedOutbound

pytestmark = pytest.mark.asyncio


class _Espia(GuardedOutbound):
    """Registra o que chegou a `_deliver` -- e o que a guarda deixou passar."""

    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregues: list[str] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregues.append(kind)


async def test_conversa_assumida_nao_recebe_nada_do_agente(session_factory, semear_corretor, banco_limpo):
    """A guarda barra TODO kind -- nao ha escotilha (D5 do desenho).

    Se algum dia alguem acrescentar uma excecao por `kind` aqui, este teste
    reprova, e e o alarme certo: a rota de envio manual do corretor tem de
    decidir isso explicitamente, nao herda-la por acidente.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    async with session_factory() as sessao:
        mensagem = Message(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511988887777",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            status="PROCESSED",
        )
        sessao.add(mensagem)
        await assumir(
            sessao,
            channel="whatsapp",
            conversation_key="5511988887777",
            corretor_id=corretor.id,
        )
        await sessao.commit()
        message_id = mensagem.id

    porta = _Espia(session_factory)
    assert await porta.send(message_id, "texto", {"body": "oi"}) is False
    assert porta.entregues == []


async def test_conversa_devolvida_volta_a_receber(session_factory, banco_limpo):
    """Prova que a guarda le o estado CORRENTE, nao "ja foi assumida um dia"."""
    agora = datetime.now(UTC)
    async with session_factory() as session:
        mensagem = Message(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511988887777",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            status="PROCESSED",
        )
        session.add(mensagem)
        await session.commit()
        message_id = mensagem.id

    porta = _Espia(session_factory)
    assert await porta.send(message_id, "texto", {"body": "oi"}) is True
    assert porta.entregues == ["texto"]
```

**Se `session_factory` não for o nome da fixture**, abra `tests/conftest.py` e use o nome real. Se o teste precisar de Postgres, ele vai para `tests/integration/` e não `tests/unit/` — decida pelo que a fixture exige e **mova o arquivo** se for o caso.

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_outbound_atendimento.py -v`
Expected: o primeiro teste FALHA (`send` devolve `True` e entrega).

- [ ] **Step 3: Acrescente a guarda**

Em `src/mobia/domain/outbound/port.py`, dentro de `GuardedOutbound.send`, **logo depois** do bloco `if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT:` e **antes** do `async with self._session_factory() as session:` que faz a reserva:

```python
        # A guarda de atendimento humano (TEC-179, RN-16.4). Mora aqui pela
        # mesma razao que a de opt-out logo acima, e o docstring do
        # `OutboundPort` ja escreve: quem herda ganha a guarda de graca. No
        # turno ela protegeria so o caminho de hoje.
        #
        # **Barra TODO kind, sem a escotilha que o opt-out tem.** A D5 do
        # desenho decide isso: nao existe caminho humano de envio para deixar
        # passar -- a rota `POST /conversas/{id}/mensagens` do SRS nao esta
        # implementada --, e uma lista de excecoes construida agora seria para
        # um chamador hipotetico. Quando aquela rota chegar ela vai encontrar
        # o proprio envio barrado aqui, e tera de decidir como o humano
        # atravessa. Falhar fechado e o lado certo de errar, e a L3 do desenho
        # existe para que ninguem descubra isso por um teste vermelho sem
        # explicacao.
        #
        # Antes da reserva pelo mesmo motivo do bloco acima: barrar depois
        # deixaria linha orfa em `outbound_dispatches`.
        async with self._session_factory() as session:
            if await esta_silenciada_por_mensagem(session, message_id):
                # `warning` e nao `info`, pelo mesmo criterio do opt-out: um
                # envio barrado aqui significa que algum caminho tentou falar
                # por cima do corretor que assumiu.
                log.warning(
                    "outbound.atendimento_humano_bloqueou",
                    message_id=str(message_id),
                    kind=kind,
                )
                return False
```

E o import no topo do arquivo:

```python
from mobia.domain.atendimento.repositorio import esta_silenciada_por_mensagem
```

- [ ] **Step 4: Atualize o docstring do `OutboundPort` — ele passou a mentir**

O docstring de `OutboundPort` lista **duas** situações em que `send` devolve `False` sem levantar ("Reentrega suprimida" e "Envio barrado pela guarda de opt-out"). Agora são **três**. Acrescente a terceira ao lado das outras duas:

```
    - Envio barrado pela guarda de atendimento humano: um corretor assumiu
      esta conversa e ainda nao a devolveu (TEC-179, RN-16.4) -- ver
      `GuardedOutbound.send` e `esta_silenciada_por_mensagem`. Ao contrario
      da guarda de opt-out, esta nao tem excecao por `kind`.
```

E no parágrafo final do mesmo docstring, que hoje diz que um adaptador escrito direto contra o Protocol *"nao tem a guarda: ele manda mensagem para quem pediu para parar"* — acrescente que ele também fala por cima do corretor que assumiu. **Aquele parágrafo é o aviso de segurança do módulo e ficou incompleto.**

- [ ] **Step 5: Rode e confirme que passa**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_outbound_atendimento.py -v
./.venv/Scripts/python.exe -m pytest tests/unit -q
```
Expected: os novos PASSAM e nenhum unitário existente quebra.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/outbound/port.py tests/unit/test_outbound_atendimento.py
git commit -m "feat(TEC-179): a porta de saida cala o agente na conversa assumida"
```

---

### Task 4: As duas guardas do turno, e os dois desfechos novos

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — o `Literal` `ResultadoDoTurno` (~linha 274), a saída barata (~linha 432, ao lado da de opt-out), o ponto do recheque (~linha 1435), e a função auxiliar ao lado de `_bloqueado_por_optout_concorrente` (~linha 1621)
- Test: `tests/integration/test_turno_atendimento_humano.py`

**Interfaces:**
- Consumes: `esta_silenciada` (Task 2)
- Produces: dois valores novos em `ResultadoDoTurno` — `"atendimento_humano"` e `"bloqueado_por_atendimento_humano"`

**Contexto que você precisa saber:**

**O nome `"silenciado"` JÁ EXISTE e significa opt-out.** Não o reuse, não o generalize. A TEC-182 deixou um comentário no `Literal` explicando por que separou três desfechos em vez de somá-los; leia-o antes de escrever os seus dois, e escreva um comentário do mesmo tipo.

**São dois, e não um**, pela mesma razão que lá são três: `atendimento_humano` é o turno que não fez nada porque a conversa já estava assumida; `bloqueado_por_atendimento_humano` é o turno que tentou responder e a guarda da porta barrou, porque alguém assumiu **entre** a checagem do topo e o envio. Somá-los esconderia quantas vezes a guarda de fato trabalhou.

**O recheque concorrente não é zelo.** `_bloqueado_por_optout_concorrente` existe porque `send()` devolve `False` sem dizer por quê, e agora há **três** causas possíveis. Sem distinguir, um envio barrado pelo silêncio seria logado como "reentrega suprimida" — alarme de dado sumido onde a guarda só fez o trabalho dela.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/integration/test_turno_atendimento_humano.py`.

**Use a fixture `rodar_turno` que já existe** (`tests/conftest.py:481`) — ela semeia a entrada e roda o turno inteiro. Assinatura exata:

```python
await rodar_turno(
    session, classificador, outbound, resumidor, contador,
    moderador=None, agendador=None, *, texto=TEXTO_PADRAO_DO_LEAD,
) -> str
```

Os dublês também já existem como fixtures: `classificador_fake`, `outbound_fake`, `resumidor_fake`, `contador_fake`, `moderador_fake`. Abra `tests/conftest.py` e veja o que cada um expõe (o `outbound_fake` é onde você verifica que nada saiu).

**A armadilha que você precisa conhecer antes de escrever o primeiro teste:** `rodar_turno` chama `executar_turno(get_sessionmaker(), ...)` — **o turno abre sessões próprias**. O `assumir` do seu setup tem de ser **commitado** antes de você chamar `rodar_turno`, ou a guarda não enxerga o estado e o teste falha por um motivo que não é o que ele testa. Se você usar a fixture `session`, chame `await session.commit()` depois do `assumir`.

**Abra também o teste existente de opt-out no turno** (procure por `silenciado_por_optout` em `tests/integration/`) e espelhe o formato das asserções — ele já resolveu como provar "o classificador não foi chamado".

Os três testes a escrever:

```python
async def test_conversa_assumida_o_turno_nao_responde(...):
    """Primeiro cenario do Gherkin. O desfecho e `atendimento_humano`."""
    # assumir a conversa, rodar o turno, assertar:
    #   resultado == "atendimento_humano"
    #   o dublê de outbound NAO recebeu nada
    #   o classificador NAO foi chamado -- a saida e ANTES do modelo, e isso
    #   e o que faz a guarda ser barata


async def test_a_mensagem_do_lead_continua_registrada(...):
    """Segundo cenario do Gherkin -- e ele passa SEM codigo novo.

    A mensagem e gravada pelo webhook, que commita o lote antes sequer de
    enfileirar o job (`api/routes/whatsapp.py`); o `process_message` so
    reivindica a linha e a le. Quando `executar_turno` roda, o registro ja
    esta commitado -- a saida antecipada nao tem como alcanca-lo.

    Este teste existe para provar que continua assim, nao para construir
    nada. Se ele algum dia reprovar, alguem moveu o registro para depois do
    turno e o silencio passou a comer mensagem do lead.
    """


async def test_devolvida_o_turno_volta_a_responder(...):
    """Prova que a guarda le o estado CORRENTE."""
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_atendimento_humano.py -v`
Expected: FALHA — o turno responde normalmente.

- [ ] **Step 3: Acrescente os dois desfechos ao `Literal`**

Em `src/mobia/domain/agente/turno.py`, no `ResultadoDoTurno` (~linha 274), depois de `"bloqueado_por_optout",`:

```python
    # A TEC-179 acrescentou os dois abaixo, separados pelo mesmo criterio que
    # o comentario acima aplica aos tres do opt-out:
    # "atendimento_humano" e o turno que nao fez nada porque um corretor ja
    # tinha assumido a conversa; "bloqueado_por_atendimento_humano" e o turno
    # que tentou responder e a guarda da porta barrou, porque alguem assumiu
    # ENTRE a checagem do topo deste turno e este envio.
    #
    # Nao reuse "silenciado": aquele valor ja significa opt-out, e soma-los
    # tornaria impossivel saber se o agente calou por pedido do lead ou por
    # um corretor ter assumido -- duas historias diferentes, com donos
    # diferentes.
    "atendimento_humano",
    "bloqueado_por_atendimento_humano",
```

- [ ] **Step 4: Acrescente a saída barata**

Logo **depois** do bloco `if not pedido_de_optout:` que checa `esta_em_optout` (~linha 432-442):

```python
    # A guarda de atendimento humano (TEC-179, RN-16.4). Depois da de opt-out
    # e nao antes: o opt-out e direito do lead e vence tudo, inclusive um
    # corretor que tenha assumido.
    #
    # Barata de proposito -- antes do classificador, entao um turno silenciado
    # nao paga chamada ao modelo. A guarda autoritativa e a da porta de saida
    # (`outbound/port.py`); esta so evita o trabalho.
    async with session_factory() as sessao:
        if await esta_silenciada(
            sessao, channel=message.channel, conversation_key=message.conversation_key
        ):
            log.info(
                "turno.atendimento_humano",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "atendimento_humano"
```

E o import no topo:

```python
from mobia.domain.atendimento.repositorio import esta_silenciada
```

- [ ] **Step 5: Escreva a função do recheque concorrente**

Ao lado de `_bloqueado_por_optout_concorrente` (~linha 1621):

```python
async def _bloqueado_por_atendimento_humano_concorrente(
    session_factory: async_sessionmaker[AsyncSession], message: Message
) -> bool:
    """A terceira causa de `outbound.send` devolver False sem levantar.

    `OutboundPort.send` documenta que o retorno booleano nao distingue
    reentrega suprimida, opt-out concorrente e atendimento humano
    concorrente. Sem esta consulta, um envio barrado porque o corretor
    assumiu no meio do turno seria logado como reentrega suprimida -- alarme
    de dado sumido onde a guarda so fez o trabalho dela.

    Best-effort pelo mesmo argumento de `_bloqueado_por_optout_concorrente`:
    entre o `send()` e esta consulta o estado ainda pode mudar (uma devolucao,
    por exemplo). Isso so muda qual historia o log conta -- em nenhum dos dois
    casos ha texto reenviado ou dado perdido.
    """
    async with session_factory() as sessao:
        return await esta_silenciada(
            sessao, channel=message.channel, conversation_key=message.conversation_key
        )
```

- [ ] **Step 6: Encadeie o recheque nos dois sítios que já chamam o de opt-out**

Procure por `_bloqueado_por_optout_concorrente(` em `turno.py` — há **duas** chamadas (~linhas 1435 e 1494). Em cada uma, acrescente o novo teste no `elif`, **depois** do de opt-out (o opt-out vence, mesma ordem da saída barata):

```python
        if await _bloqueado_por_optout_concorrente(session_factory, message):
            ...  # o bloco que ja existe, intocado
            return "bloqueado_por_optout"
        if await _bloqueado_por_atendimento_humano_concorrente(session_factory, message):
            log.info(
                "turno.bloqueado_por_atendimento_humano_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_atendimento_humano"
```

**Leia o contexto real de cada um dos dois sítios antes de editar** — o segundo (~linha 1494) está dentro da lógica de supressão parcial de fichas e usa `desfecho_da_supressao_parcial`, não um `return` direto. Espelhe o que o de opt-out faz **naquele** sítio, não o que faz no primeiro.

- [ ] **Step 7: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_atendimento_humano.py -v
./.venv/Scripts/python.exe -m pytest tests/integration -k turno -q
```
Expected: os novos PASSAM e nenhum teste de turno existente quebra.

- [ ] **Step 8: Orçamento do prompt**

Run: `./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s`
Expected: PASSA. Esta card não toca `SISTEMA_DO_AGENTE`, então o teto não deve se mexer. **Se reprovar, pare** — algo entrou no prompt sem querer.

- [ ] **Step 9: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/agente/turno.py tests/integration/test_turno_atendimento_humano.py
git commit -m "feat(TEC-179): o turno cala quando um corretor assumiu, e diz por que"
```

---

### Task 5: A guarda das automações

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_followups.py` — ao lado do `esta_em_optout` (~linha 182)
- Test: `tests/integration/test_sweep_followups.py` (acrescentar; **não** criar arquivo novo se já existir)

**Interfaces:**
- Consumes: `esta_silenciada` (Task 2)
- Produces: nada novo

**Contexto que você precisa saber:**

É o terceiro cenário do Gherkin: *"Dada uma conversa silenciada e um follow-up agendado para ela, quando o horário do disparo chega, então nenhuma mensagem automática é enviada."*

O `sweep_followups` já tem a checagem de opt-out no mesmo laço. A de silêncio vai **ao lado**, com o mesmo formato (`continue`).

Repare que a guarda da porta (Task 3) já barraria o envio — mas ela barra **depois** de o follow-up ser registrado em `followups`, que é append-only. Sem a guarda aqui, uma conversa silenciada acumularia tentativas registradas que nunca saíram, e o antispam da RN-13.1 contaria essas tentativas fantasma contra o lead quando a conversa fosse devolvida.

- [ ] **Step 1: Escreva o teste que falha**

Abra `tests/integration/test_sweep_followups.py`, encontre o teste que prova que **opt-out** impede o follow-up, e escreva o gêmeo dele para silêncio. Copie a montagem daquele teste — ele já sabe criar o candidato e fazer o sweep encontrar.

A asserção tem de ser sobre **duas** coisas, não uma: nenhum evento devolvido **e** nenhuma linha nova em `followups`. Só a primeira passaria mesmo se a guarda estivesse no lugar errado.

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -v -k atendimento`
Expected: FALHA — o follow-up é registrado.

- [ ] **Step 3: Acrescente a guarda**

Em `src/mobia/workers/jobs/sweep_followups.py`, logo **depois** do bloco `if await esta_em_optout(...): continue`:

```python
            # TEC-179, RN-16.4: nenhuma automacao dispara em conversa que um
            # corretor assumiu. A guarda da porta de saida (`outbound/port.py`)
            # barraria o envio de qualquer jeito, mas so DEPOIS de esta funcao
            # registrar a tentativa em `followups`, que e append-only. Sem a
            # checagem aqui, uma conversa silenciada acumularia tentativas que
            # nunca sairam, e o antispam da RN-13.1 as contaria contra o lead
            # quando a conversa fosse devolvida.
            if await esta_silenciada(
                session,
                channel=candidato.channel,
                conversation_key=candidato.conversation_key,
            ):
                continue
```

E o import no topo, ao lado do de opt-out.

- [ ] **Step 4: Rode**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_followups.py -v`
Expected: todos PASSAM, incluindo os que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/workers/jobs/sweep_followups.py tests/integration/test_sweep_followups.py
git commit -m "feat(TEC-179): nenhuma automacao dispara em conversa assumida"
```

---

### Task 6: As duas rotas, e o aceite do handoff junto

**Files:**
- Create: `src/mobia/api/routes/conversas.py`
- Modify: `src/mobia/app/main.py` — dentro de `create_app()`, no bloco `if settings.catalogo_admin_token:` (linhas 36-45)
- Test: `tests/integration/test_rota_de_conversas.py`

**Interfaces:**
- Consumes: `assumir`, `devolver`, `Atendimento` (Task 2); `exigir_admin` de `mobia.api.deps`; `Corretor`; `Handoff` e `Status` de `mobia.domain.handoff`
- Produces: `POST /api/v1/conversas/assumir` e `POST /api/v1/conversas/devolver`

**Contexto que você precisa saber:**

**As rotas NÃO recebem `conversaId`.** O SRS escreve `/conversas/{conversaId}` e não existe `conversaId` neste sistema — a conversa é o par `(channel, conversation_key)`. É a D9 do desenho e vira emenda (Task 7). O par vai no corpo, junto com o `corretor_id`.

**A guarda é `exigir_admin`** (`src/mobia/api/deps.py`), a única que existe. O `corretor_id` vem no corpo e é validado contra `corretores` — tem de existir **e** estar `ativo`. É a D2 do desenho, e o custo está declarado: quem tem o token pode assumir em nome de qualquer corretor.

**Assumir aceita o handoff pendente da mesma conversa (D6).** Na mesma transação: se a conversa tem handoff em `PENDENTE` ou `ESCALADO`, ele vira `ACEITO` com `aceito_em` carimbado. Os dois estados, pelo mesmo argumento da Emenda E-01 da seção 6.5 — assumir depois da escalada é o caso real.

**Abra `src/mobia/api/routes/handoffs.py` e leia a rota `aceitar` inteira antes de escrever.** O `UPDATE ... RETURNING` dela é o molde exato, inclusive o `_ACEITAVEIS`. Reuse a constante se ela for importável; se não, repita o valor e **escreva um comentário dizendo que as duas listas têm de andar juntas**.

**Modelo Pydantic: nada de `assert`.** Um `assert` dentro de `model_validator` some sob `python -O`. Use `ValueError`.

- [ ] **Step 1: Escreva os testes que falham**

Crie `tests/integration/test_rota_de_conversas.py`. Copie a montagem de `tests/integration/test_rota_de_aceite.py` (a fixture `app_com_token` e o cliente). Os testes:

```python
async def test_assumir_silencia_e_devolve_200(...): ...
async def test_assumir_sem_token_e_403(...): ...
async def test_assumir_com_corretor_inexistente_e_404(...): ...
async def test_assumir_com_corretor_inativo_e_recusado(...): ...
async def test_outro_corretor_recebe_409(...): ...
async def test_reassumir_pela_mesma_pessoa_e_200_e_nao_move_o_carimbo(...): ...
async def test_devolver_reativa_o_agente(...): ...
async def test_devolver_o_que_ninguem_assumiu_e_409(...): ...

async def test_assumir_aceita_o_handoff_pendente_junto(...):
    """D6. Sem isto o corretor atende e a gerente e cobrada ao mesmo tempo.

    Crie um handoff PENDENTE para a conversa, assuma, e assere que ele ficou
    ACEITO com `aceito_em` preenchido.
    """

async def test_assumir_aceita_tambem_o_handoff_ja_escalado(...):
    """Mesmo argumento da Emenda E-01 da secao 6.5: assumir depois da
    escalada e o caso real, porque a escalada existe para alguem pegar."""

async def test_assumir_sem_handoff_nenhum_funciona(...):
    """Nem toda conversa gerou handoff. Assumir nao pode exigir um."""

async def test_handoff_aceito_ao_assumir_para_de_ser_varrido(...):
    """A prova de que a D6 fecha o buraco que ela promete fechar: um handoff
    com prazo vencido, aceito por ter sido assumido, deixa de ser escalado
    por `escalar_vencidos`."""
```

- [ ] **Step 2: Rode e confirme que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_conversas.py -v`
Expected: FALHA — 404, a rota não existe.

- [ ] **Step 3: Escreva as rotas**

`src/mobia/api/routes/conversas.py`. Estrutura obrigatória:

- `router = APIRouter(prefix="/api/v1/conversas", tags=["conversas"])` — **confira o prefixo real** que `handoffs.py` e `corretores.py` usam e siga o mesmo padrão.
- Um modelo Pydantic `PedidoDeAtendimento` com `channel: str`, `conversation_key: str`, `corretor_id: uuid.UUID`.
- `POST /assumir` e `POST /devolver`, ambas com `_: None = Depends(exigir_admin)`.
- Em `assumir`: validar o corretor (`SELECT` em `corretores` com `ativo`), chamar `assumir` do repositório, e se valeu, rodar o `UPDATE` do handoff. `commit` uma vez, no fim.
- Resposta de `assumir`, espelhando o que o SRS especifica: `{"status": "SILENCIADA", "assumidoPor": str(...), "assumidoEm": ...isoformat()}`.
- `None` do repositório vira `409`. Corretor inexistente ou inativo vira `404`.

Escreva no docstring da rota **por que** o `corretor_id` vem no corpo: é a D2, não há identidade autenticada, e o `corretor_id` é afirmação de quem chama e não identidade provada.

- [ ] **Step 4: Registre o router**

Em `src/mobia/app/main.py`, dentro de `create_app()`. O bloco existente é:

```python
    # Sem token configurado os routers NAO entram no app. Nao e 401: rota que
    # nao existe nao pode ser exposta por engano de configuracao, e este
    # projeto ainda nao tem camada de autenticacao. Ver D1 do desenho da
    # TEC-156.
    if settings.catalogo_admin_token:
        from mobia.api.routes.corretores import router as corretores_router
        from mobia.api.routes.handoffs import router as handoffs_router
        from mobia.api.routes.imoveis import router as imoveis_router

        app.include_router(imoveis_router)
        app.include_router(corretores_router)
        app.include_router(handoffs_router)
```

Acrescente `conversas` **dentro do mesmo `if`** — o import e o `include_router`. Sem token configurado a rota não pode existir: com esta card ela governa quem fala com qual lead, então o argumento da TEC-156 vale com mais força aqui, não menos.

Isso significa que o teste de "sem token, 404 e não 403" (procure o equivalente para `handoffs` ou `corretores` em `tests/integration/`) precisa do gêmeo para `conversas`.

- [ ] **Step 5: Rode**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_conversas.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_rota_de_aceite.py tests/integration/test_escalada_de_sla.py -v
```
Expected: todos PASSAM. Os dois últimos porque a D6 acrescentou um segundo escritor de `Status.ACEITO`.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
git add src/mobia/api/routes/conversas.py tests/integration/test_rota_de_conversas.py src/mobia/app/main.py
git commit -m "feat(TEC-179): assumir a conversa cala o agente e aceita o handoff junto"
```

---

### Task 7: As emendas ao SRS e o fechamento

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1: Escreva as três emendas**

**Nunca reescreva o texto de 22/08/2026.** Cada emenda é um item aninhado abaixo da regra que altera. Localize as regras por `grep -n "RN-16.4" docs/srs/srs-agente-sdr-imobiliario-v1.0.md` e a seção 6.2 pela rota `assumir`.

1. **Abaixo da RN-16.4** — `Emenda E-01 (TEC-179, 13/09/2026)`: o autor de assumir e devolver é um `corretor_id` **informado no corpo** e guardado pelo `X-Admin-Token`, e não a identidade autenticada que o SRS pressupõe (`Bearer JWT`, papel `CORRETOR`). É **afirmação de quem chama, não identidade provada**: quem tem o token pode assumir em nome de qualquer corretor, e devolver a conversa que outro assumiu. Fechar é a TEC-201.

2. **Abaixo da RN-16.4** — `Emenda E-02 (TEC-179, 13/09/2026)`: assumir a conversa **aceita junto** o handoff `PENDENTE` ou `ESCALADO` da mesma conversa, carimbando `aceito_em`. Sem isso o corretor atende e a gerente é cobrada pelo mesmo lead quinze minutos depois. `ESCALADO` entra pelo mesmo argumento da Emenda E-01 da seção 6.5.

3. **Abaixo da rota `POST /conversas/{conversaId}/assumir`, na seção 6.2** — `Emenda E-01 (TEC-179, 13/09/2026)`: passa a existir `POST /api/v1/conversas/devolver`, que o texto original não previa e a RN-16.4 exige ("até ser reativado"). E **as duas rotas endereçam a conversa pelo par `(channel, conversation_key)` no corpo**, não por um `{conversaId}` — não existe entidade conversa neste sistema, e inventá-la numa card de silenciamento seria desenhar o modelo de dados de meio sistema. Autenticação: `X-Admin-Token`, ver a Emenda E-01 da RN-16.4.

- [ ] **Step 2: A suíte inteira, UMA vez**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`
Expected: tudo verde. **Guarde o hash junto com o resultado.**

Se falhar, rode **de novo sobre a mesma árvore** antes de culpar sua mudança — é a única coisa que separa flake de regressão. E se aparecerem dezenas de `relation ... does not exist`, leia a seção do CLAUDE.md sobre os bancos dos workers com o carimbo adiantado: isso **repete idêntico** na segunda execução e não é a sua migration.

- [ ] **Step 3: Comentários tocados, e a busca à mão**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

**Esta branch muda um contrato e a ferramenta não vê fora do diff.** Procure à mão quem descreve o que mudou:

- o docstring de `OutboundPort` que lista as causas de `send` devolver `False` — eram duas, são três (Task 3 já deve ter tratado; **confirme**)
- qualquer comentário que diga que `esta_em_optout` é a **única** guarda da porta, ou que o opt-out é o único motivo de o agente calar
- qualquer texto que afirme que nada tira handoff de `PENDENTE` além da rota de aceite — agora assumir também tira
- o comentário do `Literal` `ResultadoDoTurno` que diz "a TEC-182 acrescentou os três abaixo", se ele sugerir que são os últimos

- [ ] **Step 4: Os três gates e `alembic heads`**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy src
./.venv/Scripts/python.exe -m alembic heads
```
Expected: três verdes, e **uma só cabeça** (`0029`).

- [ ] **Step 5: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "docs(TEC-179): tres emendas -- o autor informado, o aceite junto e a rota de devolver"
```

---

## Autorrevisão do plano

**Cobertura da spec:** D1 → Task 1. D2 → Tasks 6 e 7. D3 → Task 2. D4 → Tasks 1 e 2. D5 → Tasks 3, 4 e 5 (os quatro sítios: turno barato e recheque na 4, porta na 3, sweep na 5). D6 → Task 6. D7 → Tasks 6 e 7. D8 → Task 4. D9 → Tasks 6 e 7. L1–L4 → declaradas; sem task, por construção.

**Consistência de tipos:** `AtendimentoHumano` na Task 1, usado na 2; `esta_silenciada` e `esta_silenciada_por_mensagem` na Task 2, usadas na 3, 4 e 5; `assumir`/`devolver`/`Atendimento` na Task 2, usados na 6. O `Atendimento` expõe `assumido_por` e `assumido_em`, que é exatamente o que a resposta da rota precisa.

**Ordem:** a porta (Task 3) vem antes do turno (Task 4) de propósito — o recheque concorrente da 4 existe para explicar um `False` que só a guarda da 3 produz. Inverter deixaria a Task 4 escrevendo uma função sem causa possível.

**Três pontos que o executor decide e registra:** se a resposta de `devolver` inclui quem devolveu ou só confirma; se `assumir` deve recusar conversa em opt-out (o desenho não decide, e há argumento dos dois lados — assumir não envia nada, mas silenciar uma conversa que já não recebe mensagem é estado sem efeito); e se o `_ACEITAVEIS` de `handoffs.py` é importável ou tem de ser repetido.

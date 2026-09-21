# TEC-223 — CHECK no vocabulário de `messages`: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o banco recusar uma grafia fora do vocabulário nas quatro colunas de enum de `messages`, em vez de aceitá-la em silêncio.

**Architecture:** Uma migration `0037` acrescenta quatro `CHECK` — `role`, `direction`, `content_type` e `status` — por `op.create_check_constraint`, com o `downgrade` simétrico. As mesmas quatro entram no `__table_args__` do modelo, como os outros oito CHECKs do repo. Um teste lê `pg_constraint` e amarra cada constraint ao enum correspondente nos dois sentidos, para as duas cópias nunca divergirem em silêncio.

**Tech Stack:** Python 3.13, SQLAlchemy async, Alembic, Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-223-check-no-vocabulario-de-messages-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceção: valor citado que o usuário recebe segue o literal.
- **Prosa em `docs/` e `.md`: com acento.**
- **Mensagem de commit:** português sem acento no assunto, formato `tipo(TEC-223): o que passou a ser verdade`, com linha em branco antes do trailer.
- **Os três gates, com o escopo exato, antes de qualquer commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter. **`mypy` roda sem argumento** e cobre `alembic` — a migration passa por ele.
- **Os quatro vocabulários, valores exatos** (de `src/mobia/domain/messages/enums.py` e `status.py`, todos `StrEnum` com nome igual ao valor):
  - `role`: `LEAD`, `AGENTE`, `CORRETOR`, `SISTEMA`
  - `direction`: `INBOUND`, `OUTBOUND`
  - `content_type`: `TEXTO`, `AUDIO`, `IMAGEM`, `DOCUMENTO`, `DESCONHECIDO`
  - `status`: `RECEIVED`, `QUEUED`, `PROCESSING`, `PROCESSED`, `FAILED`, **mais `NULL`**, que é valor legítimo e ativamente gravado por `recorder.py:128`
- **A classe do content type chama-se `MessageContentType`**, não `ContentType`. E **`MessageStatus` mora em `status.py`**, não em `enums.py`.
- **Estas tarefas exigem `docker compose` de pé** — são testes de integração e migration. `tests/unit` sozinho não cobre nada aqui.
- **Head do Alembic é `0036`.** A nova revisão é `0037`, com `down_revision = "0036"`.
- **Comentário desatualizado é defeito**, não sujeira.

---

### Task 1: A migration `0037` e a prova de que a constraint morde

**Files:**
- Create: `alembic/versions/0037_check_no_vocabulario_de_messages.py`
- Create: `tests/integration/test_messages_schema.py`
- Modify: `tests/integration/test_migrations.py` (acrescenta um round-trip ao fim)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: as quatro constraints existem no banco, com estes nomes exatos — `ck_messages_role`, `ck_messages_direction`, `ck_messages_content_type`, `ck_messages_status`. A Task 2 lê esses nomes do catálogo; a Task 3 os repete no modelo.

- [ ] **Step 1: Escrever os testes de comportamento, que falham**

Criar `tests/integration/test_messages_schema.py`, seguindo a forma de
`tests/integration/test_corretores_schema.py` — que é o precedente do repo para provar que um
CHECK recusa (`session.add(...)` + `pytest.raises(IntegrityError, match="ck_...")` + `commit()`):

```python
"""O vocabulario fechado de `messages` e garantido pelo banco, nao so pelo enum.

Os dois escritores de hoje passam pelos enums, entao isto e defesa em
profundidade -- para o terceiro escritor, que a TEC-124 traz com o canal web e
que vai gravar sem passar pelo parser da Meta. Duas garantias do sistema
comparam literal em SQL cru (`sweep_stalled.py` e a ancora de
`followup/repositorio.py`), e uma linha com grafia divergente as burla em
silencio.

Os testes montam o `Message` pelo ORM de proposito: nenhuma das quatro colunas
tem validador, entao o ORM aceita a grafia errada de bom grado -- e e
exatamente por isso que a garantia precisa estar no banco.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message


def _mensagem(**sobrescritas: object) -> Message:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": "whatsapp",
        "provider_message_id": f"wamid.{uuid.uuid4()}",
        "sender_external_id": "5511900000000",
        "recipient_external_id": "5511000000000",
        "conversation_key": "whatsapp:5511900000000",
        "role": "LEAD",
        "direction": "INBOUND",
        "content_type": "TEXTO",
        "status": "RECEIVED",
    }
    campos.update(sobrescritas)
    return Message(**campos)


@pytest.mark.parametrize(
    ("coluna", "valor"),
    [
        ("role", "lead"),
        ("role", "COMPRADOR"),
        ("direction", "inbound"),
        ("direction", "ENTRADA"),
        ("content_type", "text"),
        ("content_type", "TEXT"),
        ("status", "received"),
        ("status", "PENDENTE"),
    ],
)
async def test_grafia_fora_do_vocabulario_e_recusada(
    session: AsyncSession, coluna: str, valor: str
) -> None:
    """`'inbound'` e o caso que motivou a card: o sweeper filtra por 'INBOUND'.

    Uma linha com a grafia minuscula seria varrida, e a fala do proprio agente
    voltaria para `process_message`, que emitiria efeito externo por uma
    mensagem que ninguem enviou.
    """
    session.add(_mensagem(**{coluna: valor}))
    with pytest.raises(IntegrityError, match=f"ck_messages_{coluna}"):
        await session.commit()


@pytest.mark.parametrize("valor", ["LEAD", "AGENTE", "CORRETOR", "SISTEMA"])
async def test_todo_role_legitimo_passa(session: AsyncSession, valor: str) -> None:
    """Inclui CORRETOR e SISTEMA, que nenhum codigo grava hoje: o CHECK espelha
    o enum, e recusar um membro dele seria recusar por engano."""
    session.add(_mensagem(role=valor))
    await session.commit()


@pytest.mark.parametrize("valor", ["INBOUND", "OUTBOUND"])
async def test_toda_direction_legitima_passa(session: AsyncSession, valor: str) -> None:
    session.add(_mensagem(direction=valor))
    await session.commit()


@pytest.mark.parametrize("valor", ["TEXTO", "AUDIO", "IMAGEM", "DOCUMENTO", "DESCONHECIDO"])
async def test_todo_content_type_legitimo_passa(session: AsyncSession, valor: str) -> None:
    """`DESCONHECIDO` e o que `content_type_da_meta` devolve para tipo que nao
    conhecemos, entao e o valor mais provavel de aparecer em producao."""
    session.add(_mensagem(content_type=valor))
    await session.commit()


@pytest.mark.parametrize("valor", ["RECEIVED", "QUEUED", "PROCESSING", "PROCESSED", "FAILED"])
async def test_todo_status_legitimo_passa(session: AsyncSession, valor: str) -> None:
    session.add(_mensagem(status=valor))
    await session.commit()


async def test_status_nulo_continua_passando(session: AsyncSession) -> None:
    """NULL em `status` e semantico, nao ausencia de dado: e o que a linha de
    SAIDA grava (`recorder.py`), e significa "nao participa do pipeline de
    ingestao". Um CHECK que o recusasse quebraria toda mensagem do agente.
    """
    session.add(_mensagem(status=None))
    await session.commit()
```

- [ ] **Step 2: Rodar e ver falhar**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_messages_schema.py --tb=short
```

Esperado: os oito casos de `test_grafia_fora_do_vocabulario_e_recusada` **falham**, porque nenhuma constraint existe ainda e o INSERT passa — `pytest.raises(IntegrityError)` não vê exceção nenhuma. Os testes de valores legítimos passam desde já; eles são a rede que pega um CHECK escrito estrito demais.

- [ ] **Step 3: Escrever a migration**

Criar `alembic/versions/0037_check_no_vocabulario_de_messages.py`:

```python
"""o vocabulario de role, direction, content_type e status vira CHECK

TEC-223.

As quatro colunas sao `String` livre desde a TEC-126: o vocabulario vivia so
nos enums Python. Duas garantias do sistema comparam literal em SQL cru --
`WHERE direction = 'INBOUND'` no sweeper e na ancora do follow-up --, e uma
linha gravada como `'inbound'` as burla em silencio: ela seria varrida, e a
fala do proprio agente voltaria para `process_message`, que emitiria efeito
externo por uma mensagem que ninguem enviou.

Hoje ha dois escritores e ambos passam pelos enums. Isto e para o terceiro,
que a TEC-124 traz com o canal web.

`status` admite NULL, e isso e deliberado: NULL significa "nao participa do
pipeline de ingestao" e e o que a linha de saida grava. O `IS NULL` explicito
e redundante -- `IN` com NULL da UNKNOWN, que nao viola CHECK -- e esta ali
para dizer que o NULL e permitido de proposito.

Revision ID: 0037
Revises: 0036
"""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_messages_role",
        "messages",
        "role IN ('LEAD', 'AGENTE', 'CORRETOR', 'SISTEMA')",
    )
    op.create_check_constraint(
        "ck_messages_direction",
        "messages",
        "direction IN ('INBOUND', 'OUTBOUND')",
    )
    op.create_check_constraint(
        "ck_messages_content_type",
        "messages",
        "content_type IN ('TEXTO', 'AUDIO', 'IMAGEM', 'DOCUMENTO', 'DESCONHECIDO')",
    )
    op.create_check_constraint(
        "ck_messages_status",
        "messages",
        "status IS NULL OR status IN "
        "('RECEIVED', 'QUEUED', 'PROCESSING', 'PROCESSED', 'FAILED')",
    )


def downgrade() -> None:
    # Ordem inversa da criacao, como a 0014 faz.
    op.drop_constraint("ck_messages_status", "messages")
    op.drop_constraint("ck_messages_content_type", "messages")
    op.drop_constraint("ck_messages_direction", "messages")
    op.drop_constraint("ck_messages_role", "messages")
```

- [ ] **Step 4: Aplicar a migration e rodar os testes**

```
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_messages_schema.py --tb=short
```

Esperado: tudo passa.

Se o `alembic upgrade head` **reprovar** com violação de CHECK, não conserte a constraint: significa que o banco local já tem linha com valor fora do vocabulário. Isso é achado, não obstáculo — descubra qual linha (`SELECT DISTINCT role, direction, content_type, status FROM messages`) e relate, porque um valor divergente já gravado é a própria tese da card confirmada.

- [ ] **Step 5: Escrever o round-trip da migration**

O round-trip não é ritual: a docstring de `test_a_0035_desce_e_sobe_de_novo` (`tests/integration/test_migrations.py:296-299`) registra a razão da casa — objeto que nasce fora do autogenerate pode sobreviver órfão ao downgrade e fazer o **upgrade seguinte** reprovar com "already exists", num banco de desenvolvimento que já subiu e desceu a revisão. Um `CheckConstraint` criado por `op.create_check_constraint` é exatamente esse caso.

Acrescentar ao fim de `tests/integration/test_migrations.py`, seguindo o molde de `test_a_0013_desce_e_sobe_de_novo` (`:258-289`):

```python
_CONSTRAINTS_DA_0037 = (
    "ck_messages_role",
    "ck_messages_direction",
    "ck_messages_content_type",
    "ck_messages_status",
)

_CONTAR_CONSTRAINTS = text(
    "SELECT count(*) FROM pg_constraint WHERE conname = ANY(:nomes) AND contype = 'c'"
)


async def test_a_0037_desce_e_sobe_de_novo() -> None:
    """As quatro constraints somem no downgrade e voltam no upgrade.

    Mesma razao do teste da 0035 acima: elas nascem de `op.create_check_
    constraint`, nao do autogenerate, entao nada garante que o downgrade as
    derrube. Uma constraint orfa faz o upgrade SEGUINTE reprovar com "already
    exists" -- num banco de desenvolvimento que ja subiu e desceu esta
    revisao, e nao no CI, que sempre parte do zero.
    """
    await dispose_engine()
    alembic("downgrade", "0036")
    try:
        async with get_sessionmaker()() as sessao:
            assert (
                await sessao.scalar(_CONTAR_CONSTRAINTS, {"nomes": list(_CONSTRAINTS_DA_0037)})
            ) == 0
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    async with get_sessionmaker()() as sessao:
        assert (
            await sessao.scalar(_CONTAR_CONSTRAINTS, {"nomes": list(_CONSTRAINTS_DA_0037)})
        ) == 4
```

- [ ] **Step 6: Rodar o round-trip**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py --tb=short
```

Esperado: todos passam, inclusive os quatro que já existiam. Rode o arquivo inteiro, não só o teste novo: ele mexe no esquema do banco compartilhado, e os outros round-trips são quem pega uma interferência.

- [ ] **Step 7: Rodar os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/0037_check_no_vocabulario_de_messages.py tests/integration/test_messages_schema.py tests/integration/test_migrations.py
git commit -m "feat(TEC-223): o banco recusa grafia fora do vocabulario em messages"
```

---

### Task 2: A amarra que impede o enum e a constraint de divergirem

Sem ela esta card tem prazo de validade: alguém acrescenta um membro ao enum, a suíte passa inteira, e o banco recusa em produção. O precedente é `tests/integration/test_corretores_schema.py:190-203`, que faz isso para `ck_corretores_especialidades` — **mas só num sentido**, conferindo que todo valor do enum aparece na cláusula. Esta tarefa cobre os dois.

**Files:**
- Modify: `tests/integration/test_messages_schema.py` (acrescenta ao fim)

**Interfaces:**
- Consumes: os quatro nomes de constraint da Task 1.
- Produces: nada que tarefas seguintes usem.

- [ ] **Step 1: Escrever o teste**

O formato que o Postgres devolve foi medido, não suposto — ele normaliza `IN (...)` para `= ANY (ARRAY[...])` e anota o tipo em cada literal:

```
ck_messages_direction => CHECK (((direction)::text = ANY ((ARRAY['INBOUND'::character varying, 'OUTBOUND'::character varying])::text[])))
ck_messages_status    => CHECK (((status IS NULL) OR ((status)::text = ANY ((ARRAY['RECEIVED'::character varying, ...])::text[]))))
```

Por isso a extração é por `'([^']+)'::character varying`, e não por aspas soltas.

Acrescentar ao fim de `tests/integration/test_messages_schema.py` (os imports `re` e os quatro enums vão para o topo do arquivo):

```python
_VOCABULARIOS = (
    ("ck_messages_role", MessageRole),
    ("ck_messages_direction", MessageDirection),
    ("ck_messages_content_type", MessageContentType),
    ("ck_messages_status", MessageStatus),
)

# O Postgres reescreve `IN (...)` como `= ANY (ARRAY[...])` e anota o tipo em
# cada literal. Medido contra o banco, nao suposto.
_LITERAL_DO_CHECK = re.compile(r"'([^']+)'::character varying")


@pytest.mark.parametrize(("constraint", "enum"), _VOCABULARIOS)
async def test_o_check_e_o_enum_dizem_a_mesma_coisa(
    session: AsyncSession, constraint: str, enum: type[StrEnum]
) -> None:
    """O vocabulario mora em dois lugares, e eles tem de coincidir.

    Sem esta amarra, acrescentar um membro ao enum e esquecer a migration
    produz `IntegrityError` em producao e silencio na suite -- nenhum teste em
    Python veria a lista do CHECK ficar para tras. E o inverso tambem: um valor
    que saiu do enum e ficou no CHECK deixa o banco aceitando o que o codigo
    ja nao produz.

    Mesma ideia de `test_check_de_especialidades_cobre_todo_o_enum` em
    `test_corretores_schema.py`, nos DOIS sentidos em vez de um.
    """
    clausula = await session.scalar(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :nome"),
        {"nome": constraint},
    )
    assert clausula is not None, f"{constraint} nao existe no banco"

    no_check = set(_LITERAL_DO_CHECK.findall(clausula))
    no_enum = {membro.value for membro in enum}

    assert no_check == no_enum, (
        f"{constraint}: no enum e nao no CHECK = {sorted(no_enum - no_check)}; "
        f"no CHECK e nao no enum = {sorted(no_check - no_enum)}"
    )
```

Imports a acrescentar no topo do arquivo: `import re`, `from enum import StrEnum`, `from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole` e `from mobia.domain.messages.status import MessageStatus`.

- [ ] **Step 2: Rodar e ver passar**

```
./.venv/Scripts/python.exe -m pytest tests/integration/test_messages_schema.py --tb=short
```

Esperado: os quatro casos passam. Este teste nasce verde de propósito — ele não prova código novo, prova que duas listas coincidem, e o valor dele é o dia em que deixarem de coincidir.

- [ ] **Step 3: Provar que a amarra morde**

Um teste que nasce verde precisa ser visto falhando, senão não se sabe se ele olha para alguma coisa. Acrescente temporariamente um membro a `MessageDirection` em `src/mobia/domain/messages/enums.py`:

```python
    LATERAL = "LATERAL"
```

Rode `./.venv/Scripts/python.exe -m pytest tests/integration/test_messages_schema.py -k check_e_o_enum --tb=short`.

Esperado: `test_o_check_e_o_enum_dizem_a_mesma_coisa[ck_messages_direction-MessageDirection]` **falha**, e a mensagem nomeia `no enum e nao no CHECK = ['LATERAL']`.

**Remova o membro em seguida** e rode de novo para confirmar que voltou ao verde. Registre no relatório a saída literal da falha — é a evidência de que a amarra funciona.

- [ ] **Step 4: Rodar os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Confirme que `git status` não mostra `enums.py` modificado antes de commitar.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_messages_schema.py
git commit -m "test(TEC-223): o CHECK e o enum ficam amarrados nos dois sentidos"
```

---

### Task 3: As constraints também no modelo

**Files:**
- Modify: `src/mobia/domain/messages/models.py` (o import de `sqlalchemy` nas linhas 5-17, e o `__table_args__` nas linhas 155-175)

**Interfaces:**
- Consumes: os quatro nomes e as quatro expressões da Task 1 — **idênticos, caractere por caractere**.
- Produces: nada.

Oito dos doze CHECKs do repo vivem no modelo e na migration; quatro vivem só na migration. Esta card fica com os oito, porque `messages` é a tabela mais lida do repo e o modelo é onde alguém procura o que a coluna aceita. Nada no esquema de teste depende desta cópia — as fixtures sobem por `alembic upgrade`, não por `create_all`.

- [ ] **Step 1: Acrescentar o import**

Em `src/mobia/domain/messages/models.py`, o bloco de import de `sqlalchemy` (linhas 5-17) ganha `CheckConstraint`, em ordem alfabética — ele vem **antes** de `DateTime`:

```python
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
```

- [ ] **Step 2: Acrescentar as quatro constraints ao `__table_args__`**

No fim da tupla `__table_args__`, depois do `UniqueConstraint` que a fecha hoje:

```python
        # O vocabulario fechado, guardado no banco e nao so no enum (TEC-223).
        # `sweep_stalled.py` e a ancora de `followup/repositorio.py` filtram por
        # literal em SQL cru, entao uma linha gravada como `'inbound'` burla as
        # duas em silencio -- e seria varrida, devolvendo a fala do agente ao
        # `process_message`. Mesma forma de `ck_handoffs_status`. Os quatro
        # nomes e textos sao os da migration 0037, e o teste
        # `test_o_check_e_o_enum_dizem_a_mesma_coisa` amarra cada um ao enum.
        CheckConstraint(
            "role IN ('LEAD', 'AGENTE', 'CORRETOR', 'SISTEMA')",
            name="ck_messages_role",
        ),
        CheckConstraint(
            "direction IN ('INBOUND', 'OUTBOUND')",
            name="ck_messages_direction",
        ),
        CheckConstraint(
            "content_type IN ('TEXTO', 'AUDIO', 'IMAGEM', 'DOCUMENTO', 'DESCONHECIDO')",
            name="ck_messages_content_type",
        ),
        # NULL passa de proposito: e o que a linha de saida grava, e significa
        # "nao participa do pipeline de ingestao" -- ver o comentario de
        # `status` acima. O `IS NULL` e redundante (`IN` com NULL da UNKNOWN,
        # que nao viola CHECK) e esta aqui para dizer que e deliberado.
        CheckConstraint(
            "status IS NULL OR status IN "
            "('RECEIVED', 'QUEUED', 'PROCESSING', 'PROCESSED', 'FAILED')",
            name="ck_messages_status",
        ),
```

- [ ] **Step 3: Rodar os testes de integração de `messages` e os unitários**

```
./.venv/Scripts/python.exe -m pytest tests/unit tests/integration/test_messages_schema.py tests/integration/test_message_model.py --tb=short
```

Esperado: verde. Esta tarefa não muda esquema nem comportamento — a migration é quem cria as constraints, e ela já rodou na Task 1.

- [ ] **Step 4: Rodar os três gates**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 5: Commit**

```bash
git add src/mobia/domain/messages/models.py
git commit -m "feat(TEC-223): o modelo declara as quatro constraints de vocabulario"
```

---

### Task 4: Verificação final

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-tec-223-check-no-vocabulario-de-messages-design.md` (só o campo **Status**)

**Interfaces:**
- Consumes: tudo das Tasks 1 a 3.
- Produces: a evidência que o PR precisa.

- [ ] **Step 1: Rodar a suíte inteira, UMA vez**

```
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Regras deste repo que valem aqui:

- Centenas de `ERROR` de setup: **não repita o mesmo comando** — o Postgres cai sob o paralelismo. Rode por blocos (`tests/unit`, `tests/integration`, `tests/features`).
- Uma falha isolada com `ConnectionResetError [WinError 64]` não autoriza conclusão nenhuma; ~5% dos connects desta máquina falham assim.
- **`relation ... does not exist` em dezenas de testes** merece atenção redobrada nesta card: os bancos dos workers (`mobia_gw0`…`mobia_gw7`) persistem entre sessões, e esta branch acrescenta uma revisão. Se um `alembic upgrade` for interrompido, o banco fica com `alembic_version` no head e sem o DDL. Confirme comparando `SELECT version_num FROM alembic_version` com a existência das constraints antes de mexer em código.
- Se a primeira execução falhar, repita sobre a mesma árvore antes de culpar a mudança.

- [ ] **Step 2: Conferir que nenhuma fixture grava valor fora do vocabulário**

Este é o risco específico desta card: as constraints agora valem para **toda** a suíte, e qualquer fixture ou teste que gravasse uma grafia divergente passa a falhar. Isso é achado, não obstáculo — o teste estava gravando o que produção não produz.

Atenção a `tests/integration/test_migrations.py:28-38`, que insere com `'text'` e `'RECEIVED'` **no esquema da 0002** — antes da 0004 e muito antes da 0037, então não deve ser alcançado. Se ele falhar, leia por quê antes de mexer.

- [ ] **Step 3: Rodar a listagem de comentários tocados**

```
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reconferir cada `ALTERADO` e `VIZINHO`; tratar `FALSO` como afirmação, não suspeita. O `__table_args__` de `models.py` ganhou conteúdo, então os comentários vizinhos dentro dele entram na lista.

- [ ] **Step 4: Virar o status do desenho**

Em `docs/superpowers/specs/2026-09-20-tec-223-check-no-vocabulario-de-messages-design.md`, trocar `**Status:** aprovado, não implementado` por `**Status:** implementado`.

- [ ] **Step 5: Rodar os três gates uma última vez**

```
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: Commit e push**

```bash
git add docs/superpowers/specs/2026-09-20-tec-223-check-no-vocabulario-de-messages-design.md
git commit -m "docs(TEC-223): o desenho passa a implementado"
git push -u origin feat/tec-223-check-no-vocabulario-de-messages
```

Depois: abrir o PR contra `main`, comentar na card e movê-la para **Em análise**. O comentário precisa registrar:

- que `status` entrou, contra a pergunta em aberto da card, e por quê — o sweeper também o compara por literal, e o `NULL` passa no `IN` sem cláusula extra (medido);
- que `CORRETOR` e `SISTEMA` entraram no CHECK apesar de nenhum código os usar, e a razão (a amarra ao enum exigiria uma exceção que ninguém manteria);
- **a medição da `DETAIL`**: o conteúdo da conversa não vaza porque `text_body` é bytea cifrado, mas o telefone aparece três vezes; no log está fechado desde a TEC-293, pelo uvicorn não está — e esta card cria a condição que dispara aquele flanco;
- que `lead_qualification.temperatura` tem o mesmo problema e ficou de fora.

---

## Autoavaliação do plano

**Cobertura do desenho:** D1 → Task 1 (migration) e Task 3 (modelo). D2 → Task 1 (`test_todo_role_legitimo_passa` inclui os quatro). D3 → Task 2, com o Step 3 provando que a amarra morde. D4 → Task 1, Steps 3 a 6. D5 → Task 3. A seção sobre a `DETAIL` e o uvicorn não pede código; vira item do comentário da card, na Task 4.

**Consistência de nomes:** `ck_messages_role`, `ck_messages_direction`, `ck_messages_content_type` e `ck_messages_status` aparecem com a mesma grafia nas Tasks 1, 2 e 3. As quatro expressões são idênticas entre a migration (Task 1) e o modelo (Task 3), incluindo espaçamento dentro dos parênteses. `MessageContentType` e `MessageStatus` são citados com o nome e o módulo corretos.

**Verificado contra a árvore antes da entrega:** head do Alembic é `0036`; `CheckConstraint` não está importado em `models.py`; o formato de `pg_get_constraintdef` foi medido no Postgres desta máquina e é `= ANY (ARRAY['X'::character varying, …])`, que é o que justifica o regex; e um `CHECK … IN` aceita `NULL` sem cláusula extra, também medido.

**A fixture de sessão foi confirmada antes da entrega:** chama-se `session` (`tests/conftest.py`), e é o que `test_corretores_schema.py` usa. O plano já a escreve com esse nome — não há nome a descobrir durante a execução.

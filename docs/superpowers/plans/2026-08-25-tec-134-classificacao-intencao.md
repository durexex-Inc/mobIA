# TEC-134 — Classificar a intenção do lead a cada turno — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classificar a intenção do lead a cada turno com confiança persistida, e entregar ao lead a primeira resposta que este sistema já produziu.

**Architecture:** Uma única chamada ao modelo devolve intenção, confiança e resposta por saída estruturada com schema estrito. O `GuardedOutbound` passa a liberar a reserva quando a falha é retentável — perder a resposta do lead em silêncio é pior que entregá-la duas vezes. A fala do agente é gravada **depois** da entrega, para o agente se repetir em vez de inventar memória que contaminaria o resumo permanente.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis + ARQ, `anthropic` (saída estruturada), `httpx` (Cloud API da Meta), `cryptography`, structlog, pytest + pytest-asyncio, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-08-25-tec-134-classificacao-intencao-design.md](../specs/2026-08-25-tec-134-classificacao-intencao-design.md)

## Global Constraints

- Python **3.13**. Todo I/O é `async`.
- `ruff check src tests alembic` e `ruff format --check src tests alembic` limpos. `line-length = 100`, regras `E, F, I, UP, B`.
- `mypy` limpo sobre `src`.
- **Nenhum teste toca a rede.** Nem o provedor de modelo, nem a Meta. Dublês para os dois.
- **Nada loga conteúdo de lead** — nem texto de mensagem, nem resumo, nem a resposta gerada, nem o prompt montado.
- Ids de modelo **nunca** levam sufixo de data. O padrão do projeto é `claude-opus-5`.
- Comentário de código em português **sem acento**, explicando por quê e não o quê. Prosa de README e spec usa acento normal.
- Commits: `tipo(TEC-134): descricao em minusculas, sem acento`, sem acento também no corpo.
- **Rodar a suíte em primeiro plano.** `.venv/Scripts/python -m pytest -q` leva cerca de três minutos. Implementadores de histórias anteriores travaram jogando isso para background.

## Estrutura de arquivos

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/agente/__init__.py` | |
| `src/mobia/domain/agente/schemas.py` | `Intencao`, `RespostaDoAgente`. |
| `src/mobia/domain/agente/models.py` | `ConversationIntent`. |
| `src/mobia/domain/agente/repositorio.py` | `ler_intencao`, `gravar_intencao`. |
| `src/mobia/domain/agente/classificador.py` | `ClassificadorPort`, `ClassificadorAnthropic`. |
| `src/mobia/domain/agente/turno.py` | `executar_turno` — orquestra contexto, classificação, entrega e registro. |
| `src/mobia/domain/outbound/whatsapp.py` | `WhatsAppOutbound`. |
| `alembic/versions/0006_conversation_intent.py` | A tabela. |
| `tests/unit/test_intencao.py` | Enum e schema. |
| `tests/integration/test_repositorio_intencao.py` | Upsert e leitura. |
| `tests/integration/test_reserva_liberada.py` | A mudança no `GuardedOutbound`. |
| `tests/integration/test_whatsapp_outbound.py` | Classificação de erro da Meta. |
| `tests/integration/test_turno.py` | O turno inteiro com dublês. |
| `tests/features/test_classificacao_de_intencao.py` | Os cenários Gherkin utilizáveis. |

**Modificar:** `pyproject.toml`, `.env.example`, `src/mobia/app/config.py`, `src/mobia/domain/outbound/port.py`, `src/mobia/workers/jobs/process_message.py`, `src/mobia/workers/main.py`, `tests/conftest.py`, `README.md`.

---

## Task 1: Dependência HTTP e configuração

**Files:**
- Modify: `pyproject.toml`, `.env.example`, `src/mobia/app/config.py`
- Test: `tests/unit/test_config.py` (acrescentar)

**Interfaces:**
- Produces: `Settings.whatsapp_access_token`, `Settings.whatsapp_api_base`, `Settings.modelo_agente`

- [ ] **Step 1: Mover `httpx` para as dependências de produção**

Em `pyproject.toml`, acrescente a `dependencies`, depois de `"anthropic>=1.0",`:

```toml
    "httpx>=0.28",
```

E **remova** a linha `"httpx>=0.28",` de `[project.optional-dependencies] dev` — produção agora cobre.

> Por que explicitamente: hoje `httpx` só existe como dependência de desenvolvimento (o cliente de teste do FastAPI), e o `anthropic` traz `httpx2`, que é **outro pacote**. Falar com a Meta pelo transitivo de outra biblioteca quebraria no dia em que o `anthropic` trocasse de cliente HTTP.

- [ ] **Step 2: Instalar**

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: sem erro.

- [ ] **Step 3: Escrever o teste que vai falhar**

Acrescente ao fim de `tests/unit/test_config.py`:

```python
def test_defaults_do_agente(settings) -> None:
    """O modelo do agente e configuravel separado do modelo do resumo.

    Sao trabalhos diferentes: a TEC-210 vai querer afinar a acuracia de
    intencao sem mexer na qualidade do resumo, e vice-versa.
    """
    assert settings.modelo_agente == "claude-opus-5"
    assert settings.whatsapp_api_base.startswith("https://")


def test_token_da_meta_nao_tem_default_utilizavel(settings) -> None:
    """Sem token nao se envia nada, e isso tem de falhar alto no envio."""
    assert settings.whatsapp_access_token == ""
```

- [ ] **Step 4: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'modelo_agente'`

- [ ] **Step 5: Acrescentar os campos**

Em `src/mobia/app/config.py`, dentro de `Settings`, logo depois de `modelo_resumo`:

```python
    # Separado do modelo_resumo de proposito: a acuracia de intencao e a
    # qualidade do resumo sao metricas distintas e a TEC-210 vai afinar uma
    # sem tocar na outra.
    modelo_agente: str = "claude-opus-5"

    # Sem default utilizavel: envio sem token falha alto na primeira chamada,
    # que e o comportamento certo. Nao precisa da guarda de producao que a
    # chave de cifra tem -- aquela falha em silencio, esta nao.
    whatsapp_access_token: str = ""
    whatsapp_api_base: str = "https://graph.facebook.com/v21.0"
```

- [ ] **Step 6: Registrar no `.env.example`**

Acrescente ao fim:

```
# Token de envio da Cloud API da Meta. Obrigatorio a partir do TEC-134.
WHATSAPP_ACCESS_TOKEN=
```

- [ ] **Step 7: Rodar, gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add pyproject.toml .env.example src/mobia/app/config.py tests/unit/test_config.py
git commit -m "feat(TEC-134): dependencia http de producao e configuracao do agente"
```

---

## Task 2: Esquema da intenção da conversa

**Files:**
- Create: `src/mobia/domain/agente/__init__.py`, `schemas.py`, `models.py`, `repositorio.py`
- Create: `alembic/versions/0006_conversation_intent.py`, `tests/unit/test_intencao.py`, `tests/integration/test_repositorio_intencao.py`
- Modify: `tests/conftest.py`, `alembic/env.py`

**Interfaces:**
- Consumes: `mobia.domain.messages.models.Base`
- Produces:
  - `Intencao` (StrEnum: `COMPRA`, `ALUGUEL`, `INVESTIMENTO`, `VENDER_IMOVEL`, `SUPORTE_CONTRATO`, `INDEFINIDA`, `FORA_DE_ESCOPO`)
  - `ConversationIntent` (ORM)
  - `IntencaoDaConversa` (dataclass frozen: `intencao: Intencao`, `confianca: Decimal`, `modelo: str`)
  - `async def ler_intencao(session, channel, conversation_key) -> IntencaoDaConversa | None`
  - `async def gravar_intencao(session, *, channel, conversation_key, intencao, confianca, modelo) -> None`

- [ ] **Step 1: Escrever os testes que vão falhar**

Crie `tests/unit/test_intencao.py`:

```python
from mobia.domain.agente.schemas import Intencao


def test_as_sete_intencoes_da_regra_de_negocio() -> None:
    """RN-03.1 lista exatamente estas. Nem uma a mais, nem a menos.

    O schema estrito da chamada ao modelo e gerado a partir deste enum, entao
    acrescentar um valor aqui muda o que o modelo pode devolver.
    """
    assert {membro.value for membro in Intencao} == {
        "COMPRA",
        "ALUGUEL",
        "INVESTIMENTO",
        "VENDER_IMOVEL",
        "SUPORTE_CONTRATO",
        "INDEFINIDA",
        "FORA_DE_ESCOPO",
    }


def test_intencao_e_string_no_banco() -> None:
    """StrEnum: a coluna guarda o valor, nao o repr do membro."""
    assert f"{Intencao.INVESTIMENTO}" == "INVESTIMENTO"
```

Crie `tests/integration/test_repositorio_intencao.py`:

```python
from decimal import Decimal

from sqlalchemy import text as sql

from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao
from mobia.domain.agente.schemas import Intencao

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def gravar(session, intencao: Intencao, confianca: str) -> None:
    await gravar_intencao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=intencao,
        confianca=Decimal(confianca),
        modelo="claude-opus-5",
    )
    await session.commit()


async def test_intencao_faz_roundtrip(session) -> None:
    await gravar(session, Intencao.COMPRA, "0.91")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.COMPRA
    assert lida.confianca == Decimal("0.91")
    assert lida.modelo == "claude-opus-5"


async def test_gravar_de_novo_atualiza_em_vez_de_duplicar(session) -> None:
    """Uma conversa tem uma intencao corrente, nao um historico delas."""
    await gravar(session, Intencao.INDEFINIDA, "0.40")
    await gravar(session, Intencao.INVESTIMENTO, "0.88")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.INVESTIMENTO

    total = await session.scalar(sql("SELECT count(*) FROM conversation_intent"))
    assert total == 1


async def test_regravar_a_mesma_intencao_move_o_updated_at(session) -> None:
    """A classificacao acontece a cada turno, mesmo quando nada muda.

    Uma linha que nao e reescrita nao distingue "continua COMPRA" de "nao foi
    classificado neste turno".
    """
    await gravar(session, Intencao.COMPRA, "0.91")
    primeiro = await session.scalar(
        sql("SELECT updated_at FROM conversation_intent WHERE conversation_key = :k"),
        {"k": CONVERSA},
    )

    await gravar(session, Intencao.COMPRA, "0.93")
    segundo = await session.scalar(
        sql("SELECT updated_at FROM conversation_intent WHERE conversation_key = :k"),
        {"k": CONVERSA},
    )

    assert segundo > primeiro


async def test_conversa_sem_intencao_devolve_none(session) -> None:
    assert await ler_intencao(session, CANAL, "nunca-falou") is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_intencao.py tests/integration/test_repositorio_intencao.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.agente'`

- [ ] **Step 3: Criar o pacote e os schemas**

Crie `src/mobia/domain/agente/__init__.py` vazio e `src/mobia/domain/agente/schemas.py`:

```python
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Intencao(StrEnum):
    """As sete intencoes da RN-03.1.

    O schema estrito da chamada ao modelo e derivado deste enum: acrescentar um
    membro aqui muda o conjunto de valores que o modelo pode devolver.
    """

    COMPRA = "COMPRA"
    ALUGUEL = "ALUGUEL"
    INVESTIMENTO = "INVESTIMENTO"
    VENDER_IMOVEL = "VENDER_IMOVEL"
    SUPORTE_CONTRATO = "SUPORTE_CONTRATO"
    INDEFINIDA = "INDEFINIDA"
    FORA_DE_ESCOPO = "FORA_DE_ESCOPO"


@dataclass(frozen=True)
class RespostaDoAgente:
    """O que uma chamada ao modelo devolve num turno.

    Intencao, confianca e resposta vem juntas porque vem da mesma chamada: o
    modelo enxerga a conversa inteira ao decidir as tres, entao a resposta ja
    sai coerente com a intencao que ele mesmo atribuiu.
    """

    intencao: Intencao
    confianca: Decimal
    resposta: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
```

- [ ] **Step 4: Criar o modelo**

Crie `src/mobia/domain/agente/models.py`:

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class ConversationIntent(Base):
    """Intencao corrente da conversa, com a confianca que a produziu.

    Fica em tabela propria e nao em `lead_qualification`, apesar de aquela ja
    ter uma coluna `intencao`: a TEC-127 registrou que a dona de
    lead_qualification e a TEC-145, e confianca e artefato do classificador,
    nao criterio de qualificacao -- nao faz sentido ao lado de quartos e vagas.
    """

    __tablename__ = "conversation_intent"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    intencao: Mapped[str] = mapped_column(String(20), nullable=False)

    # Autoavaliacao do modelo, nao probabilidade calibrada. Ver o spec: os
    # limiares de 0,8 e 0,6 sao provisorios ate a TEC-210 medir contra as 50
    # conversas anotadas.
    confianca: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    modelo: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 5: Criar o repositório**

Crie `src/mobia/domain/agente/repositorio.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.models import ConversationIntent
from mobia.domain.agente.schemas import Intencao


@dataclass(frozen=True)
class IntencaoDaConversa:
    intencao: Intencao
    confianca: Decimal
    modelo: str


async def ler_intencao(
    session: AsyncSession, channel: str, conversation_key: str
) -> IntencaoDaConversa | None:
    linha = await session.get(ConversationIntent, (channel, conversation_key))
    if linha is None:
        return None
    return IntencaoDaConversa(
        intencao=Intencao(linha.intencao),
        confianca=linha.confianca,
        modelo=linha.modelo,
    )


async def gravar_intencao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    confianca: Decimal,
    modelo: str,
) -> None:
    """Upsert. **Nao commita** -- o chamador e dono da transacao.

    Mesma fronteira que `gravar_resumo` da TEC-127 passou a respeitar depois de
    uma review: quem abre a sessao e quem a finaliza.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": str(intencao),
        "confianca": confianca,
        "modelo": modelo,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationIntent).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in ("intencao", "confianca", "modelo", "updated_at")
            },
        )
    )
```

- [ ] **Step 6: Escrever a migração 0006**

Crie `alembic/versions/0006_conversation_intent.py`:

```python
"""intencao corrente da conversa

TEC-134. Chaveada por (channel, conversation_key) como conversation_summaries,
ja que `conversations` de primeira classe continua sendo TEC-129/TEC-130.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_intent",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("intencao", sa.String(20), nullable=False),
        sa.Column("confianca", sa.Numeric(3, 2), nullable=False),
        sa.Column("modelo", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_intent")
```

- [ ] **Step 7: Registrar no `alembic/env.py` e no truncate**

Em `alembic/env.py`, ao lado dos outros imports de modelo:

```python
from mobia.domain.agente.models import ConversationIntent  # noqa: F401
```

Em `tests/conftest.py`, acrescente `"conversation_intent"` ao início da tupla `TABELAS`.

- [ ] **Step 8: Aplicar, rodar e provar reversibilidade**

```bash
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m pytest tests/unit/test_intencao.py tests/integration/test_repositorio_intencao.py -v
.venv/Scripts/python -m alembic downgrade 0005
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic check
```
Expected: testes passam; `alembic check` diz `No new upgrade operations detected.`

- [ ] **Step 9: Suíte, gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/agente/ alembic/ tests/
git commit -m "feat(TEC-134): esquema da intencao corrente da conversa"
```

---

## Task 3: A reserva do `GuardedOutbound` passa a ser liberável

Esta task muda uma decisão que a TEC-122 tomou de propósito. É pequena e é a mais arriscada do plano.

**Files:**
- Modify: `src/mobia/domain/outbound/port.py`
- Create: `tests/integration/test_reserva_liberada.py`

**Interfaces:**
- Produces:
  - `class EnvioRetentavel(Exception)` — falha de envio que vale retentar
  - `class EnvioRecusado(Exception)` — falha permanente; a reserva fica
  - `GuardedOutbound.send` libera a reserva ao capturar `EnvioRetentavel` e repropaga

- [ ] **Step 1: Escrever os testes que vão falhar**

Crie `tests/integration/test_reserva_liberada.py`:

```python
import uuid
from typing import Any

from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel, GuardedOutbound
from mobia.infra.db import get_sessionmaker

KIND = "reply"


class OutboundQueFalha(GuardedOutbound):
    """Falha as primeiras `falhas` tentativas, depois entrega."""

    def __init__(self, session_factory, erro: Exception, falhas: int = 1) -> None:
        super().__init__(session_factory)
        self._erro = erro
        self._falhas = falhas
        self.entregues: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        if self._falhas > 0:
            self._falhas -= 1
            raise self._erro
        self.entregues.append(message_id)


async def uma_mensagem(session) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel="whatsapp",
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key="5511911112222",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()
    return identificador


async def reservas(session, message_id: uuid.UUID) -> int:
    return await session.scalar(
        sql("SELECT count(*) FROM outbound_dispatches WHERE message_id = :m"),
        {"m": message_id},
    )


async def test_falha_retentavel_libera_a_reserva(session) -> None:
    """Sem isso, a resposta ao lead se perde em silencio e para sempre.

    A reserva ja esta commitada quando o envio falha, entao o sweeper
    reenfileira, o worker reivindica, e a guarda responde "ja entreguei isso".
    A Marina nunca recebe nada sobre aquele turno.
    """
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await reservas(session, message_id) == 0, "a reserva tem de sair do caminho"


async def test_apos_liberar_a_retentativa_entrega(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await outbound.send(message_id, KIND, {}) is True
    assert outbound.entregues == [message_id]


async def test_falha_permanente_mantem_a_reserva(session) -> None:
    """4xx nao volta a dar certo. Retentar so queima chamada de modelo."""
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRecusado("payload invalido"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRecusado:
        pass

    assert await reservas(session, message_id) == 1


async def test_apos_falha_permanente_a_retentativa_e_no_op(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRecusado("payload invalido"), falhas=1)

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRecusado:
        pass

    assert await outbound.send(message_id, KIND, {}) is False
    assert outbound.entregues == [], "a guarda suprimiu, nada foi entregue"


async def test_entrega_bem_sucedida_mantem_a_reserva(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)

    assert await outbound.send(message_id, KIND, {}) is True
    assert await reservas(session, message_id) == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_reserva_liberada.py -v`
Expected: FAIL — `ImportError: cannot import name 'EnvioRetentavel'`

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/outbound/port.py`, acrescente o import de `delete`:

```python
from sqlalchemy import delete
```

Acrescente as duas exceções antes de `OutboundPort`:

```python
class EnvioRetentavel(Exception):
    """Falha de envio que uma nova tentativa pode resolver -- rede, 5xx."""


class EnvioRecusado(Exception):
    """Falha de envio permanente -- 4xx. Retentar nao muda nada."""
```

E substitua o `_deliver` dentro de `send` pelo bloco protegido, mais o método novo:

```python
        try:
            await self._deliver(message_id, kind, payload)
        except EnvioRetentavel:
            # A reserva foi desenhada na TEC-122 para um ACK, e ali perder o
            # envio nao custava nada. Agora o que se perde e a resposta ao
            # lead: a reserva commitada faz o sweeper reenfileirar, o worker
            # reivindicar e a guarda responder "ja entreguei isso" -- e o lead
            # nunca recebe nada sobre aquele turno. Liberar inverte a troca
            # para uma duplicata possivel, que e visivel e recuperavel.
            await self._liberar(message_id, kind)
            raise

        log.info("outbound.delivered", message_id=str(message_id), kind=kind)
        return True

    async def _liberar(self, message_id: uuid.UUID, kind: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(OutboundDispatch).where(
                    OutboundDispatch.message_id == message_id,
                    OutboundDispatch.kind == kind,
                )
            )
            await session.commit()
        log.warning("outbound.reserva_liberada", message_id=str(message_id), kind=kind)
```

Atualize a docstring da classe: a frase *"Queda entre a reserva e a entrega perde aquele envio"* passa a valer só para falha permanente.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_reserva_liberada.py -v`
Expected: PASS, 5 testes.

- [ ] **Step 5: Confirmar que os testes do TEC-122 continuam verdes**

Run: `.venv/Scripts/python -m pytest tests/integration/test_outbound_guard.py tests/features/test_reprocessamento_apos_falha.py -v`
Expected: PASS. O critério "nenhuma resposta duplicada" do TEC-122 continua valendo para o caminho de sucesso — só a falha retentável mudou.

- [ ] **Step 6: Suíte, gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/outbound/port.py tests/integration/test_reserva_liberada.py
git commit -m "feat(TEC-134): reserva de envio e liberada em falha retentavel"
```

---

## Task 4: Envio pela Cloud API da Meta

**Files:**
- Create: `src/mobia/domain/outbound/whatsapp.py`, `tests/integration/test_whatsapp_outbound.py`

**Interfaces:**
- Consumes: `GuardedOutbound`, `EnvioRetentavel`, `EnvioRecusado` (Task 3); `Settings.whatsapp_access_token`, `whatsapp_api_base` (Task 1)
- Produces:
  - `class EnvioForaDaJanela(EnvioRecusado)`
  - `WhatsAppOutbound(GuardedOutbound)` — `__init__(session_factory, cliente: httpx.AsyncClient | None = None)`
  - O `payload` de `send` carrega `{"para": <wa_id>, "de": <phone_number_id>, "texto": <str>}`

- [ ] **Step 1: Escrever os testes que vão falhar**

Crie `tests/integration/test_whatsapp_outbound.py`:

```python
import uuid

import httpx
import pytest

from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
from mobia.domain.outbound.whatsapp import EnvioForaDaJanela, WhatsAppOutbound
from mobia.infra.db import get_sessionmaker

PAYLOAD = {"para": "5511911112222", "de": "222222222", "texto": "Ola! Em qual regiao voce procura?"}


def cliente_que_responde(resposta: httpx.Response) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _: resposta))


def cliente_que_estoura(erro: Exception) -> httpx.AsyncClient:
    def _levanta(_: httpx.Request) -> httpx.Response:
        raise erro

    return httpx.AsyncClient(transport=httpx.MockTransport(_levanta))


async def entregar(cliente: httpx.AsyncClient) -> None:
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente)
    await outbound._deliver(uuid.uuid4(), "reply", PAYLOAD)


async def test_entrega_bem_sucedida_nao_levanta(session) -> None:
    await entregar(cliente_que_responde(httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})))


async def test_erro_de_rede_e_retentavel(session) -> None:
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_estoura(httpx.ConnectError("sem rota")))


async def test_5xx_e_retentavel(session) -> None:
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_responde(httpx.Response(503, json={})))


async def test_4xx_comum_e_recusa_permanente(session) -> None:
    """Payload invalido nao melhora com retentativa."""
    with pytest.raises(EnvioRecusado):
        await entregar(
            cliente_que_responde(
                httpx.Response(400, json={"error": {"code": 100, "message": "invalido"}})
            )
        )


async def test_fora_da_janela_de_24h_tem_excecao_propria(session) -> None:
    """Codigo 131047 da Meta: passaram mais de 24h desde a ultima fala do lead.

    Precisa ser distinguivel de um 4xx comum porque o turno termina como
    PROCESSED com log de aviso, nao como erro de payload.
    """
    with pytest.raises(EnvioForaDaJanela):
        await entregar(
            cliente_que_responde(
                httpx.Response(400, json={"error": {"code": 131047, "message": "reengagement"}})
            )
        )


async def test_erro_da_meta_nao_carrega_o_texto_no_log(session, caplog) -> None:
    """O texto enviado e fala do agente para o lead, e nao pode ir para o log."""
    import logging

    with caplog.at_level(logging.WARNING):
        with pytest.raises(EnvioRecusado):
            await entregar(
                cliente_que_responde(
                    httpx.Response(400, json={"error": {"code": 100, "message": "invalido"}})
                )
            )

    assert "Em qual regiao" not in caplog.text
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_whatsapp_outbound.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.outbound.whatsapp'`

- [ ] **Step 3: Implementar**

Crie `src/mobia/domain/outbound/whatsapp.py`:

```python
import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel, GuardedOutbound

log = structlog.get_logger(__name__)

# A Meta devolve este codigo quando passaram mais de 24h desde a ultima fala do
# lead e a mensagem livre deixa de ser permitida.
CODIGO_FORA_DA_JANELA = 131047

TIMEOUT_SEGUNDOS = 10.0


class EnvioForaDaJanela(EnvioRecusado):
    """Passaram mais de 24h desde a ultima fala do lead.

    Herda de EnvioRecusado porque retentar nao ajuda -- so template aprovado
    entrega fora da janela, e template e outra historia. Mas e distinguivel de
    um 4xx comum porque nao e erro nosso: o turno termina PROCESSED com aviso,
    nao com erro de payload.
    """


class WhatsAppOutbound(GuardedOutbound):
    """Entrega de verdade pela Cloud API da Meta.

    Primeiro `_deliver` real do projeto -- ate a TEC-134 ele levantava
    NotImplementedError e o NoopOutbound so logava.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cliente: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(session_factory)
        self._cliente = cliente

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        settings = get_settings()
        cliente = self._cliente or httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS)
        url = f"{settings.whatsapp_api_base}/{payload['de']}/messages"
        corpo = {
            "messaging_product": "whatsapp",
            "to": payload["para"],
            "type": "text",
            "text": {"body": payload["texto"]},
        }

        try:
            resposta = await cliente.post(
                url,
                json=corpo,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            )
        except httpx.RequestError as exc:
            # Nao sabemos se chegou. Retentar pode duplicar, e essa e a troca
            # que o spec escolheu de proposito: duplicata visivel e melhor que
            # silencio invisivel.
            raise EnvioRetentavel(type(exc).__name__) from exc
        finally:
            if self._cliente is None:
                await cliente.aclose()

        if resposta.status_code >= 500:
            raise EnvioRetentavel(f"http {resposta.status_code}")

        if resposta.status_code >= 400:
            codigo = _codigo_do_erro(resposta)
            # Nunca `resposta.text` nem o corpo enviado: o primeiro pode ecoar
            # o payload e o segundo e a fala do agente para o lead.
            log.warning(
                "outbound.recusado",
                message_id=str(message_id),
                kind=kind,
                status=resposta.status_code,
                codigo=codigo,
            )
            if codigo == CODIGO_FORA_DA_JANELA:
                raise EnvioForaDaJanela(str(codigo))
            raise EnvioRecusado(f"http {resposta.status_code} codigo {codigo}")


def _codigo_do_erro(resposta: httpx.Response) -> int | None:
    """O codigo numerico da Meta, quando o corpo tiver o formato esperado."""
    try:
        return int(resposta.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_whatsapp_outbound.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Suíte, gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/outbound/whatsapp.py tests/integration/test_whatsapp_outbound.py
git commit -m "feat(TEC-134): envio real pela cloud api da meta"
```

---

## Task 5: O classificador

**Files:**
- Create: `src/mobia/domain/agente/classificador.py`
- Modify: `tests/unit/test_intencao.py` (acrescentar)

**Interfaces:**
- Consumes: `Intencao`, `RespostaDoAgente` (Task 2); `ContextoMontado` (TEC-127); `get_client()` (TEC-127); `Settings.modelo_agente` (Task 1)
- Produces:
  - `SISTEMA_DO_AGENTE` (str)
  - `SCHEMA_DA_RESPOSTA` (dict) — derivado de `Intencao`
  - `class ClassificadorPort(Protocol)`: `async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente`
  - `ClassificadorAnthropic`
  - `class RespostaInvalida(RuntimeError)`

> **Verificação obrigatória antes de escrever o Step 3.** A ligação exata de saída estruturada do SDK — o formato de `output_config` e se convém usar `client.messages.parse()` — **não pode ser adivinhada**. Invoque a skill `claude-api` e leia `python/claude-api/tool-use.md`, que cobre structured outputs, antes de transcrever o bloco. Se o formato lá divergir do que este plano mostra, **o da skill vence** e você registra a divergência no relatório. Errar essa ligação produz um erro em runtime que nenhum teste com dublê pega, porque o dublê nunca fala com o SDK.

- [ ] **Step 1: Escrever o teste do schema que vai falhar**

Acrescente a `tests/unit/test_intencao.py`:

```python
from mobia.domain.agente.classificador import SCHEMA_DA_RESPOSTA


def test_schema_deriva_do_enum() -> None:
    """O enum e a fonte da verdade: acrescentar intencao muda o schema junto.

    Duas listas mantidas a mao divergem, e a divergencia so aparece quando o
    modelo devolve um valor que o codigo nao sabe converter.
    """
    valores = SCHEMA_DA_RESPOSTA["properties"]["intencao"]["enum"]
    assert set(valores) == {membro.value for membro in Intencao}


def test_schema_e_estrito() -> None:
    """Sem additionalProperties: false o modelo pode inventar campo."""
    assert SCHEMA_DA_RESPOSTA["additionalProperties"] is False
    assert set(SCHEMA_DA_RESPOSTA["required"]) == {"intencao", "confianca", "resposta"}


def test_confianca_e_limitada_no_schema() -> None:
    confianca = SCHEMA_DA_RESPOSTA["properties"]["confianca"]
    assert confianca["minimum"] == 0
    assert confianca["maximum"] == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_intencao.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.agente.classificador'`

- [ ] **Step 3: Publicar `montar_prompt` na TEC-127**

O classificador precisa transformar `ContextoMontado` em texto, e a ordem das partes pertence ao módulo que a definiu — não a quem consome. Ao fim de `src/mobia/domain/context/montagem.py`:

```python
def montar_prompt(contexto: ContextoMontado) -> str:
    """Renderiza as partes na ordem que determina o custo.

    Publico de proposito: a TEC-134 precisa do texto, e a ordem e decisao deste
    modulo, nao dela. Sistema e resumo primeiro porque mudam devagar e ficam
    quentes no cache; estado por ultimo porque muda a cada extracao da TEC-145.
    """
    partes = [contexto.sistema]
    if contexto.resumo is not None:
        partes.append(f"Resumo da conversa ate aqui:\n{contexto.resumo}")
    partes.append(f"Mensagens recentes:\n{_texto_das(contexto.literais)}")
    partes.append(f"Estado de qualificacao:\n{_texto_do_estado(contexto.estado)}")
    return "\n\n".join(partes)
```

- [ ] **Step 4: Implementar o classificador**

Crie `src/mobia/domain/agente/classificador.py`:

```python
import json
import time
from decimal import Decimal
from typing import Any, Protocol

import structlog

from mobia.app.config import get_settings
from mobia.domain.agente.schemas import Intencao, RespostaDoAgente
from mobia.domain.context.montagem import ContextoMontado, montar_prompt
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)

MAX_TOKENS_DA_RESPOSTA = 1500

SISTEMA_DO_AGENTE = (
    "Voce e o assistente virtual de uma imobiliaria brasileira, atendendo um lead "
    "por mensagem. A cada turno voce faz duas coisas: classifica a intencao do "
    "lead e responde a ele.\n\n"
    "Intencoes possiveis: COMPRA (quer comprar para morar), ALUGUEL (quer alugar), "
    "INVESTIMENTO (compra para renda ou revenda, nao para morar), VENDER_IMOVEL "
    "(quer vender o que tem), SUPORTE_CONTRATO (duvida sobre contrato vigente), "
    "INDEFINIDA (ainda nao da para saber), FORA_DE_ESCOPO (nao e assunto "
    "imobiliario).\n\n"
    "A confianca e o quanto voce considera a classificacao segura, de 0 a 1.\n\n"
    "Responda em portugues do Brasil, em tom de conversa. Use o resumo e o "
    "estado de qualificacao como memoria: nao repergunte o que ja esta "
    "preenchido. Nao invente informacao sobre imoveis que nao esteja no "
    "contexto."
)

# Derivado do enum de proposito: duas listas mantidas a mao divergem, e a
# divergencia so aparece quando o modelo devolve um valor que o codigo nao
# sabe converter.
SCHEMA_DA_RESPOSTA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intencao": {"type": "string", "enum": [membro.value for membro in Intencao]},
        "confianca": {"type": "number", "minimum": 0, "maximum": 1},
        "resposta": {"type": "string"},
    },
    "required": ["intencao", "confianca", "resposta"],
    "additionalProperties": False,
}


class RespostaInvalida(RuntimeError):
    """O modelo nao devolveu algo utilizavel neste turno."""


class ClassificadorPort(Protocol):
    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente: ...


class ClassificadorAnthropic:
    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente:
        settings = get_settings()
        comeco = time.monotonic()
        resposta = await get_client().messages.create(
            model=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_RESPOSTA,
            system=SISTEMA_DO_AGENTE,
            messages=[{"role": "user", "content": montar_prompt(contexto)}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA_DA_RESPOSTA}},
        )
        latency_ms = int((time.monotonic() - comeco) * 1000)

        if resposta.stop_reason != "end_turn":
            raise RespostaInvalida(f"stop_reason={resposta.stop_reason!r}")

        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text").strip()
        if not texto:
            raise RespostaInvalida("resposta veio vazia")

        try:
            dados = json.loads(texto)
            resultado = RespostaDoAgente(
                intencao=Intencao(dados["intencao"]),
                confianca=Decimal(str(dados["confianca"])),
                resposta=dados["resposta"].strip(),
                modelo=settings.modelo_agente,
                tokens_in=resposta.usage.input_tokens,
                tokens_out=resposta.usage.output_tokens,
                latency_ms=latency_ms,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            # Nunca interpola `texto`: ele carrega a resposta destinada ao lead.
            raise RespostaInvalida(type(exc).__name__) from exc

        if not resultado.resposta:
            raise RespostaInvalida("campo resposta veio vazio")

        # So numeros e id de modelo. Nem a resposta, nem o prompt, nem a
        # intencao classificada -- essa ultima nao e conteudo do lead, mas
        # tambem nao ajuda em log e mantem a regra simples.
        log.info(
            "agente.turno_gerado",
            modelo=resultado.modelo,
            tokens_in=resultado.tokens_in,
            tokens_out=resultado.tokens_out,
            latency_ms=resultado.latency_ms,
            custo_usd=str(
                custo_em_dolar(resultado.modelo, resultado.tokens_in, resultado.tokens_out)
            ),
        )
        return resultado
```

- [ ] **Step 5: Rodar, gates e commit**

```bash
.venv/Scripts/python -m pytest tests/unit/test_intencao.py -v
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/agente/classificador.py src/mobia/domain/context/montagem.py tests/unit/test_intencao.py
git commit -m "feat(TEC-134): classificador com saida estruturada por schema estrito"
```

---

## Task 6: O turno

Aqui as peças viram um atendimento.

**Files:**
- Create: `src/mobia/domain/agente/turno.py`, `tests/integration/test_turno.py`
- Modify: `src/mobia/workers/jobs/process_message.py`, `src/mobia/workers/main.py`

**Interfaces:**
- Consumes: tudo das tasks 2 a 5, mais `montar_contexto` e `ContextoIrreducivel` (TEC-127), `MessageRecorder` (TEC-126)
- Produces: `async def executar_turno(session_factory, *, message: Message, classificador, resumidor, contador, outbound) -> str` devolvendo `"respondido"`, `"sem_resposta"` ou `"expirado"`

- [ ] **Step 1: Escrever os testes que vão falhar**

**Os dublês nascem em `tests/conftest.py`, não em `test_turno.py`.** A Task 7 vai usar os mesmos, e importar de um módulo de teste para outro exigiria `tests/__init__.py` — acrescentá-lo muda a semântica de import de uma suíte que já está verde. O conftest já hospeda os dublês da TEC-127 (`resumidor_fake`, `contador_fake`, `semear_conversa`) pelo mesmo motivo.

Acrescente a `tests/conftest.py`:

```python
CANAL_AGENTE = "whatsapp"
CONVERSA_AGENTE = "5511911112222"


class ClassificadorFake:
    """Dubl e do provedor. Nenhum teste desta suite toca a rede."""

    def __init__(
        self,
        intencao: "Intencao" = None,  # type: ignore[assignment]
        confianca: Decimal = Decimal("0.91"),
        erro: Exception | None = None,
    ) -> None:
        from mobia.domain.agente.schemas import Intencao as _Intencao

        self.intencao = intencao or _Intencao.COMPRA
        self.confianca = confianca
        self.erro = erro
        self.chamadas = 0

    async def classificar(self, contexto):
        from mobia.domain.agente.schemas import RespostaDoAgente

        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return RespostaDoAgente(
            intencao=self.intencao,
            confianca=self.confianca,
            resposta="Ola! Em qual regiao voce procura?",
            modelo="claude-opus-5",
            tokens_in=1200,
            tokens_out=180,
            latency_ms=900,
        )


class OutboundFake(GuardedOutbound):
    def __init__(self, session_factory, erro: Exception | None = None) -> None:
        super().__init__(session_factory)
        self.erro = erro
        self.entregues: list[str] = []

    async def _deliver(self, message_id, kind, payload) -> None:
        if self.erro is not None:
            raise self.erro
        self.entregues.append(payload["texto"])


@pytest.fixture
def classificador_fake():
    return ClassificadorFake


@pytest.fixture
def outbound_fake():
    def _criar(erro: Exception | None = None) -> OutboundFake:
        return OutboundFake(get_sessionmaker(), erro=erro)

    return _criar


@pytest.fixture
def rodar_turno():
    """Semeia uma entrada e roda o turno inteiro sobre ela."""

    async def _rodar(session, classificador, outbound, resumidor, contador) -> str:
        from mobia.domain.agente.turno import executar_turno

        linha = await _entrada_do_lead(session)
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor,
            contador=contador,
            outbound=outbound,
        )

    return _rodar
```

Mais o helper `_entrada_do_lead(session)` no mesmo arquivo, que grava uma `Message` INBOUND com `conversation_key=CONVERSA_AGENTE`, `recipient_external_id="222222222"`, `status=MessageStatus.PROCESSING` e `text_body` cifrado com `encrypt(texto, aad_de(id, "text_body"))` — mesma forma que `semear` da TEC-127 usa.

Com os imports que faltarem no topo do conftest (`Decimal`, `GuardedOutbound`, `get_sessionmaker`, `pytest`).

Agora crie `tests/integration/test_turno.py`, usando as fixtures:

```python
from decimal import Decimal
from typing import Any

import logging
import pytest
from sqlalchemy import text as sql

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.montagem import ContextoIrreducivel
from mobia.domain.outbound.port import EnvioRetentavel
from mobia.domain.outbound.whatsapp import EnvioForaDaJanela
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def test_turno_classifica_entrega_e_grava(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == ["Ola! Em qual regiao voce procura?"]

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.INVESTIMENTO
    assert gravada.confianca == Decimal("0.91")

    total = await session.scalar(
        sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'")
    )
    assert total == 1, "a fala do agente entra na linha do tempo"


async def test_a_fala_e_gravada_depois_da_entrega(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Se a entrega falha, nao pode sobrar fala fantasma no historico.

    Texto que o lead nunca viu entraria no contexto do proximo turno e depois
    seria dobrado permanentemente no resumo da TEC-127: o agente passaria a
    acreditar que disse algo que nao disse.
    """
    outbound = outbound_fake(EnvioRetentavel("timeout"))

    with pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session, classificador_fake(), outbound, resumidor_fake(), contador_fake()
        )

    total = await session.scalar(
        sql("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'")
    )
    assert total == 0, "nada entregue, nada gravado"


async def test_fora_da_janela_termina_o_turno_sem_erro(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno, caplog
) -> None:
    """Expirar nao e falhar: retentar nunca vai entregar."""
    outbound = outbound_fake(EnvioForaDaJanela("131047"))

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session, classificador_fake(), outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "expirado"
    assert "outbound.fora_da_janela" in caplog.text


async def test_contexto_irreducivel_nao_derruba_o_worker(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    rodar_turno,
    monkeypatch,
    caplog,
) -> None:
    """Mensagem grande demais faz o lead ser ignorado -- em silencio para ele,
    mas nunca em silencio no log."""
    from mobia.domain.agente import turno as turno_mod

    async def _estoura(*_args: Any, **_kwargs: Any) -> Any:
        raise ContextoIrreducivel("tokens=99999, teto=11600")

    monkeypatch.setattr(turno_mod, "montar_contexto", _estoura)
    classificador = classificador_fake()

    with caplog.at_level(logging.WARNING):
        resultado = await rodar_turno(
            session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
        )

    assert resultado == "sem_resposta"
    assert classificador.chamadas == 0, "nem chega a pagar a chamada ao modelo"
    assert "turno.contexto_irreducivel" in caplog.text


async def test_a_intencao_e_gravada_mesmo_se_a_entrega_falhar(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """A classificacao aconteceu de verdade -- registra-la e honesto.

    Ela e sobre a mensagem do lead, nao sobre a resposta que nao saiu.
    """
    outbound = outbound_fake(EnvioRetentavel("timeout"))

    with pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session,
            classificador_fake(Intencao.ALUGUEL),
            outbound,
            resumidor_fake(),
            contador_fake(),
        )

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, CANAL, CONVERSA)
    assert gravada is not None
    assert gravada.intencao is Intencao.ALUGUEL
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_turno.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.agente.turno'`

- [ ] **Step 3: Implementar `src/mobia/domain/agente/turno.py`**

```python
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agente.classificador import ClassificadorPort
from mobia.domain.agente.repositorio import gravar_intencao
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.resumo import ContadorPort, ResumidorPort
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.outbound.port import EnvioRecusado, OutboundPort
from mobia.domain.outbound.whatsapp import EnvioForaDaJanela

log = structlog.get_logger(__name__)

KIND_DA_RESPOSTA = "reply"


async def executar_turno(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    classificador: ClassificadorPort,
    resumidor: ResumidorPort,
    contador: ContadorPort,
    outbound: OutboundPort,
) -> str:
    """Um turno inteiro: contexto, classificacao, entrega, registro.

    A ordem no fim nao e arbitraria. Gravar a fala **depois** da entrega
    significa que uma queda no meio deixa o lead com a resposta e a linha do
    tempo sem ela, e o turno seguinte pode se repetir. Gravar antes deixaria
    uma fala fantasma no historico -- texto que o lead nunca viu, que entra no
    contexto do proximo turno e depois e dobrado permanentemente no resumo. O
    agente se repetir o lead perdoa; memoria inventada contamina tudo o que vem
    depois e ninguem percebe.
    """
    try:
        contexto = await montar_contexto(
            session_factory,
            channel=message.channel,
            conversation_key=message.conversation_key,
            resumidor=resumidor,
            contador=contador,
        )
    except ContextoIrreducivel as exc:
        # Uma unica mensagem que nao cabe no teto. Retentar nao encolhe nada.
        log.warning(
            "turno.contexto_irreducivel",
            channel=message.channel,
            reason=str(exc),
        )
        return "sem_resposta"

    gerada = await classificador.classificar(contexto)

    # Gravada antes da entrega de proposito: a classificacao e sobre a mensagem
    # do lead, que existe, e nao sobre a resposta que pode nao sair.
    async with session_factory() as session:
        await gravar_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            confianca=gerada.confianca,
            modelo=gerada.modelo,
        )
        await session.commit()

    try:
        await outbound.send(
            message.id,
            KIND_DA_RESPOSTA,
            {
                "para": message.conversation_key,
                "de": message.recipient_external_id,
                "texto": gerada.resposta,
            },
        )
    except EnvioForaDaJanela as exc:
        log.warning(
            "outbound.fora_da_janela",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "expirado"
    except EnvioRecusado as exc:
        # `error` e nao `warning`: e o alerta que observa isto. O estado da
        # linha vira PROCESSED porque FAILED faria o sweeper rodar o turno
        # inteiro de novo -- inclusive a chamada paga ao modelo -- para um
        # payload que nunca vai ser aceito.
        log.error(
            "outbound.recusado_permanente",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "sem_resposta"

    recorder = MessageRecorder(session_factory)
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=gerada.resposta,
        model=gerada.modelo,
        subagent="classificador",
        tokens_in=gerada.tokens_in,
        tokens_out=gerada.tokens_out,
        latency_ms=gerada.latency_ms,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    return "respondido"
```

- [ ] **Step 4: Ligar no `process_message`**

Em `src/mobia/workers/jobs/process_message.py`, substitua a linha
`await outbound.send(identifier, ACK_KIND, {})` pela busca da mensagem e a chamada do turno:

```python
        async with session_factory() as session:
            linha = await session.get(Message, identifier)
        if linha is None:
            log.warning("message.sumiu", message_id=message_id)
            return "skipped"

        resultado = await executar_turno(
            session_factory,
            message=linha,
            classificador=ctx["classificador"],
            resumidor=ctx["resumidor"],
            contador=ctx["contador"],
            outbound=outbound,
        )
```

E troque o `return "processed"` final por `return resultado`. Acrescente o import de `executar_turno`. `ACK_KIND` deixa de ser usado — remova a constante e qualquer import dela.

- [ ] **Step 5: Ligar no worker**

Em `src/mobia/workers/main.py`, no `startup`, troque `NoopOutbound` e acrescente as portas:

```python
    ctx["outbound"] = WhatsAppOutbound(session_factory)
    ctx["classificador"] = ClassificadorAnthropic()
    ctx["resumidor"] = ResumidorAnthropic()
    ctx["contador"] = ContadorAnthropic()
```

Com os imports correspondentes. `NoopOutbound` deixa de ser usado em produção — mantenha o arquivo, que os testes do TEC-122 ainda usam.

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_turno.py -v`
Expected: PASS, 5 testes.

- [ ] **Step 7: Confirmar que o pipeline anterior continua verde**

Run: `.venv/Scripts/python -m pytest tests/features/ tests/integration/test_sweep_stalled.py -q`
Expected: PASS. Se `test_reprocessamento_apos_falha.py` quebrar por causa do `ACK_KIND`, ajuste o **teste** para o kind novo — o comportamento que ele prova (nenhuma resposta duplicada no reprocessamento) continua valendo.

- [ ] **Step 8: Suíte, gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/agente/turno.py src/mobia/workers/ tests/
git commit -m "feat(TEC-134): turno completo do agente ligado ao worker"
```

---

## Task 7: Critérios de aceite e README

**Files:**
- Create: `tests/features/test_classificacao_de_intencao.py`
- Modify: `README.md`

- [ ] **Step 1: Escrever os três cenários utilizáveis**

Crie `tests/features/test_classificacao_de_intencao.py`. Os dublês já estão em `tests/conftest.py` desde a Task 6 — nada a mover.

```python
"""Criterios de aceite do TEC-134 como testes executaveis.

O quarto cenario do ticket -- suite de 50 conversas com 90% de acuracia no CI
-- nao esta aqui: ele e a TEC-210, palavra por palavra, e a TEC-210 e bloqueada
pela TEC-161. Ver a secao de escopo do spec.
"""

from decimal import Decimal

from mobia.domain.agente.repositorio import ler_intencao
from mobia.domain.agente.schemas import Intencao
from mobia.infra.db import get_sessionmaker


async def test_reconhecer_intencao_de_investimento(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario: Reconhecer intencao de investimento."""
    classificador = classificador_fake(Intencao.INVESTIMENTO, confianca=Decimal("0.88"))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.INVESTIMENTO
    assert gravada.confianca >= Decimal("0.8")


async def test_reconhecer_intencao_de_aluguel(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario: Reconhecer intencao de aluguel."""
    classificador = classificador_fake(Intencao.ALUGUEL, confianca=Decimal("0.85"))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.ALUGUEL
    assert gravada.confianca >= Decimal("0.8")


async def test_intencao_e_confianca_ficam_registradas_na_conversa(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, rodar_turno
) -> None:
    """Cenario: Intencao e confianca ficam registradas na conversa."""
    classificador = classificador_fake(Intencao.COMPRA, confianca=Decimal("0.91"))
    saida = outbound_fake()

    await rodar_turno(session, classificador, saida, resumidor_fake(), contador_fake())

    async with get_sessionmaker()() as outra:
        gravada = await ler_intencao(outra, "whatsapp", "5511911112222")
    assert gravada is not None
    assert gravada.intencao is Intencao.COMPRA
    assert gravada.confianca == Decimal("0.91")
    assert saida.entregues, "o turno tambem respondeu ao lead"
```

- [ ] **Step 2: Rodar**

Run: `.venv/Scripts/python -m pytest tests/features/test_classificacao_de_intencao.py -v`
Expected: PASS, 3 testes.

- [ ] **Step 3: Documentar no README**

Acrescente depois da seção do TEC-127:

```markdown
## TEC-134 — Classificação de intenção e o primeiro turno

| Cenário Gherkin | Teste |
|---|---|
| Reconhecer intenção de investimento | `tests/features/test_classificacao_de_intencao.py::test_reconhecer_intencao_de_investimento` |
| Reconhecer intenção de aluguel | `tests/features/test_classificacao_de_intencao.py::test_reconhecer_intencao_de_aluguel` |
| Intenção e confiança ficam registradas | `tests/features/test_classificacao_de_intencao.py::test_intencao_e_confianca_ficam_registradas_na_conversa` |

O quarto cenário do ticket — suíte de 50 conversas com 90% de acurácia no CI —
é a TEC-210, palavra por palavra, e não está aqui.

### Garantias

- **Este é o primeiro turno que responde ao lead.** Até aqui o `_deliver` do
  `GuardedOutbound` levantava `NotImplementedError` e o `NoopOutbound` só logava.
- Uma única chamada devolve intenção, confiança e resposta por saída estruturada
  com schema estrito derivado do enum `Intencao`.
- **A reserva de envio é liberada em falha retentável.** A TEC-122 escolheu o
  contrário quando o que se perdia era um ACK; agora o que se perde é a resposta
  ao lead, e perdê-la em silêncio é pior que entregá-la duas vezes.
- **A fala do agente é gravada depois da entrega.** Uma queda no meio deixa o
  lead com a resposta e a linha do tempo sem ela — o agente pode se repetir. O
  contrário deixaria fala fantasma no histórico, que o resumo da TEC-127 dobraria
  permanentemente.
- Fora da janela de 24h da Meta não é falha: o turno termina `PROCESSED` com
  aviso, porque retentar nunca vai entregar.
- 4xx da Meta também termina `PROCESSED`, com log em nível `error` — marcar
  `FAILED` faria o sweeper pagar cinco chamadas ao modelo por um payload que
  nunca será aceito.
- `ANTHROPIC_API_KEY` e `WHATSAPP_ACCESS_TOKEN` são obrigatórias.

### Lacunas conhecidas

- **`ContextoIrreducivel` faz o lead ser ignorado em silêncio.** Uma mensagem
  grande demais para o teto de tokens termina o turno sem resposta. Fica visível
  no log; o dono natural é a TEC-135.
- **Não há moderação de entrada nem de saída.** A TEC-210 exige em 100% dos
  turnos. Este é o primeiro turno que existe, e ele vai ao ar sem nenhuma.
- A confiança é autoavaliação do modelo, não probabilidade calibrada. Os limiares
  de 0,8 e 0,6 são provisórios até a TEC-210 medi-los.
```

- [ ] **Step 4: Rodar a suíte inteira e os gates**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
.venv/Scripts/python -m alembic downgrade 0005 && .venv/Scripts/python -m alembic upgrade head
```
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git add tests/ README.md
git commit -m "test(TEC-134): criterios de aceite como testes executaveis"
```

---

## Verificação final

- [ ] `.venv/Scripts/python -m pytest -q` — verde
- [ ] `.venv/Scripts/python -m pytest -m perf` — o p95 do webhook do TEC-122 não pode ter mudado: o turno roda no worker, não no caminho da requisição. Se mudou, alguma coisa foi ligada onde não devia. O teste é bimodal nesta máquina — repita algumas vezes.
- [ ] `alembic downgrade 0005 && alembic upgrade head` — sem erro
- [ ] `alembic check` — `No new upgrade operations detected`
- [ ] `ruff check`, `ruff format --check`, `mypy` — sem erro
- [ ] Nenhum teste constrói `httpx.AsyncClient` sem `MockTransport`, e nenhum chama a API do modelo
- [ ] `git grep -n "resposta\|texto" src | grep "log\."` — nada loga a fala do agente

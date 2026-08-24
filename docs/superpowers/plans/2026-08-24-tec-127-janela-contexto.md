# TEC-127 — Montar a janela de contexto enviada ao modelo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Montar, a cada turno, o contexto que vai ao modelo — resumo, mensagens literais e estado de qualificação — respeitando um teto de 12.000 tokens e um piso de vinte mensagens na íntegra.

**Architecture:** O resumo guarda uma marca d'água `(created_at, id)` até onde cobre; o contexto é sempre `resumo + tudo depois da marca, literal`, então não existe lacuna. A marca nunca avança além de deixar vinte literais, e a regeneração dispara quando há quarenta. Estouro de token avança a marca, depois re-resume o resumo, em laço limitado a três iterações. Falha do modelo degrada com log e ainda respeita o teto.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis + ARQ, `anthropic` (primeira dependência de LLM do projeto), `cryptography` (AES-GCM), structlog, pydantic-settings, pytest + pytest-asyncio, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-08-24-tec-127-janela-contexto-design.md](../specs/2026-08-24-tec-127-janela-contexto-design.md)

## Global Constraints

- Python **3.13**. Todo I/O é `async`.
- `ruff check src tests alembic` e `ruff format --check src tests alembic` limpos. `line-length = 100`, regras `E, F, I, UP, B`.
- `mypy` limpo sobre `src`.
- **Nenhum teste toca a rede.** Toda chamada ao provedor passa por `ResumidorPort` ou `ContadorPort`, e os testes usam dublês. O TEC-122 deixou um teste que asserta que a rota de ingestão não tem nada de LLM — ele continua valendo.
- **Nada loga conteúdo de lead.** Nem `text_body`, nem `raw_payload`, nem o texto do resumo.
- **O teto de 12.000 tokens nunca é excedido.** É critério de aceite e não cede. O que cede é a completude, e cede ruidosamente.
- Modelo padrão: `claude-opus-5`. Ids de modelo **nunca** levam sufixo de data.
- Comentário de código em português **sem acento**, explicando por quê e não o quê. Prosa de README e spec usa português normal, com acento.
- Commits: `tipo(TEC-127): descricao em minusculas, sem acento`, sem acento também no corpo.

## Estrutura de arquivos

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/infra/anthropic.py` | Cliente do provedor. Não conhece domínio. |
| `src/mobia/domain/context/__init__.py` | |
| `src/mobia/domain/context/models.py` | `ConversationSummary`, `LeadQualification`, `aad_do_resumo`. |
| `src/mobia/domain/context/repositorio.py` | Ler/gravar resumo (cifra e decifra), ler estado. |
| `src/mobia/domain/context/janela.py` | Marca d'água, seleção de literais, gatilho e divisão. |
| `src/mobia/domain/context/resumo.py` | `ResumidorPort`, `ContadorPort`, implementações Anthropic. |
| `src/mobia/domain/context/montagem.py` | `montar_contexto`, `ContextoMontado`, laço do estouro. |
| `alembic/versions/0005_resumo_e_qualificacao.py` | As duas tabelas. |
| `tests/unit/test_janela.py` | Gatilho, divisão, invariante — sem banco. |
| `tests/integration/test_repositorio_contexto.py` | Cifra do resumo, AAD, leitura do estado. |
| `tests/integration/test_montagem.py` | Estouro, degradação, término do laço. |
| `tests/features/test_janela_de_contexto.py` | Os quatro cenários Gherkin. |

**Modificar:** `pyproject.toml`, `.env.example`, `src/mobia/app/config.py`, `tests/conftest.py`, `README.md`.

---

## Task 1: Dependência do provedor, configuração e cliente

**Files:**
- Create: `src/mobia/infra/anthropic.py`
- Modify: `pyproject.toml`, `.env.example`, `src/mobia/app/config.py`
- Test: `tests/unit/test_config.py` (acrescentar)

**Interfaces:**
- Consumes: `mobia.app.config.get_settings`, `mobia.app.config.ConfiguracaoInsegura`
- Produces:
  - `Settings.anthropic_api_key: str`, `Settings.modelo_resumo: str`
  - `Settings.contexto_teto_de_tokens: int`, `contexto_literais_minimas: int`, `contexto_gatilho_de_regeneracao: int`, `contexto_limiar_de_contagem: int`, `contexto_max_iteracoes: int`
  - `mobia.infra.anthropic.get_client() -> AsyncAnthropic`

- [ ] **Step 1: Acrescentar a dependência**

Em `pyproject.toml`, em `dependencies`, depois de `"cryptography>=44.0",`:

```toml
    "anthropic>=1.0",
```

- [ ] **Step 2: Instalar**

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: `Successfully installed anthropic-...`

- [ ] **Step 3: Escrever o teste que vai falhar**

Acrescente ao fim de `tests/unit/test_config.py`:

```python
import pytest

from mobia.app.config import ConfiguracaoInsegura
from mobia.infra.anthropic import get_client


def test_defaults_da_janela_de_contexto(settings) -> None:
    """Os numeros da RN-02.2 e RN-02.5 vivem em configuracao, nao espalhados no codigo."""
    assert settings.modelo_resumo == "claude-opus-5"
    assert settings.contexto_teto_de_tokens == 12000
    assert settings.contexto_literais_minimas == 20
    assert settings.contexto_gatilho_de_regeneracao == 40


def test_gatilho_deixa_o_piso_de_literais(settings) -> None:
    """A invariante das vinte: dobrar `gatilho - minimas` sempre deixa `minimas`.

    Se alguem mexer num dos dois numeros sem mexer no outro, a regeneracao passa
    a colar a marca no presente e o piso quebra no turno seguinte a cada resumo.
    """
    assert settings.contexto_gatilho_de_regeneracao >= 2 * settings.contexto_literais_minimas


def test_cliente_recusa_subir_sem_chave(monkeypatch) -> None:
    """Chave ausente falha aqui, com mensagem util, e nao no meio de um turno."""
    from mobia.app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    get_client.cache_clear()
    try:
        with pytest.raises(ConfiguracaoInsegura, match="ANTHROPIC_API_KEY"):
            get_client()
    finally:
        get_settings.cache_clear()
        get_client.cache_clear()


def test_cliente_e_construido_uma_vez(monkeypatch) -> None:
    from mobia.app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    get_settings.cache_clear()
    get_client.cache_clear()
    try:
        assert get_client() is get_client()
    finally:
        get_settings.cache_clear()
        get_client.cache_clear()
```

- [ ] **Step 4: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.infra.anthropic'`

- [ ] **Step 5: Acrescentar os campos às configurações**

Em `src/mobia/app/config.py`, dentro de `Settings`, depois de `content_encryption_key`:

```python
    # Sem default utilizavel: chave ausente falha alto na construcao do cliente.
    # Nao precisa da guarda de producao que a chave de cifra tem -- uma chave de
    # API errada falha na primeira chamada, enquanto uma chave de cifra errada
    # grava dado com valor publicamente conhecido e nao reclama.
    anthropic_api_key: str = ""

    modelo_resumo: str = "claude-opus-5"

    # RN-02.5: teto por chamada. RN-02.2: piso de mensagens literais.
    contexto_teto_de_tokens: int = 12000
    contexto_literais_minimas: int = 20

    # Dobrar `gatilho - minimas` mensagens deixa exatamente `minimas` literais.
    # Manter gatilho >= 2 * minimas e o que garante o piso depois da regeneracao.
    contexto_gatilho_de_regeneracao: int = 40

    # Acima desta estimativa barata (len/4) vale pagar a contagem real da API.
    # Abaixo, o turno nao gasta round trip nenhum.
    contexto_limiar_de_contagem: int = 10000

    # Teto de iteracoes do laco do estouro. Um `while` aqui e um caminho para
    # gastar dinheiro em circulo com um resumo que nao encolhe.
    contexto_max_iteracoes: int = 3
```

- [ ] **Step 6: Registrar a chave no `.env.example`**

Acrescente ao fim de `.env.example`:

```
# Obrigatoria a partir do TEC-127. Sem ela o cliente do provedor recusa subir.
ANTHROPIC_API_KEY=
```

- [ ] **Step 7: Implementar `src/mobia/infra/anthropic.py`**

```python
from functools import lru_cache

from anthropic import AsyncAnthropic

from mobia.app.config import ConfiguracaoInsegura, get_settings


@lru_cache
def get_client() -> AsyncAnthropic:
    """Cliente unico do processo.

    Construido sob demanda e nao no import: importar o modulo nao pode exigir
    credencial, senao a suite inteira passa a precisar de chave para colecionar
    testes que nunca chamam o provedor.
    """
    chave = get_settings().anthropic_api_key
    if not chave:
        raise ConfiguracaoInsegura(
            "ANTHROPIC_API_KEY nao configurada. O resumo do TEC-127 precisa dela; "
            "defina no .env ou no ambiente antes de subir a API ou o worker."
        )
    return AsyncAnthropic(api_key=chave)
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: PASS.

- [ ] **Step 9: Suíte inteira e gates**

Run: `.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy`
Expected: verde.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml .env.example src/mobia/app/config.py src/mobia/infra/anthropic.py tests/unit/test_config.py
git commit -m "feat(TEC-127): dependencia do provedor, configuracao da janela e cliente"
```

---

## Task 2: Esquema do resumo e do estado de qualificação

**Files:**
- Create: `src/mobia/domain/context/__init__.py`, `src/mobia/domain/context/models.py`, `src/mobia/domain/context/repositorio.py`, `alembic/versions/0005_resumo_e_qualificacao.py`
- Create: `tests/integration/test_repositorio_contexto.py`
- Modify: `tests/conftest.py`, `alembic/env.py`

**Interfaces:**
- Consumes: `mobia.infra.crypto` (`encrypt`, `decrypt`, `aad_de`, `DecryptionError`), `mobia.domain.messages.models.Base`
- Produces:
  - `ConversationSummary`, `LeadQualification` (ORM)
  - `aad_do_resumo(channel: str, conversation_key: str) -> str`
  - `ResumoDaConversa` (dataclass já decifrada) com `texto`, `watermark_created_at`, `watermark_message_id`, `mensagens_cobertas`, `modelo`
  - `async def ler_resumo(session, channel, conversation_key) -> ResumoDaConversa | None`
  - `async def gravar_resumo(session, channel, conversation_key, texto, watermark_created_at, watermark_message_id, mensagens_cobertas, modelo) -> None`
  - `async def ler_estado(session, channel, conversation_key) -> LeadQualification | None`

- [ ] **Step 1: Escrever os testes que vão falhar**

Crie `tests/integration/test_repositorio_contexto.py`:

```python
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text as sql

from mobia.domain.context.models import LeadQualification, aad_do_resumo
from mobia.domain.context.repositorio import gravar_resumo, ler_estado, ler_resumo
from mobia.infra.crypto import DecryptionError, decrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def gravar(session, texto: str = "lead procura apto de 2 quartos na zona sul") -> uuid.UUID:
    marca = uuid.uuid4()
    await gravar_resumo(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        texto=texto,
        watermark_created_at=datetime.now(UTC),
        watermark_message_id=marca,
        mensagens_cobertas=40,
        modelo="claude-opus-5",
    )
    return marca


async def test_resumo_faz_roundtrip(session) -> None:
    marca = await gravar(session)

    lido = await ler_resumo(session, CANAL, CONVERSA)
    assert lido is not None
    assert lido.texto == "lead procura apto de 2 quartos na zona sul"
    assert lido.watermark_message_id == marca
    assert lido.mensagens_cobertas == 40
    assert lido.modelo == "claude-opus-5"


async def test_resumo_vai_cifrado_para_o_banco(session) -> None:
    """Um resumo destila as mesmas frases que text_body guarda."""
    await gravar(session)

    cru = await session.scalar(
        sql(
            "SELECT resumo FROM conversation_summaries"
            " WHERE channel = :c AND conversation_key = :k"
        ),
        {"c": CANAL, "k": CONVERSA},
    )
    assert b"zona sul" not in bytes(cru)


async def test_resumo_de_outra_conversa_nao_decifra(session) -> None:
    """O AAD amarra o resumo a sua propria conversa."""
    await gravar(session)

    cru = await session.scalar(
        sql(
            "SELECT resumo FROM conversation_summaries"
            " WHERE channel = :c AND conversation_key = :k"
        ),
        {"c": CANAL, "k": CONVERSA},
    )
    with pytest.raises(DecryptionError):
        decrypt(bytes(cru), aad_do_resumo(CANAL, "5511999998888"))


async def test_gravar_duas_vezes_atualiza_em_vez_de_duplicar(session) -> None:
    """Uma conversa tem um resumo, nao um historico deles."""
    await gravar(session, "primeira versao")
    await gravar(session, "segunda versao")

    lido = await ler_resumo(session, CANAL, CONVERSA)
    assert lido is not None
    assert lido.texto == "segunda versao"

    total = await session.scalar(sql("SELECT count(*) FROM conversation_summaries"))
    assert total == 1


async def test_conversa_sem_resumo_devolve_none(session) -> None:
    assert await ler_resumo(session, CANAL, "nunca-falou") is None


async def test_estado_de_qualificacao_e_lido_do_banco(session) -> None:
    """TEC-127 le; quem escreve e TEC-145."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao="COMPRA",
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
            quartos=2,
        )
    )
    await session.commit()

    estado = await ler_estado(session, CANAL, CONVERSA)
    assert estado is not None
    assert estado.faixa_preco_max == Decimal("600000.00")
    assert estado.regiao == "zona sul"
    assert estado.vagas is None, "campo nao informado fica nulo, nao zero"


async def test_estado_ausente_devolve_none(session) -> None:
    assert await ler_estado(session, CANAL, "nunca-falou") is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_repositorio_contexto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.context'`

- [ ] **Step 3: Criar o pacote e os modelos**

Crie `src/mobia/domain/context/__init__.py` vazio e `src/mobia/domain/context/models.py`:

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_do_resumo(channel: str, conversation_key: str) -> str:
    """Amarra o resumo a sua propria conversa.

    Nao ha `message_id` aqui -- o resumo cobre muitas mensagens -- entao a
    identidade da linha e o par (channel, conversation_key).
    """
    return aad_de(f"{channel}:{conversation_key}", "resumo")


class ConversationSummary(Base):
    """Resumo do que veio antes da marca d'agua.

    Uma linha por conversa: e estado corrente, nao historico. A marca e um par
    ordenavel `(created_at, id)` e nao uma contagem, porque contagem quebra
    quando uma linha e apagada ou quando duas mensagens chegam fora de ordem.
    """

    __tablename__ = "conversation_summaries"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Cifrado com AES-GCM, AAD `{channel}:{conversation_key}:resumo`. Um resumo
    # destila as mesmas frases que `messages.text_body` guarda -- deixa-lo em
    # claro ao lado de uma coluna cifrada seria manter a fechadura e tirar a
    # porta.
    resumo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    watermark_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    watermark_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mensagens_cobertas: Mapped[int] = mapped_column(Integer, nullable=False)
    modelo: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @validates("resumo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Message`: str aqui vira vazamento no texto do erro.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}")
        return valor


class LeadQualification(Base):
    """Estado estruturado de qualificacao. Esta historia le; TEC-145 escreve.

    Fica **em claro**, ao contrario do resumo, e a assimetria e deliberada:
    TEC-147, TEC-150 e TEC-158 consultam faixa de preco e regiao em SQL, e
    cifrar forcaria carregar a tabela inteira para filtrar em memoria. A cifra
    da TEC-126 protege o que o lead escreveu; isto e o que o sistema concluiu.
    """

    __tablename__ = "lead_qualification"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    intencao: Mapped[str | None] = mapped_column(String(16), nullable=True)
    faixa_preco_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    faixa_preco_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    regiao: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo_imovel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quartos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vagas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgencia: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forma_pagamento: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tem_imovel_para_vender: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Implementar o repositório**

Crie `src/mobia/domain/context/repositorio.py`:

```python
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.models import ConversationSummary, LeadQualification, aad_do_resumo
from mobia.infra.crypto import decrypt, encrypt


@dataclass(frozen=True)
class ResumoDaConversa:
    """O resumo ja decifrado, com a marca do que ele cobre."""

    texto: str
    watermark_created_at: datetime
    watermark_message_id: uuid.UUID
    mensagens_cobertas: int
    modelo: str


async def ler_resumo(
    session: AsyncSession, channel: str, conversation_key: str
) -> ResumoDaConversa | None:
    linha = await session.get(ConversationSummary, (channel, conversation_key))
    if linha is None:
        return None
    texto = decrypt(bytes(linha.resumo), aad_do_resumo(channel, conversation_key))
    assert texto is not None, "resumo e NOT NULL no esquema"
    return ResumoDaConversa(
        texto=texto,
        watermark_created_at=linha.watermark_created_at,
        watermark_message_id=linha.watermark_message_id,
        mensagens_cobertas=linha.mensagens_cobertas,
        modelo=linha.modelo,
    )


async def gravar_resumo(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    texto: str,
    watermark_created_at: datetime,
    watermark_message_id: uuid.UUID,
    mensagens_cobertas: int,
    modelo: str,
) -> None:
    """Upsert: uma conversa tem um resumo, nao um historico deles."""
    cifrado = encrypt(texto, aad_do_resumo(channel, conversation_key))
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "resumo": cifrado,
        "watermark_created_at": watermark_created_at,
        "watermark_message_id": watermark_message_id,
        "mensagens_cobertas": mensagens_cobertas,
        "modelo": modelo,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationSummary).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in (
                    "resumo",
                    "watermark_created_at",
                    "watermark_message_id",
                    "mensagens_cobertas",
                    "modelo",
                    "updated_at",
                )
            },
        )
    )
    await session.commit()


async def ler_estado(
    session: AsyncSession, channel: str, conversation_key: str
) -> LeadQualification | None:
    resultado = await session.execute(
        select(LeadQualification).where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
    )
    return resultado.scalar_one_or_none()
```

- [ ] **Step 5: Escrever a migração 0005**

Crie `alembic/versions/0005_resumo_e_qualificacao.py`:

```python
"""resumo da conversa e estado de qualificacao

TEC-127. Duas tabelas, ambas chaveadas por (channel, conversation_key) -- a
mesma chave denormalizada da TEC-126, ja que `conversations` de primeira classe
continua sendo TEC-129/TEC-130.

`conversation_summaries.resumo` e bytea cifrado; `lead_qualification` fica em
claro de proposito, porque TEC-147, TEC-150 e TEC-158 filtram por esses campos
em SQL.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("resumo", sa.LargeBinary(), nullable=False),
        sa.Column("watermark_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("watermark_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mensagens_cobertas", sa.Integer(), nullable=False),
        sa.Column("modelo", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "lead_qualification",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("intencao", sa.String(16), nullable=True),
        sa.Column("faixa_preco_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("faixa_preco_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("regiao", sa.String(120), nullable=True),
        sa.Column("tipo_imovel", sa.String(32), nullable=True),
        sa.Column("quartos", sa.Integer(), nullable=True),
        sa.Column("vagas", sa.Integer(), nullable=True),
        sa.Column("urgencia", sa.String(32), nullable=True),
        sa.Column("forma_pagamento", sa.String(32), nullable=True),
        sa.Column("tem_imovel_para_vender", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("lead_qualification")
    op.drop_table("conversation_summaries")
```

- [ ] **Step 6: Registrar os modelos no `alembic/env.py`**

O `env.py` importa os modelos para que `Base.metadata` os enxergue. Ao lado do import de `OutboundDispatch`, acrescente:

```python
from mobia.domain.context.models import ConversationSummary, LeadQualification  # noqa: F401
```

- [ ] **Step 7: Acrescentar as tabelas ao truncate**

Em `tests/conftest.py`:

```python
TABELAS = (
    "conversation_summaries",
    "lead_qualification",
    "message_telemetry",
    "outbound_dispatches",
    "messages",
)
```

- [ ] **Step 8: Aplicar e rodar**

```bash
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m pytest tests/integration/test_repositorio_contexto.py -v
```
Expected: PASS, 7 testes.

- [ ] **Step 9: Provar que a migração é reversível**

```bash
.venv/Scripts/python -m alembic downgrade 0004
.venv/Scripts/python -m alembic upgrade head
```
Expected: sem erro. Reversibilidade é critério de aceite do TEC-216.

- [ ] **Step 10: Confirmar que o ORM e o esquema concordam**

Run: `.venv/Scripts/python -m alembic check`
Expected: `No new upgrade operations detected.`

- [ ] **Step 11: Suíte e gates**

Run: `.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy`
Expected: verde.

- [ ] **Step 12: Commit**

```bash
git add src/mobia/domain/context/ alembic/ tests/
git commit -m "feat(TEC-127): esquema do resumo cifrado e do estado de qualificacao"
```

---

## Task 3: A janela — marca d'água, gatilho e a invariante das vinte

Esta task é pura lógica de seleção. Nenhuma chamada de modelo.

**Files:**
- Create: `src/mobia/domain/context/janela.py`, `tests/unit/test_janela.py`
- Test também: `tests/integration/test_montagem.py` (só a parte de consulta, criado aqui)

**Interfaces:**
- Consumes: `Message` (TEC-126), `ResumoDaConversa` (Task 2)
- Produces:
  - `Marca` (dataclass frozen: `created_at: datetime`, `message_id: uuid.UUID`)
  - `marca_de(resumo: ResumoDaConversa | None) -> Marca | None`
  - `async def literais_apos(session, channel, conversation_key, marca: Marca | None) -> list[Message]`
  - `def deve_regenerar(quantidade: int, gatilho: int) -> bool`
  - `def dividir(literais: list[Message], minimas: int) -> tuple[list[Message], list[Message]]`

- [ ] **Step 1: Escrever os testes de unidade que vão falhar**

Crie `tests/unit/test_janela.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.context.janela import deve_regenerar, dividir


def mensagens(quantidade: int) -> list[object]:
    """Dubles posicionais: `dividir` so olha a ordem, nao o conteudo."""
    base = datetime.now(UTC)
    return [
        type("M", (), {"id": uuid.uuid4(), "created_at": base + timedelta(seconds=i)})()
        for i in range(quantidade)
    ]


def test_gatilho_dispara_em_quarenta_e_nao_em_trinta_e_nove() -> None:
    assert deve_regenerar(40, gatilho=40) is True
    assert deve_regenerar(39, gatilho=40) is False
    assert deve_regenerar(41, gatilho=40) is True


def test_dividir_deixa_exatamente_o_piso() -> None:
    """A invariante das vinte, no menor nivel possivel.

    Se `dividir` dobrasse tudo, a marca colaria no presente e o turno seguinte a
    cada resumo teria uma ou duas mensagens literais.
    """
    a_dobrar, a_manter = dividir(mensagens(40), minimas=20)

    assert len(a_dobrar) == 20
    assert len(a_manter) == 20


def test_dividir_nunca_dobra_abaixo_do_piso() -> None:
    """Com menos que o piso nao ha o que dobrar, mesmo que alguem chame."""
    a_dobrar, a_manter = dividir(mensagens(15), minimas=20)

    assert a_dobrar == []
    assert len(a_manter) == 15


def test_dividir_preserva_a_ordem_e_nao_perde_ninguem() -> None:
    todas = mensagens(40)
    a_dobrar, a_manter = dividir(todas, minimas=20)

    assert a_dobrar + a_manter == todas, "nenhuma mensagem some nem troca de lugar"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_janela.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.context.janela'`

- [ ] **Step 3: Implementar `src/mobia/domain/context/janela.py`**

```python
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.repositorio import ResumoDaConversa
from mobia.domain.messages.models import Message


@dataclass(frozen=True)
class Marca:
    """Ate onde o resumo cobre.

    Par ordenavel em vez de contagem: contagem quebra quando uma linha e apagada
    ou quando duas mensagens chegam no mesmo instante.
    """

    created_at: datetime
    message_id: uuid.UUID


def marca_de(resumo: ResumoDaConversa | None) -> Marca | None:
    if resumo is None:
        return None
    return Marca(
        created_at=resumo.watermark_created_at,
        message_id=resumo.watermark_message_id,
    )


async def literais_apos(
    session: AsyncSession,
    channel: str,
    conversation_key: str,
    marca: Marca | None,
) -> list[Message]:
    """Tudo o que ainda nao foi dobrado no resumo, em ordem cronologica.

    A comparacao e de tupla e nao de timestamp sozinho: duas mensagens no mesmo
    `created_at` fariam a janela pular uma ou repetir a outra. O par casa com
    `ix_messages_timeline (channel, conversation_key, created_at DESC)`.
    """
    condicoes = [
        Message.channel == channel,
        Message.conversation_key == conversation_key,
    ]
    if marca is not None:
        condicoes.append(
            tuple_(Message.created_at, Message.id) > tuple_(marca.created_at, marca.message_id)
        )

    resultado = await session.scalars(
        select(Message).where(*condicoes).order_by(Message.created_at, Message.id)
    )
    return list(resultado)


def deve_regenerar(quantidade: int, gatilho: int) -> bool:
    return quantidade >= gatilho


def dividir(
    literais: list[Message], minimas: int
) -> tuple[list[Message], list[Message]]:
    """Separa o que vira resumo do que fica literal.

    O piso manda: por mais que se acumule, `minimas` mensagens sempre ficam na
    integra. E o que faz "as 20 mais recentes na integra" valer no turno logo
    apos uma regeneracao, e nao so no turno que a disparou.
    """
    if len(literais) <= minimas:
        return [], literais
    corte = len(literais) - minimas
    return literais[:corte], literais[corte:]
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/unit/test_janela.py -v`
Expected: PASS, 4 testes.

- [ ] **Step 5: Escrever o teste de integração da consulta**

Crie `tests/integration/test_montagem.py` com a parte da janela (o resto entra na Task 5):

```python
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text as sql

from mobia.app.config import get_settings
from mobia.domain.context.janela import Marca, literais_apos
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def semear(session, quantidade: int, base: datetime | None = None) -> list[Message]:
    """Cria `quantidade` mensagens da mesma conversa, uma por segundo."""
    inicio = base or datetime.now(UTC) - timedelta(hours=1)
    criadas = []
    for i in range(quantidade):
        identificador = uuid.uuid4()
        linha = Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(f"mensagem {i}", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=inicio + timedelta(seconds=i),
        )
        session.add(linha)
        criadas.append(linha)
    await session.commit()
    return criadas


async def test_sem_marca_traz_a_conversa_inteira(session) -> None:
    await semear(session, 5)

    literais = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(literais) == 5


async def test_marca_corta_o_que_ja_foi_resumido(session) -> None:
    criadas = await semear(session, 10)
    marca = Marca(created_at=criadas[3].created_at, message_id=criadas[3].id)

    literais = await literais_apos(session, CANAL, CONVERSA, marca)

    assert len(literais) == 6
    assert literais[0].id == criadas[4].id


async def test_empate_de_timestamp_nao_pula_nem_repete(session) -> None:
    """Duas mensagens no mesmo instante: o desempate e o id, nao a sorte.

    Com comparacao so por `created_at` uma das duas sumiria (se `>`) ou as duas
    voltariam (se `>=`) -- e o resumo perderia ou duplicaria conteudo.
    """
    instante = datetime.now(UTC) - timedelta(minutes=5)
    criadas = await semear(session, 2, base=instante)
    for linha in criadas:
        linha.created_at = instante
    await session.commit()

    primeira, segunda = sorted(criadas, key=lambda m: m.id)
    marca = Marca(created_at=instante, message_id=primeira.id)

    literais = await literais_apos(session, CANAL, CONVERSA, marca)

    assert [linha.id for linha in literais] == [segunda.id]


async def test_conversa_de_outro_lead_nao_entra(session) -> None:
    await semear(session, 3)
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key="5511999998888",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()

    literais = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(literais) == 3
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_montagem.py -v`
Expected: PASS, 4 testes.

- [ ] **Step 7: Gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/context/janela.py tests/
git commit -m "feat(TEC-127): janela por marca d'agua com piso de mensagens literais"
```

---

## Task 4: O resumidor — portas, implementação Anthropic e log estruturado

**Files:**
- Create: `src/mobia/domain/context/resumo.py`
- Test: `tests/integration/test_montagem.py` (acrescentar o dublê, usado na Task 5)

**Interfaces:**
- Consumes: `get_client()` (Task 1), `PRECOS_POR_MODELO` e `custo_em_dolar` (TEC-126, em `mobia.domain.messages.recorder`)
- Produces:
  - `ResumoGerado` (dataclass frozen: `texto: str`, `modelo: str`, `tokens_in: int`, `tokens_out: int`, `latency_ms: int`)
  - `class ResumidorPort(Protocol)`: `async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado`
  - `class ContadorPort(Protocol)`: `async def contar(self, texto: str) -> int`
  - `ResumidorAnthropic`, `ContadorAnthropic`
  - `INSTRUCAO_DOBRAR`, `INSTRUCAO_COMPRIMIR` (constantes de prompt)

- [ ] **Step 1: Implementar `src/mobia/domain/context/resumo.py`**

Esta task não começa por teste: o que ela entrega é a fronteira com um serviço externo, e o dublê que os testes usam nasce junto na Task 5. O que se testa aqui é o cálculo de custo e o log, no Step 3.

```python
import time
from dataclasses import dataclass
from typing import Protocol

import structlog

from mobia.app.config import get_settings
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)

MAX_TOKENS_DO_RESUMO = 2000

INSTRUCAO_DOBRAR = (
    "Voce mantem a memoria de uma conversa entre um lead imobiliario e um agente. "
    "Incorpore as mensagens abaixo ao resumo existente, preservando fatos concretos: "
    "orcamento, regiao, tipo de imovel, quartos, vagas, prazo, forma de pagamento, "
    "objecoes e compromissos assumidos. Descarte cortesia e repeticao. "
    "Escreva em terceira pessoa, em portugues, sem inventar nada que nao esteja no texto."
)

INSTRUCAO_COMPRIMIR = (
    "Comprima o resumo abaixo pela metade, preservando todo fato concreto sobre o lead "
    "-- orcamento, regiao, tipo de imovel, quartos, vagas, prazo, forma de pagamento, "
    "objecoes e compromissos. Descarte narrativa e transicao. Nao invente nada."
)


@dataclass(frozen=True)
class ResumoGerado:
    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class ResumidorPort(Protocol):
    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado: ...


class ContadorPort(Protocol):
    async def contar(self, texto: str) -> int: ...


class ResumidorAnthropic:
    """Resumo pelo modelo padrao do projeto.

    Nao rebaixa o modelo: o resumo nao e saida descartavel, e entrada de todo
    turno seguinte. Um resumo pobre erra em todas as respostas dali em diante e
    sem ninguem perceber, e a regua que mediria isso so chega na TEC-210.
    """

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        settings = get_settings()
        comeco = time.monotonic()
        resposta = await get_client().messages.create(
            model=settings.modelo_resumo,
            max_tokens=MAX_TOKENS_DO_RESUMO,
            system=instrucao,
            messages=[{"role": "user", "content": conteudo}],
        )
        latency_ms = int((time.monotonic() - comeco) * 1000)

        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
        gerado = ResumoGerado(
            texto=texto,
            modelo=settings.modelo_resumo,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            latency_ms=latency_ms,
        )

        # Gasto de LLM que nao e resposta ao lead nao cabe em message_telemetry,
        # que tem FK para messages.id. Fica em log estruturado ate o painel de
        # custo (E8) e a TEC-220 decidirem onde isso mora. Nunca loga o texto.
        log.info(
            "resumo.gerado",
            modelo=gerado.modelo,
            tokens_in=gerado.tokens_in,
            tokens_out=gerado.tokens_out,
            latency_ms=gerado.latency_ms,
            custo_usd=str(custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)),
        )
        return gerado


class ContadorAnthropic:
    """Contagem real de tokens pela API.

    Nunca `tiktoken` nem heuristica de caractere como fonte de verdade: o teto
    de 12.000 e criterio de aceite, e errar a contagem para menos significa a
    chamada ser recusada em producao.
    """

    async def contar(self, texto: str) -> int:
        resposta = await get_client().messages.count_tokens(
            model=get_settings().modelo_resumo,
            messages=[{"role": "user", "content": texto}],
        )
        return int(resposta.input_tokens)
```

- [ ] **Step 2: Escrever o teste do log e do custo**

Acrescente a `tests/integration/test_montagem.py`:

```python
import logging

from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.messages.recorder import custo_em_dolar


def test_resumo_gerado_tem_custo_calculavel() -> None:
    """O log de `resumo.gerado` carrega custo; o modelo padrao tem preco."""
    gerado = ResumoGerado(
        texto="lead procura apto na zona sul",
        modelo="claude-opus-5",
        tokens_in=8000,
        tokens_out=500,
        latency_ms=1200,
    )
    custo = custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)

    assert custo is not None, "modelo padrao do projeto tem de estar na tabela de precos"
    assert custo > 0
```

- [ ] **Step 3: Rodar, gates e commit**

```bash
.venv/Scripts/python -m pytest tests/integration/test_montagem.py -v
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/context/resumo.py tests/
git commit -m "feat(TEC-127): porta do resumidor e implementacao pelo provedor"
```

---

## Task 5: Montagem, contagem de tokens e o laço do estouro

O coração da história. Aqui as peças das tasks 2, 3 e 4 viram um contexto.

**Files:**
- Create: `src/mobia/domain/context/montagem.py`
- Modify: `tests/integration/test_montagem.py`

**Interfaces:**
- Consumes: tudo das tasks 2, 3 e 4
- Produces:
  - `ContextoMontado` (dataclass frozen: `sistema: str`, `resumo: str | None`, `literais: list[Message]`, `estado: LeadQualification | None`, `tokens: int`, `degradado: bool`)
  - `async def montar_contexto(session, *, channel, conversation_key, resumidor, contador) -> ContextoMontado`

- [ ] **Step 1: Escrever os testes que vão falhar**

Acrescente a `tests/integration/test_montagem.py`:

```python
from decimal import Decimal

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.repositorio import ler_resumo
from mobia.domain.context.resumo import ResumidorPort  # noqa: F401  (documenta a fronteira)
from mobia.infra.db import get_sessionmaker


class ResumidorFake:
    """Dublê do provedor. Nenhum teste desta suite toca a rede."""

    def __init__(self, texto: str = "resumo do que veio antes", falha: bool = False) -> None:
        self.texto = texto
        self.falha = falha
        self.chamadas: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.chamadas.append(instrucao)
        if self.falha:
            raise RuntimeError("provedor fora do ar")
        return ResumoGerado(
            texto=self.texto,
            modelo="claude-opus-5",
            tokens_in=100,
            tokens_out=50,
            latency_ms=10,
        )


class ContadorFake:
    """Conta por caractere/4, ou devolve valores roteirizados em sequencia."""

    def __init__(self, roteiro: list[int] | None = None) -> None:
        self.roteiro = roteiro or []
        self.chamadas = 0

    async def contar(self, texto: str) -> int:
        self.chamadas += 1
        if self.roteiro:
            return self.roteiro.pop(0)
        return len(texto) // 4


@pytest.fixture
def sempre_contar(monkeypatch):
    """Forca a contagem real em todo turno.

    Sem isso a estimativa barata (len/4) responde sozinha: mensagens curtas de
    teste nunca passam do limiar de 10.000, o ContadorFake nao e consultado e o
    roteiro de estouro nunca acontece. O teste passaria sem exercitar o laco.
    """
    monkeypatch.setenv("CONTEXTO_LIMIAR_DE_CONTAGEM", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_regenera_ao_atingir_o_gatilho(session) -> None:
    await semear(session, 40)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert len(resumidor.chamadas) == 1, "quarenta literais disparam uma regeneracao"
    assert len(contexto.literais) == 20, "o piso fica intacto depois de dobrar"
    assert contexto.resumo == "resumo do que veio antes"

    async with get_sessionmaker()() as outra:
        gravado = await ler_resumo(outra, CANAL, CONVERSA)
    assert gravado is not None, "a marca avanca no banco, nao so em memoria"
    assert gravado.mensagens_cobertas == 20


async def test_nao_regenera_abaixo_do_gatilho(session) -> None:
    await semear(session, 39)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert resumidor.chamadas == []
    assert len(contexto.literais) == 39, "sem resumo ainda, tudo entra literal"
    assert contexto.resumo is None


async def test_o_piso_vale_em_todo_ponto_entre_regeneracoes(session) -> None:
    """A regressao que os quatro cenarios Gherkin sozinhos nao pegariam.

    Eles testam estados; este testa a transicao. Se a marca colar no presente, o
    turno seguinte a uma regeneracao cai para uma ou duas literais e este teste
    quebra no passo exato em que isso acontece.
    """
    criadas = await semear(session, 80)
    resumidor = ResumidorFake()
    minimas = get_settings().contexto_literais_minimas

    for corte in range(41, 81):
        async with get_sessionmaker()() as limpeza:
            await limpeza.execute(
                sql("DELETE FROM messages WHERE created_at > :t"),
                {"t": criadas[corte - 1].created_at},
            )
            await limpeza.commit()

        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=ContadorFake(),
        )
        assert len(contexto.literais) >= minimas, (
            f"com {corte} mensagens o prompt caiu para {len(contexto.literais)} literais"
        )


async def test_estouro_avanca_a_marca_antes_de_comprimir(session, sempre_contar) -> None:
    """A ordem importa: dobrar mensagem e perda normal, re-resumir e cascata."""
    await semear(session, 25)
    resumidor = ResumidorFake()
    # 1a contagem estoura, 2a (depois de dobrar) cabe.
    contador = ContadorFake(roteiro=[13500, 9000])

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert resumidor.chamadas[0] == INSTRUCAO_DOBRAR, "primeiro dobra, so depois comprime"


async def test_laco_termina_mesmo_com_resumidor_que_nao_encolhe(session, sempre_contar) -> None:
    """Um `while` aqui gastaria dinheiro em circulo. O teto de iteracoes corta."""
    await semear(session, 25)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500] * 10)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert len(resumidor.chamadas) <= get_settings().contexto_max_iteracoes + 1
    assert contexto.degradado is True


async def test_falha_do_provedor_degrada_sem_derrubar(session, caplog) -> None:
    """A Marina esta esperando: o turno segue, o teto e respeitado, o log grita."""
    await semear(session, 40)

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(falha=True),
            contador=ContadorFake(),
        )

    assert contexto.degradado is True
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert "contexto.degradado" in caplog.text


async def test_estado_de_qualificacao_entra_no_contexto(session) -> None:
    await semear(session, 3)
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
        )
    )
    await session.commit()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    assert contexto.estado is not None
    assert contexto.estado.faixa_preco_max == Decimal("600000.00")
```

Acrescente ao topo do arquivo os imports que faltam:

```python
from mobia.domain.context.resumo import INSTRUCAO_DOBRAR, ResumoGerado
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_montagem.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.context.montagem'`

- [ ] **Step 3: Implementar `src/mobia/domain/context/montagem.py`**

```python
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.context.janela import dividir, literais_apos, marca_de
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import (
    ResumoDaConversa,
    gravar_resumo,
    ler_estado,
    ler_resumo,
)
from mobia.domain.context.resumo import (
    INSTRUCAO_COMPRIMIR,
    INSTRUCAO_DOBRAR,
    ContadorPort,
    ResumidorPort,
)
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, decrypt

log = structlog.get_logger(__name__)

SISTEMA = (
    "Voce e o assistente virtual de uma imobiliaria, atendendo um lead. "
    "Use o resumo e o estado de qualificacao abaixo como memoria: nao repergunte "
    "o que ja esta preenchido."
)


@dataclass(frozen=True)
class ContextoMontado:
    """As partes em ordem, nao uma string pronta.

    A ordem pertence ao dominio porque e ela que determina o custo: prompt
    caching e casamento de prefixo, entao o que muda devagar vem primeiro. O
    estado vai por ultimo de proposito -- no topo, cada campo extraido pela
    TEC-145 invalidaria o resumo e as vinte mensagens junto.
    """

    sistema: str
    resumo: str | None
    literais: list[Message]
    estado: LeadQualification | None
    tokens: int
    degradado: bool


def _texto_da(linha: Message) -> str:
    """Decifra o corpo para montar o prompt.

    O conteudo real e obrigatorio aqui por dois motivos: o resumo so e util se
    resumir o que foi dito, e a contagem de tokens tem de medir o que vai de
    fato ser enviado. Este texto nunca entra num `log.*`.
    """
    corpo = decrypt(linha.text_body, aad_de(linha.id, "text_body")) or ""
    return f"[{linha.role}] {corpo}"


def _texto_das(literais: list[Message]) -> str:
    return "\n".join(_texto_da(linha) for linha in literais)


def _estimar(resumo: str | None, literais: list[Message]) -> int:
    bruto = len(SISTEMA) + len(resumo or "") + len(_texto_das(literais))
    return bruto // 4


async def _contar_se_valer(
    contador: ContadorPort, resumo: str | None, literais: list[Message]
) -> int:
    """Estimativa barata decide se vale pagar o round trip da contagem real.

    Turno normal nao paga nada; turno perto do limite paga um e acerta. A
    estimativa nunca decide sozinha se cabe -- so decide se vale medir.
    """
    estimativa = _estimar(resumo, literais)
    if estimativa < get_settings().contexto_limiar_de_contagem:
        return estimativa
    return await contador.contar(f"{SISTEMA}\n{resumo or ''}\n{_texto_das(literais)}")


async def montar_contexto(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    resumidor: ResumidorPort,
    contador: ContadorPort,
) -> ContextoMontado:
    settings = get_settings()

    async with session_factory() as session:
        resumo_atual = await ler_resumo(session, channel, conversation_key)
        literais = await literais_apos(
            session, channel, conversation_key, marca_de(resumo_atual)
        )
        estado = await ler_estado(session, channel, conversation_key)

    texto_do_resumo = resumo_atual.texto if resumo_atual else None
    cobertas = resumo_atual.mensagens_cobertas if resumo_atual else 0
    degradado = False

    # Gatilho por acumulo: quarenta literais dobram as vinte mais antigas e
    # deixam vinte. Por proximidade, a marca colaria no presente.
    if len(literais) >= settings.contexto_gatilho_de_regeneracao:
        texto_do_resumo, literais, cobertas, falhou = await _dobrar(
            session_factory,
            channel,
            conversation_key,
            resumidor,
            texto_do_resumo,
            literais,
            cobertas,
            INSTRUCAO_DOBRAR,
        )
        degradado = degradado or falhou

    tokens = await _contar_se_valer(contador, texto_do_resumo, literais)

    iteracao = 0
    while tokens > settings.contexto_teto_de_tokens:
        if iteracao >= settings.contexto_max_iteracoes:
            # Ultimo recurso: o teto e limite fisico da chamada, o piso e
            # preferencia de qualidade. Quando se contradizem, o teto vence.
            descartadas = len(literais) - 1
            literais = literais[-1:]
            degradado = True
            log.warning(
                "contexto.truncado",
                channel=channel,
                descartadas=descartadas,
                tokens=tokens,
            )
            tokens = await _contar_se_valer(contador, texto_do_resumo, literais)
            break

        if len(literais) > settings.contexto_literais_minimas:
            instrucao = INSTRUCAO_DOBRAR
        else:
            # Nao ha mais mensagem a dobrar sem violar o piso; agora a cascata.
            instrucao = INSTRUCAO_COMPRIMIR
            log.warning("contexto.piso_violado", channel=channel, tokens=tokens)

        texto_do_resumo, literais, cobertas, falhou = await _dobrar(
            session_factory,
            channel,
            conversation_key,
            resumidor,
            texto_do_resumo,
            literais,
            cobertas,
            instrucao,
        )
        degradado = degradado or falhou
        if falhou:
            break
        tokens = await _contar_se_valer(contador, texto_do_resumo, literais)
        iteracao += 1

    return ContextoMontado(
        sistema=SISTEMA,
        resumo=texto_do_resumo,
        literais=literais,
        estado=estado,
        tokens=tokens,
        degradado=degradado,
    )


async def _dobrar(
    session_factory: async_sessionmaker[AsyncSession],
    channel: str,
    conversation_key: str,
    resumidor: ResumidorPort,
    texto_do_resumo: str | None,
    literais: list[Message],
    cobertas: int,
    instrucao: str,
) -> tuple[str | None, list[Message], int, bool]:
    """Uma passada: gera o resumo novo, grava a marca e devolve o que sobrou.

    Falha do provedor nao propaga. A Marina esta esperando: o caminho degradado
    usa o resumo antigo e o chamador corta literais ate caber. E a mesma
    filosofia do `_try_enqueue` da TEC-122 -- o caminho principal sobrevive, o
    efeito secundario engole a propria falha e grita no log.
    """
    settings = get_settings()

    if instrucao == INSTRUCAO_COMPRIMIR:
        a_dobrar, a_manter = [], literais
        conteudo = texto_do_resumo or ""
    else:
        a_dobrar, a_manter = dividir(literais, settings.contexto_literais_minimas)
        if not a_dobrar:
            return texto_do_resumo, literais, cobertas, False
        conteudo = (
            f"Resumo atual:\n{texto_do_resumo or '(vazio)'}\n\n"
            f"Novas mensagens:\n{_texto_das(a_dobrar)}"
        )

    try:
        gerado = await resumidor.resumir(instrucao, conteudo)
    except Exception as exc:
        log.warning(
            "contexto.degradado",
            channel=channel,
            reason=type(exc).__name__,
            detail=str(exc),
        )
        return texto_do_resumo, literais, cobertas, True

    if a_dobrar:
        ultima = a_dobrar[-1]
        async with session_factory() as session:
            await gravar_resumo(
                session,
                channel=channel,
                conversation_key=conversation_key,
                texto=gerado.texto,
                watermark_created_at=ultima.created_at,
                watermark_message_id=ultima.id,
                mensagens_cobertas=cobertas + len(a_dobrar),
                modelo=gerado.modelo,
            )
        cobertas += len(a_dobrar)

    return gerado.texto, a_manter, cobertas, False
```

> **Sobre o breakpoint de cache:** o spec descreve a ordem `sistema → resumo → mensagens → estado` com um breakpoint depois do resumo. Esta história **não** renderiza o prompt — ela devolve as partes, e quem renderiza é TEC-134. A ordem é entregue pela ordem dos campos de `ContextoMontado` e pela docstring que explica o porquê. Não implemente um renderizador aqui: seria adivinhar a forma que o consumidor ainda não tem.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_montagem.py -v`
Expected: PASS.

- [ ] **Step 5: Gates e commit**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic && .venv/Scripts/python -m ruff format src tests alembic && .venv/Scripts/python -m mypy
git add src/mobia/domain/context/montagem.py tests/
git commit -m "feat(TEC-127): montagem do contexto com teto de tokens e laco limitado"
```

---

## Task 6: Critérios de aceite como testes executáveis

**Files:**
- Create: `tests/features/test_janela_de_contexto.py`
- Modify: `README.md`

- [ ] **Step 1: Escrever os quatro cenários**

**Primeiro mova os helpers para onde os dois arquivos alcançam.** `semear`, `ResumidorFake`, `ContadorFake` e a fixture `sempre_contar` nasceram em `tests/integration/test_montagem.py`, mas importar de um módulo de teste para outro exige que `tests/` seja pacote — e acrescentar `tests/__init__.py` muda a semântica de import da suíte inteira, que já está verde. Mova os quatro para `tests/conftest.py`, que é sempre alcançável, e importe `ResumoGerado` lá. Em `test_montagem.py` deixe apenas os testes; as classes viram fixtures ou continuam classes de módulo importadas do conftest via `pytest.fixture`.

O caminho mais curto que não mexe na semântica: declare no `conftest.py`

```python
@pytest.fixture
def resumidor_fake():
    return ResumidorFake


@pytest.fixture
def contador_fake():
    return ContadorFake


@pytest.fixture
def semear_conversa():
    return semear
```

e receba as três por parâmetro nos testes dos dois arquivos.

```python
"""Criterios de aceite do TEC-127 como testes executaveis.

Cada teste corresponde a um cenario Gherkin da historia. Ha sobreposicao
deliberada com os testes de integracao: estes existem para que o criterio tenha
um endereco, nao para cobrir codigo novo.
"""

from decimal import Decimal

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import montar_contexto
from mobia.infra.db import get_sessionmaker



async def test_conversa_longa_cabe_no_limite_de_tokens(session) -> None:
    """Cenario: Conversa longa cabe no limite de tokens."""
    await semear(session, 60)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    assert len(contexto.literais) >= get_settings().contexto_literais_minimas
    assert contexto.resumo is not None, "as anteriores viraram resumo"
    assert contexto.tokens <= 12000


async def test_estado_estruturado_nao_e_reconstruido_pelo_modelo(session) -> None:
    """Cenario: Estado estruturado nao e reconstruido pelo modelo."""
    await semear(session, 5)
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
        )
    )
    await session.commit()

    resumidor = ResumidorFake()
    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert contexto.estado is not None
    assert contexto.estado.faixa_preco_max == Decimal("600000.00")
    assert resumidor.chamadas == [], (
        "o estado vem do banco; nenhuma chamada ao modelo o reconstroi"
    )


async def test_resumo_e_comprimido_ao_estourar_o_limite(session, sempre_contar) -> None:
    """Cenario: Resumo e comprimido ao estourar o limite."""
    await semear(session, 25)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(roteiro=[13500, 9000]),
    )

    assert contexto.tokens <= 12000


async def test_resumo_e_regerado_na_cadencia_definida(session) -> None:
    """Cenario: Resumo e regerado na cadencia definida."""
    await semear(session, 39)
    resumidor = ResumidorFake()

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )
    assert resumidor.chamadas == [], "trinta e nove nao dispara"

    await semear(session, 1)
    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )
    assert len(resumidor.chamadas) == 1, "a quadragesima dispara"
```

- [ ] **Step 2: Rodar**

Run: `.venv/Scripts/python -m pytest tests/features/test_janela_de_contexto.py -v`
Expected: PASS, 4 testes.

- [ ] **Step 3: Documentar no README**

Acrescente ao `README.md`, depois da seção do TEC-126:

```markdown
## TEC-127 — Janela de contexto do modelo

| Cenário Gherkin | Teste |
|---|---|
| Conversa longa cabe no limite de tokens | `tests/features/test_janela_de_contexto.py::test_conversa_longa_cabe_no_limite_de_tokens` |
| Estado estruturado não é reconstruído | `tests/features/test_janela_de_contexto.py::test_estado_estruturado_nao_e_reconstruido_pelo_modelo` |
| Resumo é comprimido ao estourar | `tests/features/test_janela_de_contexto.py::test_resumo_e_comprimido_ao_estourar_o_limite` |
| Resumo é regerado na cadência | `tests/features/test_janela_de_contexto.py::test_resumo_e_regerado_na_cadencia_definida` |

### Garantias

- O contexto é `resumo + tudo o que veio depois da marca d'água, na íntegra` —
  não existe lacuna entre o que foi resumido e o que está literal.
- **A marca nunca avança além de deixar vinte mensagens literais.** As vinte mais
  recentes são um piso, não um teto: entre regenerações o prompt carrega de vinte
  a quarenta na íntegra.
- Estouro do teto de 12.000 tokens avança a marca primeiro e só re-resume o
  resumo depois — dobrar mensagem é perda normal, re-resumir é perda em cascata.
  O laço é limitado a três iterações.
- Quando o piso e o teto se contradizem (vinte mensagens que somam mais de
  12.000 tokens), o teto vence e `contexto.piso_violado` registra.
- Falha do provedor não derruba o turno: usa o resumo antigo, corta literais até
  caber, e loga `contexto.degradado`.
- O resumo é cifrado em repouso como o conteúdo das mensagens; o estado de
  qualificação fica em claro de propósito, porque TEC-147, TEC-150 e TEC-158
  filtram por ele em SQL.
- A chave `ANTHROPIC_API_KEY` é obrigatória a partir desta história.
```

- [ ] **Step 4: Rodar a suíte inteira e os gates**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests alembic
.venv/Scripts/python -m ruff format --check src tests alembic
.venv/Scripts/python -m mypy
```
Expected: tudo verde. É o mesmo conjunto que o CI do TEC-216 roda.

- [ ] **Step 5: Commit**

```bash
git add tests/features/test_janela_de_contexto.py README.md
git commit -m "test(TEC-127): criterios de aceite como testes executaveis"
```

---

## Verificação final

- [ ] `.venv/Scripts/python -m pytest -q` — verde
- [ ] `.venv/Scripts/python -m pytest -m perf` — o teste de latência do TEC-122 continua no orçamento. Esta história **não** entra no caminho da requisição do webhook, então não deve mexer no p95; se mexer, alguma coisa foi ligada onde não devia. O teste é bimodal nesta máquina — repita algumas vezes antes de concluir qualquer coisa.
- [ ] `alembic downgrade 0004 && alembic upgrade head` — sem erro
- [ ] `alembic check` — `No new upgrade operations detected`
- [ ] `ruff check`, `ruff format --check`, `mypy` — sem erro
- [ ] `git grep -n "text_body\|resumo" src | grep "log\."` — nada loga conteúdo nem resumo
- [ ] Nenhum teste da suíte constrói `AsyncAnthropic` nem chama a rede

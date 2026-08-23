# TEC-122 — Ingestão de mensagens do WhatsApp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receber o webhook do WhatsApp, verificar a assinatura da Meta, persistir a mensagem e enfileirá-la para processamento assíncrono, sem perder mensagem em queda de worker e sem efeito colateral duplicado.

**Architecture:** O webhook responde 200 depois de um único `INSERT` commitado e um enqueue otimista no Redis. A própria tabela `messages` é o outbox: se o processo morrer entre o commit e o enqueue, um cron ARQ varre linhas paradas e reenfileira. O worker reivindica a mensagem com um `UPDATE` condicional e todo efeito externo passa por uma reserva única em `outbound_dispatches`, o que torna a reentrega um no-op. Nenhuma dependência de LLM existe no caminho da requisição.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis + ARQ, structlog, pydantic-settings, pytest + pytest-asyncio, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-08-23-tec-122-ingestao-whatsapp-design.md](../specs/2026-08-23-tec-122-ingestao-whatsapp-design.md)

## Global Constraints

- Python **3.12**. Todo I/O é `async`.
- O endpoint `POST /webhooks/whatsapp` **sempre responde 200**, inclusive para assinatura inválida e payload malformado. A Meta re-tenta em não-2xx; um forjador não deve conseguir provocar retry.
- **Nenhuma chamada a provedor de LLM** dentro do ciclo da requisição. Nenhuma dependência de LLM é injetada na rota.
- A mensagem é **commitada no Postgres antes** de qualquer publicação no Redis.
- Descarte por assinatura inválida é **apenas log estruturado** com o motivo — não vira tabela.
- Todo log é JSON via structlog, roteado por `logging.stdlib` para que `caplog` capture nos testes.
- Estados válidos: `RECEIVED` → `QUEUED` → `PROCESSING` → `PROCESSED` | `FAILED`.
- Testes de integração rodam contra **Postgres e Redis reais** subidos pelo `docker-compose.yml` do repo (portas 5433 e 6380, escolhidas para não colidir com instalações locais).
- Fora de escopo, não implemente: dedup por `message_id` (TEC-125), debounce (TEC-128), transcrição de áudio (TEC-131), canal web (TEC-124), CI/CD (TEC-216), observabilidade (TEC-211), DLQ (TEC-209).
- Commits em português, formato `tipo(TEC-122): descrição`.

**Desvio deliberado do spec:** o spec cita um `Makefile`. O ambiente alvo é Windows, onde `make` não é padrão. Os comandos vão documentados no `README.md` e configurados no `pyproject.toml`; nenhum `Makefile` é criado.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `pyproject.toml` | Dependências, config do pytest/ruff | 1 |
| `docker-compose.yml` | Postgres 16 + Redis 7 locais | 1 |
| `.env.example`, `.gitignore`, `README.md` | Onboarding e comandos | 1 |
| `src/mobia/app/config.py` | `Settings` via pydantic-settings | 1 |
| `src/mobia/app/logging.py` | structlog JSON + `correlation_id` | 1 |
| `src/mobia/app/main.py` | Factory FastAPI, `/health` | 1 |
| `tests/conftest.py` | Fixtures de settings, banco, redis, app | 1, 4, 5 |
| `src/mobia/infra/signature.py` | HMAC `X-Hub-Signature-256` | 2 |
| `src/mobia/domain/messages/schemas.py` | Parser do envelope Meta → `ParsedMessage` | 3 |
| `src/mobia/domain/messages/status.py` | `MessageStatus` e conjunto reivindicável | 4 |
| `src/mobia/domain/messages/models.py` | `Base`, `Message` | 4 |
| `src/mobia/infra/db.py` | Engine e sessionmaker async | 4 |
| `alembic/`, `alembic.ini` | Migrations | 4, 8 |
| `src/mobia/infra/queue.py` | Pool ARQ e nome do job | 5 |
| `src/mobia/domain/messages/service.py` | `IngestionService`: persiste → enfileira | 6 |
| `src/mobia/api/routes/whatsapp.py` | `GET` verify + `POST` ingest | 7 |
| `src/mobia/api/deps.py` | Dependências FastAPI | 7 |
| `src/mobia/domain/outbound/models.py` | `OutboundDispatch` | 8 |
| `src/mobia/domain/outbound/port.py` | `OutboundPort`, `GuardedOutbound` | 8 |
| `src/mobia/domain/outbound/noop.py` | `NoopOutbound` | 8 |
| `src/mobia/workers/jobs/process_message.py` | Job com claim idempotente | 9 |
| `src/mobia/workers/jobs/sweep_stalled.py` | Cron de reenfileiramento | 10 |
| `src/mobia/workers/main.py` | `WorkerSettings` do ARQ | 10 |
| `tests/perf/test_ingest_latency.py` | p95 < 300 ms, marcado `perf` | 11 |

---

## Task 1: Esqueleto do projeto, configuração e logging

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `docker-compose.yml`
- Create: `src/mobia/__init__.py`, `src/mobia/app/__init__.py`, `src/mobia/app/config.py`, `src/mobia/app/logging.py`, `src/mobia/app/main.py`
- Test: `tests/conftest.py`, `tests/unit/test_config.py`, `tests/integration/test_health.py`

**Interfaces:**
- Consumes: nada.
- Produces: `Settings` com os campos `database_url: str`, `redis_url: str`, `whatsapp_app_secret: str`, `whatsapp_verify_token: str`, `log_level: str`, `sweep_received_after_seconds: int`, `sweep_inflight_after_seconds: int`, `sweep_max_attempts: int`; `get_settings() -> Settings` (cacheada, com `.cache_clear()`); `configure_logging(level: str) -> None`; `correlation_id: ContextVar[str]`; `create_app() -> FastAPI`.

- [ ] **Step 1: Criar a árvore de diretórios e os arquivos vazios de pacote**

```bash
mkdir -p src/mobia/app src/mobia/api/routes src/mobia/domain/messages src/mobia/domain/outbound src/mobia/infra src/mobia/workers/jobs
mkdir -p tests/unit tests/integration tests/features tests/perf
for d in src/mobia src/mobia/app src/mobia/api src/mobia/api/routes src/mobia/domain src/mobia/domain/messages src/mobia/domain/outbound src/mobia/infra src/mobia/workers src/mobia/workers/jobs tests tests/unit tests/integration tests/features tests/perf; do touch "$d/__init__.py"; done
rm tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/features/__init__.py tests/perf/__init__.py
```

- [ ] **Step 2: Escrever o `pyproject.toml`**

```toml
[project]
name = "mobia"
version = "0.1.0"
description = "Agente de IA para qualificacao de leads imobiliarios"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "arq>=0.26",
    "redis>=5.2",
    "structlog>=24.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.28",
    "ruff>=0.8",
    "mypy>=1.13",
]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-m 'not perf'"
markers = [
    "perf: teste de latencia, roda so sob demanda com -m perf",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 3: Escrever `.gitignore`, `.env.example` e `docker-compose.yml`**

`.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/
```

`.env.example`:

```dotenv
DATABASE_URL=postgresql+asyncpg://mobia:mobia@localhost:5433/mobia
REDIS_URL=redis://localhost:6380/0
WHATSAPP_APP_SECRET=dev-app-secret
WHATSAPP_VERIFY_TOKEN=dev-verify-token
LOG_LEVEL=INFO
```

`docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: mobia
      POSTGRES_PASSWORD: mobia
      POSTGRES_DB: mobia
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mobia"]
      interval: 2s
      timeout: 3s
      retries: 20

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "6380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 3s
      retries: 20
```

- [ ] **Step 4: Escrever o teste de configuração que vai falhar**

`tests/unit/test_config.py`:

```python
import pytest

from mobia.app.config import Settings, get_settings


def test_settings_le_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "segredo-do-teste")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6390/1")
    settings = Settings(_env_file=None)
    assert settings.whatsapp_app_secret == "segredo-do-teste"
    assert settings.redis_url == "redis://localhost:6390/1"


def test_get_settings_e_cacheada() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()


def test_limiares_do_sweeper_tem_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.sweep_received_after_seconds == 30
    assert settings.sweep_inflight_after_seconds == 300
    assert settings.sweep_max_attempts == 5
```

- [ ] **Step 5: Rodar o teste e confirmar que falha**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia'` (o ambiente ainda não foi criado — o próximo passo resolve).

- [ ] **Step 6: Criar o ambiente virtual e instalar**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e ".[dev]"
```

Em Linux/macOS o binário é `.venv/bin/python`. Todos os comandos seguintes assumem esse interpretador; ative o venv ou prefixe os comandos.

Rodar de novo: `python -m pytest tests/unit/test_config.py -v` → agora FAIL com `ModuleNotFoundError: No module named 'mobia.app.config'`.

- [ ] **Step 7: Implementar `src/mobia/app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://mobia:mobia@localhost:5433/mobia"
    redis_url: str = "redis://localhost:6380/0"

    whatsapp_app_secret: str = "dev-app-secret"
    whatsapp_verify_token: str = "dev-verify-token"

    log_level: str = "INFO"

    sweep_received_after_seconds: int = 30
    sweep_inflight_after_seconds: int = 300
    sweep_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 8: Rodar o teste de configuração e confirmar que passa**

Run: `python -m pytest tests/unit/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 9: Implementar `src/mobia/app/logging.py`**

O `logger_factory` é o da stdlib de propósito: o JSON renderizado vira a mensagem de um `LogRecord`, e é assim que `caplog` consegue asserir sobre eventos nos testes da Task 7.

```python
import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def _add_correlation_id(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    value = correlation_id.get()
    if value:
        event_dict["correlation_id"] = value
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 10: Escrever o teste do health check que vai falhar**

`tests/integration/test_health.py`:

```python
from httpx import ASGITransport, AsyncClient

from mobia.app.main import create_app


async def test_health_responde_ok() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 11: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_health.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.app.main'`.

- [ ] **Step 12: Implementar `src/mobia/app/main.py`**

```python
from fastapi import FastAPI

from mobia.app.config import get_settings
from mobia.app.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="mobIA", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 13: Rodar e confirmar que passa**

Run: `python -m pytest -v`
Expected: 4 passed.

- [ ] **Step 14: Escrever o `README.md`**

````markdown
# mobIA

Agente de IA para qualificação de leads imobiliários.

## Ambiente local

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
cp .env.example .env
docker compose up -d
```

## Comandos

| O quê | Comando |
|---|---|
| Testes | `python -m pytest` |
| Teste de latência | `python -m pytest -m perf` |
| Lint | `python -m ruff check src tests` |
| Formatação | `python -m ruff format src tests` |
| Migrations | `python -m alembic upgrade head` |
| API | `python -m uvicorn mobia.app.main:app --reload` |
| Worker | `python -m arq mobia.workers.main.WorkerSettings` |
````

- [ ] **Step 15: Commit**

```bash
git add pyproject.toml .gitignore .env.example README.md docker-compose.yml src tests
git commit -m "feat(TEC-122): esqueleto do projeto, configuracao e logging estruturado"
```

---

## Task 2: Verificação da assinatura X-Hub-Signature-256

**Files:**
- Create: `src/mobia/infra/signature.py`
- Test: `tests/unit/test_signature.py`

**Interfaces:**
- Consumes: nada.
- Produces: `SIGNATURE_HEADER: str` (`"X-Hub-Signature-256"`); `compute_signature(app_secret: str, body: bytes) -> str` devolvendo `"sha256=<hex>"`; `is_valid_signature(app_secret: str, body: bytes, header_value: str | None) -> bool`.

- [ ] **Step 1: Escrever os testes que vão falhar**

`tests/unit/test_signature.py`:

```python
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature, is_valid_signature

SECRET = "segredo-do-app"
BODY = b'{"object":"whatsapp_business_account"}'


def test_nome_do_header() -> None:
    assert SIGNATURE_HEADER == "X-Hub-Signature-256"


def test_assinatura_tem_prefixo_sha256() -> None:
    assinatura = compute_signature(SECRET, BODY)
    assert assinatura.startswith("sha256=")
    assert len(assinatura) == len("sha256=") + 64


def test_assinatura_valida_e_aceita() -> None:
    assert is_valid_signature(SECRET, BODY, compute_signature(SECRET, BODY)) is True


def test_assinatura_forjada_e_recusada() -> None:
    assert is_valid_signature(SECRET, BODY, "sha256=" + "0" * 64) is False


def test_assinatura_ausente_e_recusada() -> None:
    assert is_valid_signature(SECRET, BODY, None) is False
    assert is_valid_signature(SECRET, BODY, "") is False


def test_assinatura_sem_prefixo_e_recusada() -> None:
    sem_prefixo = compute_signature(SECRET, BODY).removeprefix("sha256=")
    assert is_valid_signature(SECRET, BODY, sem_prefixo) is False


def test_corpo_alterado_invalida_a_assinatura() -> None:
    assinatura = compute_signature(SECRET, BODY)
    assert is_valid_signature(SECRET, BODY + b" ", assinatura) is False


def test_segredo_errado_invalida_a_assinatura() -> None:
    assinatura = compute_signature("outro-segredo", BODY)
    assert is_valid_signature(SECRET, BODY, assinatura) is False
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_signature.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.infra.signature'`.

- [ ] **Step 3: Implementar `src/mobia/infra/signature.py`**

```python
import hashlib
import hmac

SIGNATURE_HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="


def compute_signature(app_secret: str, body: bytes) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"


def is_valid_signature(app_secret: str, body: bytes, header_value: str | None) -> bool:
    if not header_value or not header_value.startswith(_PREFIX):
        return False
    return hmac.compare_digest(compute_signature(app_secret, body), header_value)
```

`hmac.compare_digest` é obrigatório aqui: comparação com `==` vaza a assinatura correta por timing.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_signature.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/infra/signature.py tests/unit/test_signature.py
git commit -m "feat(TEC-122): verificacao HMAC da assinatura X-Hub-Signature-256"
```

---

## Task 3: Parser do envelope da Meta

**Files:**
- Create: `src/mobia/domain/messages/schemas.py`
- Test: `tests/unit/test_meta_envelope.py`

**Interfaces:**
- Consumes: nada.
- Produces: dataclass congelada `ParsedMessage` com os campos `provider_message_id: str`, `sender_external_id: str`, `recipient_external_id: str`, `content_type: str`, `text_body: str | None`, `raw_payload: dict[str, Any]`; `parse_meta_envelope(payload: dict[str, Any]) -> list[ParsedMessage]`.

O `raw_payload` guarda o objeto da mensagem individual, não o envelope inteiro — é a granularidade que o reprocesso por linha precisa.

- [ ] **Step 1: Escrever os testes que vão falhar**

`tests/unit/test_meta_envelope.py`:

```python
from typing import Any

from mobia.domain.messages.schemas import ParsedMessage, parse_meta_envelope


def envelope(*messages: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5511999998888",
                                "phone_number_id": "222222222",
                            },
                            "contacts": [{"wa_id": "5511911112222"}],
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


MENSAGEM_TEXTO = {
    "from": "5511911112222",
    "id": "wamid.TEXTO",
    "timestamp": "1755900000",
    "type": "text",
    "text": {"body": "Oi, procuro apartamento de 2 quartos"},
}


def test_extrai_mensagem_de_texto() -> None:
    resultado = parse_meta_envelope(envelope(MENSAGEM_TEXTO))
    assert len(resultado) == 1
    msg = resultado[0]
    assert isinstance(msg, ParsedMessage)
    assert msg.provider_message_id == "wamid.TEXTO"
    assert msg.sender_external_id == "5511911112222"
    assert msg.recipient_external_id == "222222222"
    assert msg.content_type == "text"
    assert msg.text_body == "Oi, procuro apartamento de 2 quartos"
    assert msg.raw_payload == MENSAGEM_TEXTO


def test_audio_e_registrado_sem_corpo_de_texto() -> None:
    audio = {
        "from": "5511911112222",
        "id": "wamid.AUDIO",
        "type": "audio",
        "audio": {"id": "media-1", "mime_type": "audio/ogg"},
    }
    resultado = parse_meta_envelope(envelope(audio))
    assert len(resultado) == 1
    assert resultado[0].content_type == "audio"
    assert resultado[0].text_body is None


def test_varias_mensagens_no_mesmo_envelope() -> None:
    outra = dict(MENSAGEM_TEXTO, id="wamid.SEGUNDA")
    resultado = parse_meta_envelope(envelope(MENSAGEM_TEXTO, outra))
    assert [m.provider_message_id for m in resultado] == ["wamid.TEXTO", "wamid.SEGUNDA"]


def test_notificacao_de_status_nao_gera_mensagem() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "statuses": [{"id": "wamid.X", "status": "delivered"}],
                        },
                    }
                ],
            }
        ],
    }
    assert parse_meta_envelope(payload) == []


def test_payload_vazio_ou_desconhecido_nao_quebra() -> None:
    assert parse_meta_envelope({}) == []
    assert parse_meta_envelope({"entry": None}) == []
    assert parse_meta_envelope({"entry": [{"changes": None}]}) == []


def test_mensagem_sem_id_ou_remetente_e_ignorada() -> None:
    sem_id = {"from": "5511911112222", "type": "text", "text": {"body": "oi"}}
    sem_remetente = {"id": "wamid.SEM_FROM", "type": "text", "text": {"body": "oi"}}
    assert parse_meta_envelope(envelope(sem_id, sem_remetente)) == []


def test_tipo_ausente_vira_unknown() -> None:
    resultado = parse_meta_envelope(envelope({"from": "5511911112222", "id": "wamid.Z"}))
    assert resultado[0].content_type == "unknown"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/unit/test_meta_envelope.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.messages.schemas'`.

- [ ] **Step 3: Implementar `src/mobia/domain/messages/schemas.py`**

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedMessage:
    provider_message_id: str
    sender_external_id: str
    recipient_external_id: str
    content_type: str
    text_body: str | None
    raw_payload: dict[str, Any]


def parse_meta_envelope(payload: dict[str, Any]) -> list[ParsedMessage]:
    """Extrai as mensagens recebidas de um envelope de webhook da Meta.

    Tolera estrutura ausente ou desconhecida devolvendo lista vazia: notificacoes
    de status e payloads que nao contem `messages[]` nao viram linha.
    """
    parsed: list[ParsedMessage] = []

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            recipient = str(metadata.get("phone_number_id") or "")

            for message in value.get("messages") or []:
                provider_message_id = message.get("id")
                sender = message.get("from")
                if not provider_message_id or not sender:
                    continue

                content_type = message.get("type") or "unknown"
                text_body = None
                if content_type == "text":
                    text_body = (message.get("text") or {}).get("body")

                parsed.append(
                    ParsedMessage(
                        provider_message_id=str(provider_message_id),
                        sender_external_id=str(sender),
                        recipient_external_id=recipient,
                        content_type=str(content_type),
                        text_body=text_body,
                        raw_payload=message,
                    )
                )

    return parsed
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/unit/test_meta_envelope.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/domain/messages/schemas.py tests/unit/test_meta_envelope.py
git commit -m "feat(TEC-122): parser do envelope de webhook da Meta"
```

---

## Task 4: Modelo `Message`, camada de banco e migration inicial

**Files:**
- Create: `src/mobia/domain/messages/status.py`, `src/mobia/domain/messages/models.py`, `src/mobia/infra/db.py`
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_criar_messages.py`
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_message_model.py`

**Interfaces:**
- Consumes: `Settings.database_url` da Task 1.
- Produces: `MessageStatus` (StrEnum com `RECEIVED`, `QUEUED`, `PROCESSING`, `PROCESSED`, `FAILED`); `CLAIMABLE_STATUSES: tuple[MessageStatus, ...]`; `Base` (DeclarativeBase); modelo `Message`; `get_engine() -> AsyncEngine`; `get_sessionmaker() -> async_sessionmaker[AsyncSession]`; `dispose_engine() -> None`.

- [ ] **Step 1: Subir a infra local**

```bash
docker compose up -d
docker compose ps
```

Expected: `postgres` e `redis` com estado `healthy`.

- [ ] **Step 2: Escrever o teste de modelo que vai falhar**

`tests/integration/test_message_model.py`:

```python
import uuid

from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus


def test_statuses_reivindicaveis() -> None:
    assert CLAIMABLE_STATUSES == (
        MessageStatus.RECEIVED,
        MessageStatus.QUEUED,
        MessageStatus.PROCESSING,
    )


async def test_persiste_mensagem_com_defaults(session) -> None:
    message = Message(
        channel="whatsapp",
        provider_message_id="wamid.PERSIST",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="oi",
        raw_payload={"id": "wamid.PERSIST", "type": "text"},
        status=MessageStatus.RECEIVED,
    )
    session.add(message)
    await session.commit()

    resultado = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.PERSIST")
    )
    assert resultado is not None
    assert isinstance(resultado.id, uuid.UUID)
    assert resultado.status == MessageStatus.RECEIVED
    assert resultado.attempts == 0
    assert resultado.received_at is not None
    assert resultado.queued_at is None
    assert resultado.processed_at is None
    assert resultado.last_error is None
    assert resultado.raw_payload["type"] == "text"


async def test_provider_message_id_ainda_nao_e_unico(session) -> None:
    """A UNIQUE de dedup entra no TEC-125; hoje duas linhas iguais convivem."""
    for _ in range(2):
        session.add(
            Message(
                channel="whatsapp",
                provider_message_id="wamid.DUPLICADO",
                sender_external_id="5511911112222",
                recipient_external_id="222222222",
                content_type="text",
                text_body="oi",
                raw_payload={},
                status=MessageStatus.RECEIVED,
            )
        )
    await session.commit()

    linhas = (
        await session.scalars(
            select(Message).where(Message.provider_message_id == "wamid.DUPLICADO")
        )
    ).all()
    assert len(linhas) == 2
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_message_model.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.messages.models'`.

- [ ] **Step 4: Implementar `src/mobia/domain/messages/status.py`**

```python
from enum import StrEnum


class MessageStatus(StrEnum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


CLAIMABLE_STATUSES: tuple[MessageStatus, ...] = (
    MessageStatus.RECEIVED,
    MessageStatus.QUEUED,
    MessageStatus.PROCESSING,
)
```

- [ ] **Step 5: Implementar `src/mobia/domain/messages/models.py`**

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mobia.domain.messages.status import MessageStatus


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MessageStatus.RECEIVED
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_messages_status_received_at", "status", "received_at"),
        Index("ix_messages_provider_message_id", "provider_message_id"),
    )
```

- [ ] **Step 6: Implementar `src/mobia/infra/db.py`**

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from mobia.app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
```

- [ ] **Step 7: Inicializar o Alembic e apontar para o metadata**

```bash
python -m alembic init -t async alembic
```

Em `alembic.ini`, deixe `sqlalchemy.url` vazio (a URL vem das Settings):

```ini
sqlalchemy.url =
```

Substitua o topo de `alembic/env.py` pelo bloco abaixo, mantendo o resto do arquivo gerado:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from mobia.app.config import get_settings
from mobia.domain.messages.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
```

- [ ] **Step 8: Escrever a migration `alembic/versions/0001_criar_messages.py`**

```python
"""cria a tabela messages

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("sender_external_id", sa.String(64), nullable=False),
        sa.Column("recipient_external_id", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_messages_status_received_at", "messages", ["status", "received_at"]
    )
    op.create_index(
        "ix_messages_provider_message_id", "messages", ["provider_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_messages_provider_message_id", table_name="messages")
    op.drop_index("ix_messages_status_received_at", table_name="messages")
    op.drop_table("messages")
```

- [ ] **Step 9: Adicionar as fixtures de banco em `tests/conftest.py`**

O arquivo passa a conter:

```python
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.infra.db import dispose_engine, get_sessionmaker

TABELAS = ("outbound_dispatches", "messages")


@pytest.fixture(scope="session", autouse=True)
def migrar_banco() -> None:
    """Aplica as migrations uma vez por sessao de teste.

    Roda o Alembic de verdade em vez de `metadata.create_all` para que as
    migrations sejam exercitadas pelos testes.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
async def banco_limpo(migrar_banco: None) -> AsyncIterator[None]:
    """Trunca antes do teste e descarta o engine depois.

    Truncar na entrada (nao na saida) evita disputar lock com a sessao do teste.
    O dispose no fim e obrigatorio: cada teste roda no seu proprio event loop e
    conexoes asyncpg nao sobrevivem a troca de loop.
    """
    async with get_sessionmaker()() as sessao:
        for tabela in TABELAS:
            existe = await sessao.scalar(text(f"SELECT to_regclass('public.{tabela}')"))
            if existe:
                await sessao.execute(text(f"TRUNCATE TABLE {tabela} CASCADE"))
        await sessao.commit()
    yield
    await dispose_engine()


@pytest.fixture
async def session(banco_limpo: None) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as sessao:
        yield sessao


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()
```

`TABELAS` já lista `outbound_dispatches`, que a Task 8 cria; o `to_regclass` faz o truncate ignorar tabela ainda inexistente.

- [ ] **Step 10: Rodar e confirmar que passa**

Run: `python -m pytest tests/integration/test_message_model.py -v`
Expected: 3 passed.

- [ ] **Step 11: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: 22 passed.

- [ ] **Step 12: Commit**

```bash
git add alembic alembic.ini src/mobia/domain/messages src/mobia/infra/db.py tests/conftest.py tests/integration/test_message_model.py
git commit -m "feat(TEC-122): modelo Message, camada async de banco e migration inicial"
```

---

## Task 5: Pool do Redis e enfileiramento ARQ

**Files:**
- Create: `src/mobia/infra/queue.py`
- Modify: `tests/conftest.py`
- Test: `tests/integration/test_queue.py`

**Interfaces:**
- Consumes: `Settings.redis_url` da Task 1.
- Produces: `PROCESS_MESSAGE_JOB: str` (`"process_message"`); `redis_settings() -> RedisSettings`; `create_redis_pool() -> ArqRedis`; `enqueue_process_message(pool: ArqRedis, message_id: uuid.UUID) -> bool` (devolve `False` quando o ARQ recusa o job por `_job_id` já existente).

O `_job_id` é derivado do `message_id`, então o mesmo id nunca entra duas vezes na fila enquanto o job estiver pendente — é o que impede o sweeper de multiplicar trabalho.

- [ ] **Step 1: Escrever o teste que vai falhar**

`tests/integration/test_queue.py`:

```python
import uuid

from mobia.infra.queue import PROCESS_MESSAGE_JOB, enqueue_process_message


async def test_enfileira_job_de_processamento(redis_pool) -> None:
    message_id = uuid.uuid4()
    assert await enqueue_process_message(redis_pool, message_id) is True

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1
    assert jobs[0].function == PROCESS_MESSAGE_JOB
    assert jobs[0].args == (str(message_id),)


async def test_mesmo_id_nao_entra_duas_vezes_na_fila(redis_pool) -> None:
    message_id = uuid.uuid4()
    assert await enqueue_process_message(redis_pool, message_id) is True
    assert await enqueue_process_message(redis_pool, message_id) is False
    assert len(await redis_pool.queued_jobs()) == 1
```

- [ ] **Step 2: Adicionar a fixture `redis_pool` em `tests/conftest.py`**

Acrescente ao final do arquivo:

```python
from mobia.infra.queue import create_redis_pool  # noqa: E402


@pytest.fixture
async def redis_pool() -> AsyncIterator["ArqRedis"]:  # noqa: F821
    pool = await create_redis_pool()
    await pool.flushdb()
    try:
        yield pool
    finally:
        await pool.flushdb()
        await pool.aclose()
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_queue.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.infra.queue'`.

- [ ] **Step 4: Implementar `src/mobia/infra/queue.py`**

```python
import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from mobia.app.config import get_settings

PROCESS_MESSAGE_JOB = "process_message"
SWEEP_STALLED_JOB = "sweep_stalled"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def create_redis_pool() -> ArqRedis:
    return await create_pool(redis_settings())


async def enqueue_process_message(pool: ArqRedis, message_id: uuid.UUID) -> bool:
    """Enfileira o processamento de uma mensagem.

    Usa `_job_id` derivado do message_id: o ARQ recusa o segundo enqueue enquanto
    o job estiver pendente, entao o sweeper nao multiplica trabalho. Devolve False
    quando o job ja estava na fila.
    """
    job = await pool.enqueue_job(
        PROCESS_MESSAGE_JOB, str(message_id), _job_id=f"msg:{message_id}"
    )
    return job is not None
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `python -m pytest tests/integration/test_queue.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/infra/queue.py tests/conftest.py tests/integration/test_queue.py
git commit -m "feat(TEC-122): pool do Redis e enfileiramento idempotente no ARQ"
```

---

## Task 6: Serviço de ingestão — persiste, depois enfileira

**Files:**
- Create: `src/mobia/domain/messages/service.py`
- Test: `tests/integration/test_ingestion_service.py`

**Interfaces:**
- Consumes: `ParsedMessage` (Task 3), `Message`/`MessageStatus` (Task 4), `enqueue_process_message` (Task 5).
- Produces: `IngestionService(session_factory: async_sessionmaker[AsyncSession], queue: ArqRedis | None)` com `async def ingest(self, parsed: list[ParsedMessage], channel: str = "whatsapp") -> list[uuid.UUID]`.

A ordem é a regra de negócio inteira: **insert + commit primeiro**, enqueue depois. Falha do Redis é capturada e logada, nunca propagada — a linha fica `RECEIVED` e a Task 10 a recupera.

- [ ] **Step 1: Escrever os testes que vão falhar**

`tests/integration/test_ingestion_service.py`:

```python
import pytest
from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker


def parsed(provider_message_id: str = "wamid.SERVICO") -> ParsedMessage:
    return ParsedMessage(
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="quero agendar visita",
        raw_payload={"id": provider_message_id, "type": "text"},
    )


class FilaQuebrada:
    async def enqueue_job(self, *args, **kwargs):
        raise ConnectionError("redis fora do ar")


async def test_persiste_e_enfileira(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    ids = await service.ingest([parsed()])

    assert len(ids) == 1
    linha = await session.get(Message, ids[0])
    assert linha is not None
    assert linha.channel == "whatsapp"
    assert linha.status == MessageStatus.QUEUED
    assert linha.queued_at is not None
    assert len(await redis_pool.queued_jobs()) == 1


async def test_redis_fora_do_ar_nao_perde_a_mensagem(session, caplog) -> None:
    service = IngestionService(get_sessionmaker(), FilaQuebrada())

    with caplog.at_level("WARNING"):
        ids = await service.ingest([parsed("wamid.SEM_REDIS")])

    linha = await session.get(Message, ids[0])
    assert linha is not None, "a mensagem tem de existir mesmo sem fila"
    assert linha.status == MessageStatus.RECEIVED
    assert linha.queued_at is None
    assert "enqueue.failed" in caplog.text


async def test_sem_fila_configurada_a_mensagem_fica_received(session) -> None:
    service = IngestionService(get_sessionmaker(), None)

    ids = await service.ingest([parsed("wamid.SEM_FILA")])

    linha = await session.get(Message, ids[0])
    assert linha.status == MessageStatus.RECEIVED


async def test_lote_com_varias_mensagens(session, redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)

    ids = await service.ingest([parsed("wamid.A"), parsed("wamid.B")])

    assert len(ids) == 2
    linhas = (await session.scalars(select(Message))).all()
    assert {linha.provider_message_id for linha in linhas} == {"wamid.A", "wamid.B"}
    assert len(await redis_pool.queued_jobs()) == 2


async def test_lista_vazia_nao_faz_nada(redis_pool) -> None:
    service = IngestionService(get_sessionmaker(), redis_pool)
    assert await service.ingest([]) == []
    assert await redis_pool.queued_jobs() == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_ingestion_service.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.messages.service'`.

- [ ] **Step 3: Implementar `src/mobia/domain/messages/service.py`**

```python
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.status import MessageStatus
from mobia.infra.queue import enqueue_process_message

log = structlog.get_logger(__name__)


class IngestionService:
    """Persiste a mensagem recebida e so entao a enfileira.

    A ordem importa: a linha commitada no Postgres e a garantia de nao-perda.
    O enqueue e otimista e sua falha nao propaga -- a mensagem fica em RECEIVED
    e o sweeper (workers/jobs/sweep_stalled.py) a recupera.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: Any | None,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue

    async def ingest(
        self, parsed: list[ParsedMessage], channel: str = "whatsapp"
    ) -> list[uuid.UUID]:
        if not parsed:
            return []

        message_ids = await self._persist(parsed, channel)
        for message_id in message_ids:
            await self._try_enqueue(message_id)
        return message_ids

    async def _persist(self, parsed: list[ParsedMessage], channel: str) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            messages = [
                Message(
                    id=uuid.uuid4(),
                    channel=channel,
                    provider_message_id=item.provider_message_id,
                    sender_external_id=item.sender_external_id,
                    recipient_external_id=item.recipient_external_id,
                    content_type=item.content_type,
                    text_body=item.text_body,
                    raw_payload=item.raw_payload,
                    status=MessageStatus.RECEIVED,
                )
                for item in parsed
            ]
            session.add_all(messages)
            await session.commit()

        message_ids = [message.id for message in messages]
        log.info("message.received", message_ids=[str(i) for i in message_ids], channel=channel)
        return message_ids

    async def _try_enqueue(self, message_id: uuid.UUID) -> None:
        if self._queue is None:
            log.warning("enqueue.failed", message_id=str(message_id), reason="no_queue")
            return
        try:
            await enqueue_process_message(self._queue, message_id)
        except Exception as exc:
            log.warning(
                "enqueue.failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        async with self._session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == message_id)
                .values(status=MessageStatus.QUEUED, queued_at=datetime.now(UTC))
            )
            await session.commit()
        log.info("message.queued", message_id=str(message_id))
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/integration/test_ingestion_service.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/domain/messages/service.py tests/integration/test_ingestion_service.py
git commit -m "feat(TEC-122): servico de ingestao persiste antes de enfileirar"
```

---

## Task 7: Rota do webhook — cenários Gherkin 1 e 2

**Files:**
- Create: `src/mobia/api/deps.py`, `src/mobia/api/routes/whatsapp.py`
- Modify: `src/mobia/app/main.py`, `tests/conftest.py`
- Test: `tests/features/test_recepcao_de_mensagem.py`

**Interfaces:**
- Consumes: `is_valid_signature`/`SIGNATURE_HEADER` (Task 2), `parse_meta_envelope` (Task 3), `IngestionService` (Task 6), `create_redis_pool` (Task 5).
- Produces: `router: APIRouter` com `GET /webhooks/whatsapp` e `POST /webhooks/whatsapp`; `get_ingestion_service(request: Request) -> IngestionService`; `create_app()` passa a montar o router e a abrir/fechar o pool do Redis no lifespan, guardando-o em `app.state.redis_pool`.

O `LLMPort` fake do cenário 1 não precisa existir como código de produção: o teste asserta a ausência de LLM verificando que nenhum módulo de LLM está registrado nas dependências da rota. Como nenhum existe ainda, a asserção é sobre o `app.state` e o tempo de resposta.

- [ ] **Step 1: Escrever os testes dos cenários que vão falhar**

`tests/features/test_recepcao_de_mensagem.py`:

```python
"""Cenarios Gherkin de TEC-122.

Funcionalidade: Recepcao de mensagem do WhatsApp
"""

import json

import pytest
from sqlalchemy import func, select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

ENVELOPE = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "111111111",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "222222222"},
                        "messages": [
                            {
                                "from": "5511911112222",
                                "id": "wamid.GHERKIN",
                                "timestamp": "1755900000",
                                "type": "text",
                                "text": {"body": "Boa noite, ainda tem o 2 quartos?"},
                            }
                        ],
                    },
                }
            ],
        }
    ],
}


def corpo_assinado(secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(ENVELOPE).encode("utf-8")
    return body, {
        SIGNATURE_HEADER: compute_signature(secret, body),
        "Content-Type": "application/json",
    }


async def test_confirmar_recebimento_antes_de_processar(
    client, session, redis_pool, settings
) -> None:
    """Cenario: Confirmar recebimento antes de processar."""
    body, headers = corpo_assinado(settings.whatsapp_app_secret)

    response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200

    linha = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.GHERKIN")
    )
    assert linha is not None
    assert linha.status == MessageStatus.QUEUED
    assert linha.text_body == "Boa noite, ainda tem o 2 quartos?"

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1, "a mensagem tem de estar na fila de processamento"

    import mobia.api.routes.whatsapp as rota

    assert not [nome for nome in dir(rota) if "llm" in nome.lower()], (
        "nenhuma dependencia de LLM pode existir no ciclo da requisicao"
    )


async def test_descartar_payload_com_assinatura_invalida(
    client, session, redis_pool, caplog
) -> None:
    """Cenario: Descartar payload com assinatura invalida."""
    body = json.dumps(ENVELOPE).encode("utf-8")
    headers = {SIGNATURE_HEADER: "sha256=" + "f" * 64, "Content-Type": "application/json"}

    with caplog.at_level("WARNING"):
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    assert await redis_pool.queued_jobs() == []
    assert "webhook.rejected" in caplog.text
    assert "invalid_signature" in caplog.text


async def test_assinatura_ausente_tambem_e_descartada(client, session, caplog) -> None:
    body = json.dumps(ENVELOPE).encode("utf-8")

    with caplog.at_level("WARNING"):
        response = await client.post(
            "/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    assert "missing_or_invalid_signature" in caplog.text or "invalid_signature" in caplog.text


async def test_json_malformado_nao_derruba_o_endpoint(client, session, settings, caplog) -> None:
    body = b"{nao e json"
    headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

    with caplog.at_level("WARNING"):
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    assert "malformed_json" in caplog.text


async def test_notificacao_de_status_nao_vira_mensagem(client, session, settings) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "statuses": [{"id": "wamid.X", "status": "read"}],
                        }
                    }
                ]
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

    response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize(
    ("params", "esperado_status", "esperado_corpo"),
    [
        (
            {"hub.mode": "subscribe", "hub.verify_token": "dev-verify-token", "hub.challenge": "42"},
            200,
            "42",
        ),
        (
            {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"},
            403,
            None,
        ),
        ({"hub.mode": "unsubscribe", "hub.challenge": "42"}, 403, None),
    ],
)
async def test_handshake_de_verificacao(
    client, params, esperado_status, esperado_corpo
) -> None:
    response = await client.get("/webhooks/whatsapp", params=params)
    assert response.status_code == esperado_status
    if esperado_corpo is not None:
        assert response.text == esperado_corpo
```

- [ ] **Step 2: Adicionar a fixture `client` em `tests/conftest.py`**

Acrescente ao final do arquivo:

```python
from httpx import ASGITransport, AsyncClient  # noqa: E402

from mobia.app.main import create_app  # noqa: E402


@pytest.fixture
async def client(banco_limpo: None, redis_pool) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.redis_pool = redis_pool
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
```

Injetar o pool direto em `app.state` faz o teste usar a mesma conexão que a fixture limpa, sem depender do lifespan.

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `python -m pytest tests/features/test_recepcao_de_mensagem.py -v`
Expected: FAIL — todas as requisições devolvem 404, porque o router ainda não existe.

- [ ] **Step 4: Implementar `src/mobia/api/deps.py`**

```python
from fastapi import Request

from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker


def get_ingestion_service(request: Request) -> IngestionService:
    return IngestionService(get_sessionmaker(), getattr(request.app.state, "redis_pool", None))
```

- [ ] **Step 5: Implementar `src/mobia/api/routes/whatsapp.py`**

```python
import hashlib
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from mobia.app.config import Settings, get_settings
from mobia.app.logging import correlation_id
from mobia.api.deps import get_ingestion_service
from mobia.domain.messages.schemas import parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.infra.signature import SIGNATURE_HEADER, is_valid_signature

log = structlog.get_logger(__name__)
router = APIRouter(tags=["whatsapp"])


@router.get("/webhooks/whatsapp")
async def verify(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    """Handshake de registro do webhook na Meta."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.whatsapp_verify_token
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))

    log.warning("webhook.verify_rejected", reason="invalid_verify_token")
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/webhooks/whatsapp")
async def ingest(
    request: Request,
    settings: Settings = Depends(get_settings),
    service: IngestionService = Depends(get_ingestion_service),
) -> Response:
    """Recebe, valida, persiste e enfileira.

    Responde 200 em todos os caminhos, inclusive na recusa: a Meta re-tenta em
    nao-2xx, e quem forja assinatura nao deve conseguir provocar retry.
    Nenhuma chamada a provedor de LLM ocorre aqui.
    """
    correlation_id.set(str(uuid.uuid4()))

    body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)

    if not is_valid_signature(settings.whatsapp_app_secret, body, signature):
        log.warning(
            "webhook.rejected",
            reason="invalid_signature" if signature else "missing_or_invalid_signature",
            remote_ip=request.client.host if request.client else None,
            payload_sha256=hashlib.sha256(body).hexdigest(),
        )
        return Response(status_code=200)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        log.warning(
            "webhook.rejected",
            reason="malformed_json",
            payload_sha256=hashlib.sha256(body).hexdigest(),
        )
        return Response(status_code=200)

    parsed = parse_meta_envelope(payload)
    if not parsed:
        log.info("webhook.ignored", reason="no_inbound_messages")
        return Response(status_code=200)

    await service.ingest(parsed)
    return Response(status_code=200)
```

- [ ] **Step 6: Montar o router e o lifespan em `src/mobia/app/main.py`**

Substitua o arquivo inteiro:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mobia.api.routes.whatsapp import router as whatsapp_router
from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.infra.db import dispose_engine
from mobia.infra.queue import create_redis_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not hasattr(app.state, "redis_pool"):
        app.state.redis_pool = await create_redis_pool()
        app.state.owns_redis_pool = True
    yield
    if getattr(app.state, "owns_redis_pool", False):
        await app.state.redis_pool.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="mobIA", version="0.1.0", lifespan=lifespan)
    app.include_router(whatsapp_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 7: Rodar os cenários e confirmar que passam**

Run: `python -m pytest tests/features/test_recepcao_de_mensagem.py -v`
Expected: 8 passed (5 testes + 3 parametrizações do handshake).

- [ ] **Step 8: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: 37 passed.

- [ ] **Step 9: Commit**

```bash
git add src/mobia/api src/mobia/app/main.py tests/conftest.py tests/features/test_recepcao_de_mensagem.py
git commit -m "feat(TEC-122): endpoint de ingestao do WhatsApp com verificacao de assinatura"
```

---

## Task 8: Guarda de idempotência de saída

**Files:**
- Create: `src/mobia/domain/outbound/models.py`, `src/mobia/domain/outbound/port.py`, `src/mobia/domain/outbound/noop.py`
- Create: `alembic/versions/0002_criar_outbound_dispatches.py`
- Test: `tests/integration/test_outbound_guard.py`

**Interfaces:**
- Consumes: `Base` de `mobia.domain.messages.models` (Task 4).
- Produces: modelo `OutboundDispatch` (`id`, `message_id`, `kind`, `created_at`, `UNIQUE (message_id, kind)`); `OutboundPort` (Protocol com `async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool`); `GuardedOutbound` (classe base com `_deliver` abstrato); `NoopOutbound`.

**Semântica deliberada: reservar, depois entregar.** `send()` insere a linha de reserva e commita *antes* do efeito externo. Queda entre a reserva e a entrega perde aquele envio; queda depois dela nunca duplica. O critério de aceite exige "nenhuma resposta duplicada", então a troca é essa, e é a certa.

- [ ] **Step 1: Escrever os testes que vão falhar**

`tests/integration/test_outbound_guard.py`:

```python
import uuid
from typing import Any

from sqlalchemy import func, select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.noop import NoopOutbound
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.db import get_sessionmaker


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[tuple[uuid.UUID, str]] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregas.append((message_id, kind))


async def criar_mensagem(session) -> uuid.UUID:
    message = Message(
        id=uuid.uuid4(),
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="oi",
        raw_payload={},
        status=MessageStatus.RECEIVED,
    )
    session.add(message)
    await session.commit()
    return message.id


async def test_primeiro_envio_reserva_e_entrega(session) -> None:
    message_id = await criar_mensagem(session)
    outbound = OutboundEspiao(get_sessionmaker())

    assert await outbound.send(message_id, "ack", {}) is True
    assert outbound.entregas == [(message_id, "ack")]

    total = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert total == 1


async def test_segundo_envio_do_mesmo_par_e_suprimido(session, caplog) -> None:
    message_id = await criar_mensagem(session)
    outbound = OutboundEspiao(get_sessionmaker())

    await outbound.send(message_id, "ack", {})
    with caplog.at_level("INFO"):
        assert await outbound.send(message_id, "ack", {}) is False

    assert len(outbound.entregas) == 1, "a reentrega nao pode disparar efeito externo"
    total = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert total == 1
    assert "outbound.duplicate_suppressed" in caplog.text


async def test_kinds_diferentes_nao_colidem(session) -> None:
    message_id = await criar_mensagem(session)
    outbound = OutboundEspiao(get_sessionmaker())

    assert await outbound.send(message_id, "ack", {}) is True
    assert await outbound.send(message_id, "reply", {}) is True
    assert len(outbound.entregas) == 2


async def test_noop_outbound_reserva_sem_efeito_externo(session) -> None:
    message_id = await criar_mensagem(session)
    outbound = NoopOutbound(get_sessionmaker())

    assert await outbound.send(message_id, "ack", {}) is True
    assert await outbound.send(message_id, "ack", {}) is False

    total = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert total == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_outbound_guard.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.outbound.models'`.

- [ ] **Step 3: Implementar `src/mobia/domain/outbound/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class OutboundDispatch(Base):
    """Reserva do direito de emitir um efeito externo para uma mensagem.

    A UNIQUE (message_id, kind) e o que torna o reprocessamento seguro: a segunda
    tentativa colide e vira no-op.
    """

    __tablename__ = "outbound_dispatches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("message_id", "kind", name="uq_outbound_message_kind"),)
```

- [ ] **Step 4: Implementar `src/mobia/domain/outbound/port.py`**

```python
import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.outbound.models import OutboundDispatch

log = structlog.get_logger(__name__)


class OutboundPort(Protocol):
    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool: ...


class GuardedOutbound:
    """Reserva antes de entregar.

    A linha em outbound_dispatches e commitada antes do efeito externo. Queda
    entre a reserva e a entrega perde aquele envio; queda depois nunca duplica.
    O criterio de aceite exige "nenhuma resposta duplicada" -- a troca e essa.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        async with self._session_factory() as session:
            session.add(OutboundDispatch(id=uuid.uuid4(), message_id=message_id, kind=kind))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                log.info(
                    "outbound.duplicate_suppressed",
                    message_id=str(message_id),
                    kind=kind,
                )
                return False

        await self._deliver(message_id, kind, payload)
        log.info("outbound.delivered", message_id=str(message_id), kind=kind)
        return True

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError
```

- [ ] **Step 5: Implementar `src/mobia/domain/outbound/noop.py`**

```python
import uuid
from typing import Any

import structlog

from mobia.domain.outbound.port import GuardedOutbound

log = structlog.get_logger(__name__)


class NoopOutbound(GuardedOutbound):
    """Nao envia nada ao lead -- resposta so existe a partir de TEC-134.

    A reserva ja acontece porque e a infraestrutura que o criterio
    "nenhuma resposta duplicada" de TEC-122 exige.
    """

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        log.info("outbound.noop", message_id=str(message_id), kind=kind)
```

- [ ] **Step 6: Escrever a migration `alembic/versions/0002_criar_outbound_dispatches.py`**

```python
"""cria a tabela outbound_dispatches

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbound_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", "kind", name="uq_outbound_message_kind"),
    )


def downgrade() -> None:
    op.drop_table("outbound_dispatches")
```

- [ ] **Step 7: Importar o modelo no `alembic/env.py`**

Acrescente junto aos outros imports, para que o metadata do autogenerate enxergue a tabela:

```python
from mobia.domain.outbound.models import OutboundDispatch  # noqa: F401
```

- [ ] **Step 8: Aplicar a migration e rodar os testes**

```bash
python -m alembic upgrade head
python -m pytest tests/integration/test_outbound_guard.py -v
```

Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
git add src/mobia/domain/outbound alembic/versions/0002_criar_outbound_dispatches.py alembic/env.py tests/integration/test_outbound_guard.py
git commit -m "feat(TEC-122): guarda de idempotencia de saida com reserva unica"
```

---

## Task 9: Job de processamento com claim idempotente — cenário Gherkin 3

**Files:**
- Create: `src/mobia/workers/jobs/process_message.py`
- Test: `tests/features/test_reprocessamento_apos_falha.py`

**Interfaces:**
- Consumes: `Message`/`MessageStatus`/`CLAIMABLE_STATUSES` (Task 4), `GuardedOutbound` (Task 8).
- Produces: `async def claim_message(session: AsyncSession, message_id: uuid.UUID) -> bool`; `async def process_message(ctx: dict[str, Any], message_id: str) -> str` devolvendo `"processed"`, `"skipped"` ou levantando exceção. O `ctx` precisa das chaves `session_factory` e `outbound`.

O `claim` usa `UPDATE ... WHERE status IN (...)` e checa `rowcount`. `PROCESSING` está entre os reivindicáveis de propósito: é exatamente o estado deixado por um worker que morreu no meio, e é o que permite a retomada.

- [ ] **Step 1: Escrever o teste do cenário que vai falhar**

`tests/features/test_reprocessamento_apos_falha.py`:

```python
"""Cenario Gherkin de TEC-122: nao perder mensagem em falha do worker."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import claim_message, process_message


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregas.append(message_id)


class QuedaDoWorker(RuntimeError):
    pass


async def enfileirada(session, status: str = MessageStatus.QUEUED) -> uuid.UUID:
    message = Message(
        id=uuid.uuid4(),
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="ainda tem o 2 quartos?",
        raw_payload={},
        status=status,
    )
    session.add(message)
    await session.commit()
    return message.id


async def test_processa_mensagem_enfileirada(session) -> None:
    message_id = await enfileirada(session)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    assert await process_message(ctx, str(message_id)) == "processed"

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.processed_at is not None
    assert outbound.entregas == [message_id]


async def test_mensagem_ja_processada_e_ignorada(session) -> None:
    message_id = await enfileirada(session, status=MessageStatus.PROCESSED)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    assert await process_message(ctx, str(message_id)) == "skipped"
    assert outbound.entregas == []


async def test_claim_recusa_status_terminal(session) -> None:
    message_id = await enfileirada(session, status=MessageStatus.PROCESSED)
    async with get_sessionmaker()() as sessao:
        assert await claim_message(sessao, message_id) is False


async def test_claim_aceita_processing_para_permitir_retomada(session) -> None:
    """PROCESSING e o estado que um worker morto deixa; tem de ser reivindicavel."""
    message_id = await enfileirada(session, status=MessageStatus.PROCESSING)
    async with get_sessionmaker()() as sessao:
        assert await claim_message(sessao, message_id) is True
        await sessao.commit()


async def test_nao_perder_mensagem_em_falha_do_worker(session) -> None:
    """Cenario: Nao perder mensagem em falha do worker.

    Dada uma mensagem ja enfileirada e um worker interrompido durante o
    processamento, quando o worker e reiniciado, a mensagem volta a ser
    processada e nenhuma resposta duplicada e enviada ao lead.
    """
    message_id = await enfileirada(session)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    # Worker interrompido logo depois da entrega, antes de marcar PROCESSED.
    ctx["fault"] = QuedaDoWorker("worker morto no meio do processamento")
    with pytest.raises(QuedaDoWorker):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.FAILED
    assert linha.attempts == 1
    assert len(outbound.entregas) == 1

    # Worker reiniciado: a mensagem volta a ser processada.
    ctx.pop("fault")
    assert await process_message(ctx, str(message_id)) == "processed"

    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert len(outbound.entregas) == 1, "nenhuma resposta duplicada ao lead"
    assert await session.scalar(select(func.count()).select_from(OutboundDispatch)) == 1


async def test_mensagem_em_received_tambem_e_processavel(session) -> None:
    """Cobre a linha que o sweeper recupera: nunca chegou a ficar QUEUED."""
    message_id = await enfileirada(session, status=MessageStatus.RECEIVED)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}

    assert await process_message(ctx, str(message_id)) == "processed"
    assert outbound.entregas == [message_id]


async def test_mensagem_inexistente_e_ignorada() -> None:
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = {"session_factory": get_sessionmaker(), "outbound": outbound}
    assert await process_message(ctx, str(uuid.uuid4())) == "skipped"
```

O `ctx["fault"]` é injeção de falha só de teste: a implementação levanta o que estiver ali logo depois da entrega, que é a janela exata em que a duplicação aconteceria sem a guarda.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/features/test_reprocessamento_apos_falha.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.workers.jobs.process_message'`.

- [ ] **Step 3: Implementar `src/mobia/workers/jobs/process_message.py`**

```python
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus

log = structlog.get_logger(__name__)

ACK_KIND = "ack"


async def claim_message(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """Reivindica a mensagem para processamento.

    PROCESSING esta entre os estados reivindicaveis de proposito: e o estado que
    um worker morto no meio do job deixa para tras, e e o que permite a retomada.
    Quem perde a corrida recebe rowcount 0 e sai como no-op.
    """
    resultado = await session.execute(
        update(Message)
        .where(Message.id == message_id, Message.status.in_(CLAIMABLE_STATUSES))
        .values(status=MessageStatus.PROCESSING)
    )
    return resultado.rowcount == 1


async def process_message(ctx: dict[str, Any], message_id: str) -> str:
    session_factory = ctx["session_factory"]
    outbound = ctx["outbound"]
    identifier = uuid.UUID(message_id)

    async with session_factory() as session:
        if not await claim_message(session, identifier):
            await session.rollback()
            log.info("message.skipped", message_id=message_id, reason="not_claimable")
            return "skipped"
        await session.commit()

    try:
        await outbound.send(identifier, ACK_KIND, {})

        fault = ctx.get("fault")
        if fault is not None:
            raise fault

        async with session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == identifier)
                .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
            )
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == identifier)
                .values(
                    status=MessageStatus.FAILED,
                    attempts=Message.attempts + 1,
                    last_error=f"{type(exc).__name__}: {exc}",
                )
            )
            await session.commit()
        log.warning("message.failed", message_id=message_id, error=str(exc))
        raise

    log.info("message.processed", message_id=message_id)
    return "processed"
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/features/test_reprocessamento_apos_falha.py -v`
Expected: 7 passed.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: 48 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/workers/jobs/process_message.py tests/features/test_reprocessamento_apos_falha.py
git commit -m "feat(TEC-122): job de processamento com claim idempotente e retomada"
```

---

## Task 10: Sweeper de mensagens paradas e configuração do worker

**Files:**
- Create: `src/mobia/workers/jobs/sweep_stalled.py`, `src/mobia/workers/main.py`
- Test: `tests/integration/test_sweep_stalled.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `Message`/`MessageStatus` (Task 4), `enqueue_process_message`/`redis_settings`/`SWEEP_STALLED_JOB` (Task 5), `process_message` (Task 9), `NoopOutbound` (Task 8).
- Produces: `async def sweep_stalled(ctx: dict[str, Any]) -> int` devolvendo quantas mensagens foram reenfileiradas; classe `WorkerSettings` com `functions`, `cron_jobs`, `redis_settings`, `on_startup`, `on_shutdown`.

O sweeper cobre as duas janelas de perda: `RECEIVED` velho (morreu entre o commit e o enqueue) e `QUEUED`/`PROCESSING` velho (morreu durante o job). O `FOR UPDATE SKIP LOCKED` permite mais de um worker varrendo sem colidir.

- [ ] **Step 1: Escrever os testes que vão falhar**

`tests/integration/test_sweep_stalled.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_stalled import sweep_stalled


async def mensagem(
    session,
    status: str,
    idade_segundos: int,
    attempts: int = 0,
) -> uuid.UUID:
    instante = datetime.now(UTC) - timedelta(seconds=idade_segundos)
    message = Message(
        id=uuid.uuid4(),
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type="text",
        text_body="oi",
        raw_payload={},
        status=status,
        attempts=attempts,
        received_at=instante,
        queued_at=instante if status != MessageStatus.RECEIVED else None,
    )
    session.add(message)
    await session.commit()
    return message.id


def contexto(redis_pool, settings) -> dict:
    return {
        "session_factory": get_sessionmaker(),
        "redis": redis_pool,
        "settings": settings,
    }


async def test_reenfileira_received_parado(session, redis_pool, settings) -> None:
    message_id = await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1

    jobs = await redis_pool.queued_jobs()
    assert [job.args for job in jobs] == [(str(message_id),)]

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.attempts == 1


async def test_nao_toca_em_received_recente(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.RECEIVED, idade_segundos=5)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_reenfileira_processing_travado(session, redis_pool, settings) -> None:
    message_id = await mensagem(session, MessageStatus.PROCESSING, idade_segundos=3600)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 1
    assert [job.args for job in await redis_pool.queued_jobs()] == [(str(message_id),)]


async def test_nao_toca_em_queued_recente(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.QUEUED, idade_segundos=60)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0


async def test_ignora_terminais(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.PROCESSED, idade_segundos=3600)
    await mensagem(session, MessageStatus.FAILED, idade_segundos=3600, attempts=1)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0


async def test_respeita_o_teto_de_tentativas(session, redis_pool, settings) -> None:
    await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120, attempts=5)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []


async def test_varre_varias_de_uma_vez(session, redis_pool, settings) -> None:
    for _ in range(3):
        await mensagem(session, MessageStatus.RECEIVED, idade_segundos=120)

    assert await sweep_stalled(contexto(redis_pool, settings)) == 3
    assert len(await redis_pool.queued_jobs()) == 3

    paradas = (
        await session.scalars(
            select(Message).where(Message.status == MessageStatus.RECEIVED)
        )
    ).all()
    assert all(linha.attempts == 1 for linha in paradas)
```

Note que `FAILED` **não** é varrido: retry de job que falhou é responsabilidade do ARQ, e a recuperação definitiva de `FAILED` é TEC-209.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/integration/test_sweep_stalled.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.workers.jobs.sweep_stalled'`.

- [ ] **Step 3: Implementar `src/mobia/workers/jobs/sweep_stalled.py`**

```python
import uuid
from typing import Any

import structlog
from sqlalchemy import text

from mobia.app.config import Settings, get_settings
from mobia.infra.queue import enqueue_process_message

log = structlog.get_logger(__name__)

_SELECIONAR_PARADAS = text(
    """
    UPDATE messages
       SET attempts = attempts + 1
     WHERE id IN (
        SELECT id
          FROM messages
         WHERE attempts < :max_attempts
           AND (
                (status = 'RECEIVED' AND received_at < now() - make_interval(secs => :received_after))
             OR (status IN ('QUEUED', 'PROCESSING')
                 AND COALESCE(queued_at, received_at) < now() - make_interval(secs => :inflight_after))
           )
         ORDER BY received_at
         LIMIT :limite
           FOR UPDATE SKIP LOCKED
     )
 RETURNING id
    """
)


async def sweep_stalled(ctx: dict[str, Any], limite: int = 100) -> int:
    """Reenfileira mensagens que ficaram para tras.

    Duas janelas de perda: RECEIVED velho (o processo morreu entre o commit e o
    enqueue) e QUEUED/PROCESSING velho (o worker morreu durante o job). O
    SKIP LOCKED permite varias instancias varrendo em paralelo sem colidir.
    """
    session_factory = ctx["session_factory"]
    redis = ctx["redis"]
    settings: Settings = ctx.get("settings") or get_settings()

    async with session_factory() as session:
        resultado = await session.execute(
            _SELECIONAR_PARADAS,
            {
                "max_attempts": settings.sweep_max_attempts,
                "received_after": settings.sweep_received_after_seconds,
                "inflight_after": settings.sweep_inflight_after_seconds,
                "limite": limite,
            },
        )
        ids: list[uuid.UUID] = [linha[0] for linha in resultado.fetchall()]
        await session.commit()

    for message_id in ids:
        await enqueue_process_message(redis, message_id)

    if ids:
        log.info("sweep.requeued", count=len(ids), message_ids=[str(i) for i in ids])
    return len(ids)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/integration/test_sweep_stalled.py -v`
Expected: 7 passed.

- [ ] **Step 5: Implementar `src/mobia/workers/main.py`**

```python
from typing import Any

from arq import cron

from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.domain.outbound.noop import NoopOutbound
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.queue import create_redis_pool, redis_settings
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.sweep_stalled import sweep_stalled


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = get_sessionmaker()
    ctx["settings"] = settings
    ctx["session_factory"] = session_factory
    ctx["outbound"] = NoopOutbound(session_factory)
    ctx["redis"] = await create_redis_pool()


async def shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("redis")
    if pool is not None:
        await pool.aclose()
    await dispose_engine()


class WorkerSettings:
    functions = [process_message, sweep_stalled]
    cron_jobs = [cron(sweep_stalled, second={0, 30}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = 5
    job_timeout = 60
```

- [ ] **Step 6: Verificar que o worker sobe**

```bash
python -c "from mobia.workers.main import WorkerSettings; print([f.__name__ for f in WorkerSettings.functions])"
```

Expected: `['process_message', 'sweep_stalled']`

Depois, com o compose de pé, suba o worker por alguns segundos e derrube com Ctrl+C:

```bash
python -m arq mobia.workers.main.WorkerSettings
```

Expected: log de startup do ARQ sem traceback.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: 55 passed.

- [ ] **Step 8: Commit**

```bash
git add src/mobia/workers tests/integration/test_sweep_stalled.py
git commit -m "feat(TEC-122): sweeper de mensagens paradas e configuracao do worker ARQ"
```

---

## Task 11: Teste de latência p95 e fechamento

**Files:**
- Create: `tests/perf/test_ingest_latency.py`
- Modify: `README.md`
- Test: o próprio arquivo criado

**Interfaces:**
- Consumes: fixture `client` (Task 7), `compute_signature` (Task 2).
- Produces: nada consumido por outra task.

Marcado `perf` e excluído do run padrão pelo `addopts` da Task 1: medição de latência em máquina compartilhada é frágil e viraria flake. Roda sob demanda com `-m perf`.

- [ ] **Step 1: Escrever o teste de latência**

`tests/perf/test_ingest_latency.py`:

```python
"""Criterio de aceite de TEC-122: 200 OK em ate 300 ms no p95.

Marcado `perf` e fora do run padrao: a medicao depende da maquina.
Rode com `python -m pytest -m perf`.
"""

import json
import statistics
import time

import pytest

from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

REQUISICOES = 200
P95_MAXIMO_MS = 300.0
P99_MAXIMO_MS = 500.0


def envelope(indice: int) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [
                                {
                                    "from": "5511911112222",
                                    "id": f"wamid.PERF{indice}",
                                    "type": "text",
                                    "text": {"body": "tem apartamento de 2 quartos?"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }


@pytest.mark.perf
async def test_p95_do_webhook_fica_abaixo_de_300ms(client, settings) -> None:
    latencias_ms: list[float] = []

    for indice in range(REQUISICOES):
        body = json.dumps(envelope(indice)).encode("utf-8")
        headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

        inicio = time.perf_counter()
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)
        latencias_ms.append((time.perf_counter() - inicio) * 1000)

        assert response.status_code == 200

    quantis = statistics.quantiles(latencias_ms, n=100)
    p95 = quantis[94]
    p99 = quantis[98]

    print(f"\np50={statistics.median(latencias_ms):.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms")
    assert p95 < P95_MAXIMO_MS, f"p95 de {p95:.1f}ms estourou o orcamento de {P95_MAXIMO_MS}ms"
    assert p99 < P99_MAXIMO_MS, f"p99 de {p99:.1f}ms estourou o orcamento de {P99_MAXIMO_MS}ms"
```

- [ ] **Step 2: Rodar o teste de latência**

Run: `python -m pytest -m perf -v -s`
Expected: 1 passed, com a linha `p50=… p95=… p99=…` impressa e p95 confortavelmente abaixo de 300 ms.

Se estourar: confirme que o `docker compose` está saudável e que nenhuma outra carga está na máquina. Se ainda estourar, o gargalo é real — investigue com `EXPLAIN ANALYZE` no insert e cheque o `pool_pre_ping`.

- [ ] **Step 3: Rodar tudo e conferir o lint**

```bash
python -m pytest -v
python -m pytest -m perf -v
python -m ruff check src tests
```

Expected: 55 passed no run padrão, 1 passed no perf, `All checks passed!` no ruff.

- [ ] **Step 4: Documentar os critérios de aceite no README**

Acrescente ao final do `README.md`:

````markdown
## TEC-122 — Ingestão do WhatsApp

Os critérios de aceite da história vivem como testes executáveis:

| Cenário Gherkin | Teste |
|---|---|
| Confirmar recebimento antes de processar | `tests/features/test_recepcao_de_mensagem.py::test_confirmar_recebimento_antes_de_processar` |
| Descartar payload com assinatura inválida | `tests/features/test_recepcao_de_mensagem.py::test_descartar_payload_com_assinatura_invalida` |
| Não perder mensagem em falha do worker | `tests/features/test_reprocessamento_apos_falha.py::test_nao_perder_mensagem_em_falha_do_worker` |
| 200 OK em até 300 ms no p95 | `tests/perf/test_ingest_latency.py` (roda com `-m perf`) |

### Garantias

- A mensagem é commitada no Postgres **antes** de ir para o Redis. Se o processo
  morrer no meio, o cron `sweep_stalled` reenfileira.
- Efeito externo passa por `outbound_dispatches` com `UNIQUE (message_id, kind)`:
  a reentrega vira no-op, então o reprocessamento nunca duplica resposta.
- Assinatura inválida responde 200 e só gera log. Devolver erro faria a própria
  Meta re-tentar o payload de um forjador.
````

- [ ] **Step 5: Commit**

```bash
git add tests/perf/test_ingest_latency.py README.md
git commit -m "test(TEC-122): teste de latencia p95 do webhook e documentacao dos criterios"
```

---

## Verificação final

- [ ] `python -m pytest -v` → 55 passed
- [ ] `python -m pytest -m perf -v` → 1 passed
- [ ] `python -m ruff check src tests` → sem erros
- [ ] `python -m alembic upgrade head` em banco limpo → sem erros
- [ ] Os três cenários Gherkin de TEC-122 têm teste nomeado correspondente
- [ ] Nenhum import de provedor de LLM em `src/mobia/api/`

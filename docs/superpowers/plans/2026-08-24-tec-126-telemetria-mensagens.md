# TEC-126 — Persistir mensagens com tokens, custo e latência — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer de `messages` a linha do tempo canônica da conversa — entrada e saída — com o conteúdo cifrado em repouso, mascarado em log, e a telemetria de tokens, custo e latência do agente numa tabela ao lado.

**Architecture:** `messages` ganha `role`, `direction` e `conversation_key`, e perde a premissa de que toda linha veio de fora: `status` passa a nullable e o sweeper filtra `direction = INBOUND`. `text_body` e `raw_payload` viram `bytea` cifrado com AES-GCM, com AAD amarrado a `{message_id}:{coluna}`. Tokens, custo, latência, modelo e subagente vão para `message_telemetry`, 1-1, gravada num segundo passo best-effort para que falha de telemetria nunca derrube o registro da fala do agente.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic, Redis + ARQ, `cryptography` (AES-GCM), structlog, pydantic-settings, pytest + pytest-asyncio, Docker Compose.

**Spec:** [docs/superpowers/specs/2026-08-24-tec-126-telemetria-mensagens-design.md](../specs/2026-08-24-tec-126-telemetria-mensagens-design.md)

## Global Constraints

- Python **3.13** (`requires-python = ">=3.13"`, ruff `target-version = "py313"`, mypy `python_version = "3.13"`). O plano do TEC-122 dizia 3.12; o repositório está em 3.13 e é ele que manda.
- Todo I/O é `async`.
- `ruff check src tests` e `ruff format --check src tests` limpos, `line-length = 100`, regras `E, F, I, UP, B`.
- `mypy` limpo sobre `src` (`warn_unused_ignores`, `warn_unreachable` ligados).
- **Nada no código loga `text_body` nem `raw_payload`.** O processor de mascaramento é a segunda linha de defesa, não a primeira.
- **Nenhuma chamada a provedor de LLM** em qualquer caminho desta história. Não existe agente ainda.
- Testes rodam contra Postgres e Redis reais (`docker compose up -d`). Nada de mock de banco ou fila.
- Mensagens de commit no formato do repositório: `tipo(TEC-126): descricao em minusculas, sem acento`.
- Comentário de código em português, sem acento, explicando **por quê** e não o quê — é o padrão do repositório.

## Decisão de implementação registrada aqui, não no spec

**Por que a cifra não é um `TypeDecorator` do SQLAlchemy.** Seria a solução idiomática e pouparia churn: `Message(text_body="oi")` continuaria funcionando e a coluna seria `bytea` no Postgres. Mas `process_bind_param` não conhece o `id` da linha que está sendo gravada, e sem ele o AAD não pode ser `{message_id}:{coluna}` — perde-se justamente a proteção contra mover ciphertext de um lead para a linha de outro.

Como só existem **dois** escritores (`IngestionService._persist` e `MessageRecorder`), a cifra explícita nesses dois pontos custa pouco e preserva o AAD. Leitura usa o helper `decrypt`.

## Estrutura de arquivos

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/infra/crypto.py` | AES-GCM: `encrypt`/`decrypt`/`encrypt_json`/`decrypt_json`/`aad_de`. Não conhece domínio nem ORM. |
| `src/mobia/domain/messages/enums.py` | `MessageRole`, `MessageDirection`, `MessageContentType` e o mapeamento do vocabulário da Meta. |
| `src/mobia/domain/messages/recorder.py` | `MessageRecorder.record_agent_message` — a costura que TEC-134 vai usar. |
| `alembic/versions/0004_timeline_telemetria_e_cifra.py` | Migração, com backfill de cifra e `downgrade` que decifra. |
| `tests/unit/test_crypto.py` | Roundtrip, nonce, AAD, adulteração. |
| `tests/unit/test_logging_mascara.py` | O processor de PII. |
| `tests/integration/test_recorder.py` | O recorder e seus modos de falha. |
| `tests/features/test_telemetria_de_mensagens.py` | Os quatro cenários Gherkin. |

**Modificar:**

| Arquivo | O quê |
|---|---|
| `pyproject.toml` | Dependência `cryptography`. |
| `.env.example` | `CONTENT_ENCRYPTION_KEY`. |
| `src/mobia/app/config.py` | `content_encryption_key`, `PRECOS_POR_MODELO`. |
| `src/mobia/app/logging.py` | Processor de mascaramento. |
| `src/mobia/domain/messages/models.py` | Colunas novas em `Message`, classe `MessageTelemetry`. |
| `src/mobia/domain/messages/schemas.py` | Parser mapeia para `MessageContentType`. |
| `src/mobia/domain/messages/service.py` | Grava `role`/`direction`/`conversation_key` e cifra. |
| `src/mobia/workers/jobs/sweep_stalled.py` | `received_at` → `created_at`, filtro `direction = INBOUND`. |
| `tests/conftest.py` | `message_telemetry` na lista de truncate. |
| `tests/unit/test_meta_envelope.py` | Espera o enum de domínio. |
| `tests/integration/test_message_model.py` | Colunas novas, `created_at`, conteúdo cifrado. |
| `tests/integration/test_sweep_stalled.py` | Helper com as colunas novas. |
| `tests/integration/test_migrations.py` | Decifra antes de comparar. |
| `README.md` | Tabela de critérios do TEC-126. |

---

## Task 1: Cifra AEAD do conteúdo

**Files:**
- Create: `src/mobia/infra/crypto.py`
- Create: `tests/unit/test_crypto.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `src/mobia/app/config.py`

**Interfaces:**
- Consumes: `mobia.app.config.get_settings`
- Produces:
  - `aad_de(message_id: uuid.UUID | str, coluna: str) -> str`
  - `encrypt(texto: str | None, aad: str) -> bytes | None`
  - `decrypt(blob: bytes | None, aad: str) -> str | None`
  - `encrypt_json(valor: dict[str, Any] | None, aad: str) -> bytes | None`
  - `decrypt_json(blob: bytes | None, aad: str) -> dict[str, Any] | None`
  - `class DecryptionError(Exception)`
  - `Settings.content_encryption_key: str`

> O spec listava estes testes como `tests/integration/test_crypto.py`. O primitivo não toca banco nenhum, então vive em `tests/unit/`. O teste de integração que o spec pede — `SELECT` cru devolvendo bytes — entra na Task 5, onde já existe linha gravada pelo serviço.

- [ ] **Step 1: Adicionar a dependência**

Em `pyproject.toml`, na lista `dependencies`, depois de `"structlog>=24.4",`:

```toml
    "cryptography>=44.0",
```

- [ ] **Step 2: Instalar**

Run: `.venv/Scripts/python -m pip install -e ".[dev]"`
Expected: `Successfully installed cryptography-...`

- [ ] **Step 3: Escrever o teste que vai falhar**

Crie `tests/unit/test_crypto.py`:

```python
import pytest

from mobia.infra.crypto import (
    DecryptionError,
    aad_de,
    decrypt,
    decrypt_json,
    encrypt,
    encrypt_json,
)

AAD = aad_de("11111111-1111-1111-1111-111111111111", "text_body")


def test_roundtrip_de_texto() -> None:
    cifrado = encrypt("orcamento de 600 mil", AAD)
    assert cifrado is not None
    assert decrypt(cifrado, AAD) == "orcamento de 600 mil"


def test_none_atravessa_sem_cifrar() -> None:
    """A coluna e nullable e ausencia de conteudo nao e conteudo."""
    assert encrypt(None, AAD) is None
    assert decrypt(None, AAD) is None


def test_mesmo_texto_cifra_diferente_a_cada_chamada() -> None:
    """Nonce aleatorio por chamada: e o que impede inferir igualdade pelo ciphertext."""
    assert encrypt("oi", AAD) != encrypt("oi", AAD)


def test_ciphertext_movido_de_outra_linha_e_rejeitado() -> None:
    """O AAD amarra o ciphertext ao seu proprio (message_id, coluna).

    Sem isso, quem tem UPDATE no banco mas nao a chave move o conteudo da Marina
    para a linha de outro lead e a aplicacao decifra sem reclamar.
    """
    cifrado = encrypt("oi", AAD)
    assert cifrado is not None
    outra_linha = aad_de("22222222-2222-2222-2222-222222222222", "text_body")
    with pytest.raises(DecryptionError):
        decrypt(cifrado, outra_linha)


def test_ciphertext_movido_de_outra_coluna_e_rejeitado() -> None:
    cifrado = encrypt("oi", AAD)
    assert cifrado is not None
    outra_coluna = aad_de("11111111-1111-1111-1111-111111111111", "raw_payload")
    with pytest.raises(DecryptionError):
        decrypt(cifrado, outra_coluna)


def test_ciphertext_adulterado_e_rejeitado() -> None:
    cifrado = bytearray(encrypt("oi", AAD) or b"")
    cifrado[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        decrypt(bytes(cifrado), AAD)


def test_roundtrip_de_json() -> None:
    payload = {"id": "wamid.ABC", "type": "text", "text": {"body": "oi"}}
    cifrado = encrypt_json(payload, AAD)
    assert cifrado is not None
    assert decrypt_json(cifrado, AAD) == payload
```

- [ ] **Step 4: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.infra.crypto'`

- [ ] **Step 5: Acrescentar a chave às configurações**

Em `src/mobia/app/config.py`, dentro de `Settings`, logo abaixo de `whatsapp_verify_token`:

```python
    # 32 bytes em base64. O default so serve para desenvolvimento e teste --
    # em producao vem do ambiente, como o whatsapp_app_secret.
    content_encryption_key: str = "ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE="
```

- [ ] **Step 6: Registrar a chave no `.env.example`**

Acrescente ao fim de `.env.example`:

```
# 32 bytes em base64: python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
CONTENT_ENCRYPTION_KEY=ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE=
```

- [ ] **Step 7: Implementar `src/mobia/infra/crypto.py`**

```python
import base64
import json
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mobia.app.config import get_settings

NONCE_BYTES = 12
CHAVE_BYTES = 32


class DecryptionError(Exception):
    """O conteudo nao autentica com esta chave e este AAD."""


def _cifra() -> AESGCM:
    chave = base64.b64decode(get_settings().content_encryption_key)
    if len(chave) != CHAVE_BYTES:
        raise ValueError(
            f"content_encryption_key deve ter {CHAVE_BYTES} bytes apos o base64,"
            f" tem {len(chave)}"
        )
    return AESGCM(chave)


def aad_de(message_id: uuid.UUID | str, coluna: str) -> str:
    """Amarra o ciphertext a sua propria linha e coluna.

    Sem isso, quem tem UPDATE no banco mas nao a chave pode mover o conteudo de
    um lead para a linha de outro, ou de `text_body` para `raw_payload`, e a
    aplicacao decifra sem reclamar.
    """
    return f"{message_id}:{coluna}"


def encrypt(texto: str | None, aad: str) -> bytes | None:
    if texto is None:
        return None
    # Nonce novo a cada chamada: o mesmo texto cifra diferente toda vez, entao
    # busca por igualdade sobre conteudo deixa de existir. E intencional.
    nonce = os.urandom(NONCE_BYTES)
    return nonce + _cifra().encrypt(nonce, texto.encode(), aad.encode())


def decrypt(blob: bytes | None, aad: str) -> str | None:
    if blob is None:
        return None
    nonce, corpo = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    try:
        return _cifra().decrypt(nonce, corpo, aad.encode()).decode()
    except InvalidTag as exc:
        raise DecryptionError(aad) from exc


def encrypt_json(valor: dict[str, Any] | None, aad: str) -> bytes | None:
    if valor is None:
        return None
    return encrypt(json.dumps(valor, separators=(",", ":"), sort_keys=True), aad)


def decrypt_json(blob: bytes | None, aad: str) -> dict[str, Any] | None:
    texto = decrypt(blob, aad)
    if texto is None:
        return None
    resultado: dict[str, Any] = json.loads(texto)
    return resultado
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/unit/test_crypto.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 9: Lint e tipos**

Run: `.venv/Scripts/python -m ruff check src tests && .venv/Scripts/python -m ruff format src tests && .venv/Scripts/python -m mypy`
Expected: sem erro.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml .env.example src/mobia/app/config.py src/mobia/infra/crypto.py tests/unit/test_crypto.py
git commit -m "feat(TEC-126): cifra AES-GCM do conteudo com AAD por linha e coluna"
```

---

## Task 2: Vocabulário de domínio para papel, direção e tipo

**Files:**
- Create: `src/mobia/domain/messages/enums.py`
- Modify: `src/mobia/domain/messages/schemas.py`
- Modify: `tests/unit/test_meta_envelope.py`

**Interfaces:**
- Produces:
  - `MessageRole` — `LEAD`, `AGENTE`, `CORRETOR`, `SISTEMA`
  - `MessageDirection` — `INBOUND`, `OUTBOUND`
  - `MessageContentType` — `TEXTO`, `AUDIO`, `IMAGEM`, `DOCUMENTO`, `DESCONHECIDO`
  - `content_type_da_meta(valor: str | None) -> MessageContentType`
- Consumed by: Tasks 4, 5, 7.

- [ ] **Step 1: Escrever o teste que vai falhar**

Acrescente ao fim de `tests/unit/test_meta_envelope.py`:

```python
from mobia.domain.messages.enums import MessageContentType, content_type_da_meta


def envelope_com_tipo(tipo: str) -> dict:
    mensagem: dict = {"id": "wamid.TIPO", "from": "5511911112222", "type": tipo}
    if tipo == "text":
        mensagem["text"] = {"body": "oi"}
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [mensagem],
                        }
                    }
                ]
            }
        ]
    }


def test_mapeia_o_vocabulario_da_meta_para_o_dominio() -> None:
    """A coluna guarda o termo do dominio, nao o da Meta.

    TEC-124 traz o widget web, com vocabulario proprio. Se cada canal gravasse
    o seu, `messages` deixaria de ser um registro canonico legivel.
    """
    assert content_type_da_meta("text") is MessageContentType.TEXTO
    assert content_type_da_meta("audio") is MessageContentType.AUDIO
    assert content_type_da_meta("image") is MessageContentType.IMAGEM
    assert content_type_da_meta("document") is MessageContentType.DOCUMENTO


def test_tipo_ausente_ou_desconhecido_nao_derruba_o_parse() -> None:
    assert content_type_da_meta(None) is MessageContentType.DESCONHECIDO
    assert content_type_da_meta("sticker") is MessageContentType.DESCONHECIDO


def test_parser_devolve_o_tipo_do_dominio() -> None:
    (parsed,) = parse_meta_envelope(envelope_com_tipo("image"))
    assert parsed.content_type is MessageContentType.IMAGEM
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_meta_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.messages.enums'`

- [ ] **Step 3: Implementar `src/mobia/domain/messages/enums.py`**

```python
from enum import StrEnum


class MessageRole(StrEnum):
    LEAD = "LEAD"
    AGENTE = "AGENTE"
    CORRETOR = "CORRETOR"
    SISTEMA = "SISTEMA"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageContentType(StrEnum):
    TEXTO = "TEXTO"
    AUDIO = "AUDIO"
    IMAGEM = "IMAGEM"
    DOCUMENTO = "DOCUMENTO"
    DESCONHECIDO = "DESCONHECIDO"


# O vocabulario cru da Meta fica confinado aqui. Cada canal novo (TEC-124 web,
# por exemplo) ganha o seu proprio mapeamento e a coluna continua canonica.
_DA_META = {
    "text": MessageContentType.TEXTO,
    "audio": MessageContentType.AUDIO,
    "image": MessageContentType.IMAGEM,
    "document": MessageContentType.DOCUMENTO,
}


def content_type_da_meta(valor: str | None) -> MessageContentType:
    if valor is None:
        return MessageContentType.DESCONHECIDO
    return _DA_META.get(valor, MessageContentType.DESCONHECIDO)
```

- [ ] **Step 4: Trocar o tipo em `ParsedMessage`**

Em `src/mobia/domain/messages/schemas.py`, troque o import e o campo:

```python
from mobia.domain.messages.enums import MessageContentType, content_type_da_meta
```

```python
@dataclass(frozen=True)
class ParsedMessage:
    provider_message_id: str
    sender_external_id: str
    recipient_external_id: str
    content_type: MessageContentType
    text_body: str | None
    raw_payload: dict[str, Any]
```

E dentro de `parse_meta_envelope`, substitua o bloco que decide tipo e corpo:

```python
                content_type = content_type_da_meta(message.get("type"))
                text_body = None
                if content_type is MessageContentType.TEXTO:
                    text_body = (message.get("text") or {}).get("body")
```

E no construtor, `content_type=content_type,` (deixa de ter o `str(...)` em volta).

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/unit/ -v`
Expected: PASS. Se algum teste antigo do envelope esperava `"text"`, ajuste para `MessageContentType.TEXTO`.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/domain/messages/enums.py src/mobia/domain/messages/schemas.py tests/unit/test_meta_envelope.py
git commit -m "feat(TEC-126): vocabulario de dominio para papel, direcao e tipo"
```

---

## Task 3: Mascaramento de PII em log

**Files:**
- Modify: `src/mobia/app/logging.py`
- Create: `tests/unit/test_logging_mascara.py`

**Interfaces:**
- Produces: processor `_mascarar_pii` registrado em `configure_logging`, antes do `JSONRenderer`.

- [ ] **Step 1: Escrever o teste que vai falhar**

Crie `tests/unit/test_logging_mascara.py`:

```python
import logging

import structlog


def test_telefone_em_campo_livre_sai_mascarado(caplog) -> None:
    """Segunda linha de defesa: pega o telefone que escapou para um campo qualquer."""
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", detalhe="retornar para 5511987654321 hoje")

    assert "5511987654321" not in caplog.text
    assert "*********4321" in caplog.text


def test_campos_de_conteudo_sao_redigidos_inteiros(caplog) -> None:
    """`text_body` e `raw_payload` nunca aparecem, com ou sem digito."""
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", text_body="quero apto na zona sul")

    assert "zona sul" not in caplog.text
    assert "<redigido>" in caplog.text


def test_identificador_externo_e_mascarado_pela_chave(caplog) -> None:
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", sender_external_id="5511987654321")

    assert "5511987654321" not in caplog.text


def test_uuid_nao_e_confundido_com_telefone(caplog) -> None:
    """Um UUID tem 12 digitos seguidos no ultimo grupo.

    Sem a excecao, o mascaramento comeria o `message_id` de todo log de
    ingestao e a correlacao entre eventos morreria.
    """
    identificador = "550e8400-e29b-41d4-a716-446655440000"
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", message_id=identificador)

    assert identificador in caplog.text


def test_lista_de_identificadores_sobrevive(caplog) -> None:
    """`message.received` loga `message_ids` como lista."""
    identificadores = ["550e8400-e29b-41d4-a716-446655440000"]
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", message_ids=identificadores)

    assert identificadores[0] in caplog.text
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/unit/test_logging_mascara.py -v`
Expected: FAIL — `assert "5511987654321" not in caplog.text`

- [ ] **Step 3: Implementar o processor**

Em `src/mobia/app/logging.py`, acrescente ao topo:

```python
import re
```

E, depois de `_add_correlation_id`:

```python
# 10 a 15 digitos seguidos: cobre telefone nacional com e sem DDI.
_CORRIDA_DE_DIGITOS = re.compile(r"\d{10,15}")

# Um UUID termina em 12 digitos hexadecimais que podem ser todos decimais, e o
# `message_id` aparece em quase todo evento de ingestao. Mascarar isso mataria a
# correlacao entre eventos sem proteger ninguem.
_UUID = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)

# Conteudo de lead: nao ha versao segura de logar, entao some inteiro.
_CHAVES_REDIGIDAS = frozenset({"text_body", "raw_payload", "envelope_context"})


def _mascarar_digitos(texto: str) -> str:
    if _UUID.match(texto):
        return texto
    return _CORRIDA_DE_DIGITOS.sub(
        lambda achado: "*" * (len(achado.group()) - 4) + achado.group()[-4:],
        texto,
    )


def _mascarar_pii(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Segunda linha de defesa do mascaramento.

    A primeira e nao logar conteudo, e ela ja vale hoje. Esta existe para o dia
    em que alguem esquecer: disciplina que depende de lembrar vaza uma hora.
    """
    for chave, valor in list(event_dict.items()):
        if chave in _CHAVES_REDIGIDAS:
            event_dict[chave] = "<redigido>"
        elif isinstance(valor, str):
            event_dict[chave] = _mascarar_digitos(valor)
        elif isinstance(valor, list):
            event_dict[chave] = [
                _mascarar_digitos(item) if isinstance(item, str) else item for item in valor
            ]
    return event_dict
```

E registre-o na lista de processors de `configure_logging`, entre `TimeStamper` e `JSONRenderer`:

```python
            structlog.processors.TimeStamper(fmt="iso"),
            _mascarar_pii,
            structlog.processors.JSONRenderer(),
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/unit/test_logging_mascara.py -v`
Expected: PASS, 5 testes.

- [ ] **Step 5: Confirmar que a suíte inteira continua verde**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS. Testes que asseguram conteúdo de log (ex.: `webhook.rejected`) não devem quebrar — eles logam `reason`, `remote_ip` e `payload_sha256`, e nenhum casa com as regras acima. Se um `remote_ip` de teste for numérico contínuo, ajuste o teste, não o processor.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/app/logging.py tests/unit/test_logging_mascara.py
git commit -m "feat(TEC-126): mascara telefone e redige conteudo no log estruturado"
```

---

## Task 4: Esquema da linha do tempo e da telemetria

Esta é a task pesada: migração, modelo e o ajuste mecânico de tudo que lia `received_at`. Ela termina com a suíte inteira verde.

**Files:**
- Create: `alembic/versions/0004_timeline_telemetria_e_cifra.py`
- Modify: `src/mobia/domain/messages/models.py`
- Modify: `src/mobia/workers/jobs/sweep_stalled.py`
- Modify: `tests/conftest.py`
- Modify: `tests/integration/test_message_model.py`
- Modify: `tests/integration/test_sweep_stalled.py`
- Modify: `tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: `mobia.infra.crypto` (Task 1), `mobia.domain.messages.enums` (Task 2)
- Produces:
  - `Message.role`, `Message.direction`, `Message.conversation_key`, `Message.created_at`
  - `Message.text_body: Mapped[bytes | None]`, `Message.raw_payload: Mapped[bytes | None]`
  - `class MessageTelemetry` com `message_id`, `model`, `subagent`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `created_at`

- [ ] **Step 1: Escrever o teste de modelo que vai falhar**

Substitua `test_persiste_mensagem_com_defaults` e `nova_mensagem` em `tests/integration/test_message_model.py`:

```python
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus
from mobia.infra.crypto import aad_de, decrypt, encrypt


def nova_mensagem(provider_message_id: str, channel: str = "whatsapp") -> Message:
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        channel=channel,
        provider_message_id=provider_message_id,
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        conversation_key="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("oi", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.RECEIVED,
    )


async def test_persiste_mensagem_com_defaults(session) -> None:
    message = nova_mensagem("wamid.PERSIST")
    session.add(message)
    await session.commit()

    resultado = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.PERSIST")
    )
    assert resultado is not None
    assert resultado.role == MessageRole.LEAD
    assert resultado.direction == MessageDirection.INBOUND
    assert resultado.conversation_key == "5511911112222"
    assert resultado.content_type == MessageContentType.TEXTO
    assert resultado.created_at is not None
    assert resultado.attempts == 0
    assert decrypt(resultado.text_body, aad_de(resultado.id, "text_body")) == "oi"


async def test_linha_de_saida_nasce_sem_status(session) -> None:
    """A fala do agente nao participa do pipeline de ingestao.

    Se ela nascesse com o default RECEIVED, o sweeper do TEC-122 varreria a
    propria resposta do agente e a enfileiraria para processamento.
    """
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel="whatsapp",
            provider_message_id=None,
            sender_external_id=None,
            recipient_external_id=None,
            conversation_key="5511911112222",
            role=MessageRole.AGENTE,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("Ola! Em qual regiao voce procura?", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=None,
        )
    )
    await session.commit()

    linha = await session.get(Message, identificador)
    assert linha is not None
    assert linha.status is None
    assert linha.provider_message_id is None


async def test_varias_linhas_de_saida_convivem(session) -> None:
    """A UNIQUE (channel, provider_message_id) sobrevive ao nullable.

    Postgres nao considera dois NULLs iguais, entao as linhas de saida nao
    colidem entre si nem enfraquecem a dedup do TEC-125.
    """
    for _ in range(3):
        identificador = uuid.uuid4()
        session.add(
            Message(
                id=identificador,
                channel="whatsapp",
                provider_message_id=None,
                conversation_key="5511911112222",
                role=MessageRole.AGENTE,
                direction=MessageDirection.OUTBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=None,
                raw_payload=None,
                status=None,
            )
        )
    await session.commit()

    total = await session.scalar(
        text("SELECT count(*) FROM messages WHERE direction = 'OUTBOUND'")
    )
    assert total == 3


async def test_telemetria_e_um_para_um_com_a_mensagem(session) -> None:
    message = nova_mensagem("wamid.TELEMETRIA")
    session.add(message)
    await session.commit()

    session.add(
        MessageTelemetry(
            message_id=message.id,
            model="claude-sonnet-5",
            subagent="qualificador",
            tokens_in=1200,
            tokens_out=180,
            cost_usd=Decimal("0.006300"),
            latency_ms=1450,
        )
    )
    await session.commit()

    linha = await session.get(MessageTelemetry, message.id)
    assert linha is not None
    assert linha.cost_usd == Decimal("0.006300")

    session.add(
        MessageTelemetry(
            message_id=message.id,
            model="outro",
            subagent="roteador",
            tokens_in=1,
            tokens_out=1,
            cost_usd=None,
            latency_ms=1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
```

> Ajuste também `test_colunas_reservadas_nascem_nulas` e `test_mesmo_id_em_canais_diferentes_convive` para usar o novo `nova_mensagem`. O helper já devolve tudo preenchido, então eles só precisam continuar chamando-o. O import `select` continua em uso por eles; `text` é novo.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_message_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'MessageTelemetry'`

- [ ] **Step 3: Atualizar o modelo**

Em `src/mobia/domain/messages/models.py`, troque os imports e a classe `Message`, e acrescente `MessageTelemetry`:

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mobia.domain.messages.status import MessageStatus
```

Dentro de `Message`, as colunas mudam assim:

```python
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Id externo do lead, invariante a direcao: e por ele que a conversa e
    # agrupada, porque sender e recipient se invertem entre entrada e saida.
    # `conversations` de verdade e TEC-129/TEC-130.
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)

    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Cifrados com AES-GCM, AAD `{id}:{coluna}`. A cifra e explicita nos dois
    # escritores em vez de um TypeDecorator porque o bind do decorator nao
    # conhece o id da linha, e sem o id no AAD o ciphertext pode ser movido de
    # um lead para outro.
    text_body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # NULL significa "nao participa do pipeline de ingestao" -- e o que a linha
    # de saida grava. Ver a docstring do sweeper.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

`queued_at`, `processed_at`, `last_error`, `envelope_context` e `claimed_at` ficam como estão.

E `__table_args__`:

```python
    __table_args__ = (
        Index("ix_messages_status_created_at", "status", "created_at"),
        # A consulta que TEC-127 faz a cada turno: as N mensagens mais recentes
        # de uma conversa, nas duas direcoes.
        Index(
            "ix_messages_timeline",
            "channel",
            "conversation_key",
            created_at.desc(),
        ),
        UniqueConstraint(
            "channel",
            "provider_message_id",
            name="uq_messages_channel_provider_message_id",
        ),
    )
```

> `created_at.desc()` dentro de `__table_args__` referencia a coluna já declarada acima na classe. Se o mypy reclamar, use `Index("ix_messages_timeline", "channel", "conversation_key", text("created_at DESC"))` com `from sqlalchemy import text`.

Ao fim do arquivo:

```python
class MessageTelemetry(Base):
    """Tokens, custo e latencia de uma resposta do agente.

    Fica ao lado e nao dentro de `messages` porque as duas tabelas respondem a
    perguntas diferentes: TEC-127 le a linha do tempo e nao quer saber de custo;
    o painel de custo soma dolares e nao deve tocar em conteudo de lead.
    """

    __tablename__ = "message_telemetry"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    subagent: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)

    # NULL = modelo sem preco cadastrado. Gravar 0.00 somaria silenciosamente no
    # painel e faria o custo parecer menor do que foi; NULL aparece como lacuna.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

> `JSONB` e `Text` deixam de ser usados por `Message`. Remova-os do import se o ruff apontar `F401`.

- [ ] **Step 4: Escrever a migração**

Crie `alembic/versions/0004_timeline_telemetria_e_cifra.py`:

```python
"""linha do tempo da conversa, telemetria e cifra do conteudo

TEC-126. Tres mudancas na mesma tabela, numa migration so porque nenhuma delas
deixa o esquema coerente sozinha:

* `messages` deixa de ser "o que chegou" e vira a linha do tempo da conversa.
* `text_body` e `raw_payload` passam a bytea cifrado.
* `message_telemetry` nasce.

O `downgrade` **apaga as linhas OUTBOUND**: elas nao cabem no esquema anterior,
onde `provider_message_id` e `status` sao NOT NULL. E perda de dado consciente,
e o motivo de o rollback so ser seguro enquanto o agente do TEC-134 nao existir.

Revision ID: 0004
Revises: 0003
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from mobia.infra.crypto import aad_de, decrypt, decrypt_json, encrypt, encrypt_json

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_PARA_O_DOMINIO = """
    UPDATE messages SET content_type = CASE content_type
        WHEN 'text' THEN 'TEXTO'
        WHEN 'audio' THEN 'AUDIO'
        WHEN 'image' THEN 'IMAGEM'
        WHEN 'document' THEN 'DOCUMENTO'
        ELSE 'DESCONHECIDO'
    END
"""

_PARA_A_META = """
    UPDATE messages SET content_type = CASE content_type
        WHEN 'TEXTO' THEN 'text'
        WHEN 'AUDIO' THEN 'audio'
        WHEN 'IMAGEM' THEN 'image'
        WHEN 'DOCUMENTO' THEN 'document'
        ELSE 'unknown'
    END
"""


def upgrade() -> None:
    # 1. Colunas da linha do tempo, nullable primeiro para poder preencher.
    op.add_column("messages", sa.Column("role", sa.String(16), nullable=True))
    op.add_column("messages", sa.Column("direction", sa.String(8), nullable=True))
    op.add_column("messages", sa.Column("conversation_key", sa.String(64), nullable=True))
    op.execute(
        """
        UPDATE messages
           SET role = 'LEAD',
               direction = 'INBOUND',
               conversation_key = sender_external_id
        """
    )
    op.alter_column("messages", "role", nullable=False)
    op.alter_column("messages", "direction", nullable=False)
    op.alter_column("messages", "conversation_key", nullable=False)

    # 2. `received_at` mente numa linha de saida.
    op.alter_column("messages", "received_at", new_column_name="created_at")
    op.drop_index("ix_messages_status_received_at", table_name="messages")
    op.create_index("ix_messages_status_created_at", "messages", ["status", "created_at"])

    # 3. O que so a entrada tem passa a nullable.
    op.alter_column("messages", "provider_message_id", nullable=True)
    op.alter_column("messages", "sender_external_id", nullable=True)
    op.alter_column("messages", "recipient_external_id", nullable=True)
    op.alter_column("messages", "status", nullable=True)

    op.execute(_PARA_O_DOMINIO)

    # 4. Cifra. Colunas novas, backfill, troca -- nunca `USING` no ALTER, porque
    # a cifra acontece em Python e o banco nao tem a chave.
    op.add_column("messages", sa.Column("text_body_cifrado", sa.LargeBinary(), nullable=True))
    op.add_column("messages", sa.Column("raw_payload_cifrado", sa.LargeBinary(), nullable=True))

    conexao = op.get_bind()
    linhas = conexao.execute(sa.text("SELECT id, text_body, raw_payload FROM messages")).fetchall()
    for linha in linhas:
        conexao.execute(
            sa.text(
                "UPDATE messages"
                "   SET text_body_cifrado = :texto, raw_payload_cifrado = :payload"
                " WHERE id = :id"
            ),
            {
                "id": linha.id,
                "texto": encrypt(linha.text_body, aad_de(linha.id, "text_body")),
                "payload": encrypt_json(linha.raw_payload, aad_de(linha.id, "raw_payload")),
            },
        )

    op.drop_column("messages", "text_body")
    op.drop_column("messages", "raw_payload")
    op.alter_column("messages", "text_body_cifrado", new_column_name="text_body")
    op.alter_column("messages", "raw_payload_cifrado", new_column_name="raw_payload")

    # 5. O indice da consulta de TEC-127.
    op.create_index(
        "ix_messages_timeline",
        "messages",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )

    # 6. Telemetria.
    op.create_table(
        "message_telemetry",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("subagent", sa.String(32), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("message_telemetry")
    op.drop_index("ix_messages_timeline", table_name="messages")

    # A linha de saida nao cabe no esquema anterior. Ver a docstring do modulo.
    op.execute("DELETE FROM messages WHERE direction = 'OUTBOUND'")

    op.add_column("messages", sa.Column("text_body_claro", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("raw_payload_claro", postgresql.JSONB(), nullable=True))

    conexao = op.get_bind()
    linhas = conexao.execute(sa.text("SELECT id, text_body, raw_payload FROM messages")).fetchall()
    for linha in linhas:
        conexao.execute(
            sa.text(
                "UPDATE messages"
                "   SET text_body_claro = :texto,"
                "       raw_payload_claro = CAST(:payload AS jsonb)"
                " WHERE id = :id"
            ),
            {
                "id": linha.id,
                "texto": decrypt(linha.text_body, aad_de(linha.id, "text_body")),
                # O CAST no SQL espera texto JSON ou NULL, entao o dict decifrado
                # volta a ser string aqui.
                "payload": None
                if linha.raw_payload is None
                else json.dumps(decrypt_json(linha.raw_payload, aad_de(linha.id, "raw_payload"))),
            },
        )

    op.drop_column("messages", "text_body")
    op.drop_column("messages", "raw_payload")
    op.alter_column("messages", "text_body_claro", new_column_name="text_body")
    op.alter_column("messages", "raw_payload_claro", new_column_name="raw_payload")
    op.execute("UPDATE messages SET raw_payload = '{}'::jsonb WHERE raw_payload IS NULL")
    op.alter_column("messages", "raw_payload", nullable=False)

    op.execute(_PARA_A_META)

    op.alter_column("messages", "status", nullable=False)
    op.alter_column("messages", "recipient_external_id", nullable=False)
    op.alter_column("messages", "sender_external_id", nullable=False)
    op.alter_column("messages", "provider_message_id", nullable=False)

    # Renomeia antes de indexar: o create_index referencia a coluna pelo nome, e
    # ate o alter_column ela ainda se chama `created_at`.
    op.drop_index("ix_messages_status_created_at", table_name="messages")
    op.alter_column("messages", "created_at", new_column_name="received_at")
    op.create_index("ix_messages_status_received_at", "messages", ["status", "received_at"])

    op.drop_column("messages", "conversation_key")
    op.drop_column("messages", "direction")
    op.drop_column("messages", "role")
```

> Nos dois sentidos, a ordem é **renomear a coluna, depois mexer no índice**: `create_index` referencia a coluna pelo nome, e antes do `alter_column` ela ainda tem o nome antigo. Se o `upgrade` rodar num banco onde a 0003 já apagou `ix_messages_provider_message_id`, nada aqui depende disso — os índices tocados são só os de `status`.

- [ ] **Step 5: Corrigir o SQL do sweeper para o rename**

Em `src/mobia/workers/jobs/sweep_stalled.py`, dentro de `_SELECIONAR_PARADAS`, troque as três ocorrências de `received_at` por `created_at`:

```python
_SELECIONAR_PARADAS = text(
    """
    SELECT id
      FROM messages
     WHERE attempts < :max_attempts
       AND (
            (status = 'RECEIVED'
             AND created_at < now() - make_interval(secs => :received_after))
         OR (status IN ('QUEUED', 'PROCESSING', 'FAILED')
             AND COALESCE(queued_at, created_at)
                 < now() - make_interval(secs => :inflight_after))
       )
     ORDER BY created_at
     LIMIT :limite
       FOR UPDATE SKIP LOCKED
    """
)
```

E na docstring, onde diz `COALESCE(queued_at, received_at)`, troque para `COALESCE(queued_at, created_at)`.

- [ ] **Step 6: Acrescentar a tabela nova ao truncate**

Em `tests/conftest.py`:

```python
TABELAS = ("message_telemetry", "outbound_dispatches", "messages")
```

- [ ] **Step 7: Ajustar o helper do teste do sweeper**

Em `tests/integration/test_sweep_stalled.py`, dentro de `mensagem(...)`, substitua a construção do `Message`:

```python
    identificador = uuid.uuid4()
    message = Message(
        id=identificador,
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        conversation_key="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("oi", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=status,
        attempts=attempts,
        created_at=instante,
        queued_at=instante if status != MessageStatus.RECEIVED else None,
    )
```

Com os imports correspondentes:

```python
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.infra.crypto import aad_de, encrypt
```

E na linha 178, `order_by(Message.received_at)` vira `order_by(Message.created_at)`.

- [ ] **Step 8: Ajustar o teste de migração para decifrar**

Em `tests/integration/test_migrations.py`, acrescente o import:

```python
from mobia.infra.crypto import aad_de, decrypt
```

E troque a asserção de conteúdo:

```python
    assert len(sobreviventes) == 1, "a migration tem de resolver a duplicata, nao abortar"
    assert sobreviventes[0].id == antiga, "sobrevive a primeira entrega, que foi a processada"
    assert (
        decrypt(sobreviventes[0].text_body, aad_de(sobreviventes[0].id, "text_body"))
        == "primeira entrega"
    ), "a 0004 tem de cifrar as linhas que ja existiam, nao so as novas"
```

Acrescente também à docstring do módulo:

```
A partir da 0004 este teste tambem prova o backfill de cifra: as linhas sao
inseridas em texto claro no esquema da 0002 e tem de voltar cifradas no head.
```

- [ ] **Step 9: Rodar as migrações e a suíte**

```bash
docker compose up -d
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m pytest -q
```
Expected: PASS.

- [ ] **Step 10: Provar que o rollback funciona**

```bash
.venv/Scripts/python -m alembic downgrade 0003
.venv/Scripts/python -m alembic upgrade head
```
Expected: os dois comandos terminam sem erro. Reversibilidade é critério de aceite do TEC-216.

- [ ] **Step 11: Lint e tipos**

Run: `.venv/Scripts/python -m ruff check src tests && .venv/Scripts/python -m ruff format src tests && .venv/Scripts/python -m mypy`
Expected: sem erro.

- [ ] **Step 12: Commit**

```bash
git add alembic/versions/0004_timeline_telemetria_e_cifra.py src/mobia/domain/messages/models.py src/mobia/workers/jobs/sweep_stalled.py tests/
git commit -m "feat(TEC-126): messages vira linha do tempo e ganha telemetria cifrada"
```

---

## Task 5: Ingestão grava papel, direção, conversa e conteúdo cifrado

**Files:**
- Modify: `src/mobia/domain/messages/service.py`
- Modify: `tests/integration/test_ingestion_service.py`

**Interfaces:**
- Consumes: `crypto` (Task 1), `enums` (Task 2), modelo (Task 4)
- Produces: linhas `INBOUND`/`LEAD` com `conversation_key = sender_external_id` e conteúdo cifrado.

- [ ] **Step 1: Escrever o teste que vai falhar**

Acrescente a `tests/integration/test_ingestion_service.py`:

```python
from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.infra.crypto import aad_de, decrypt, decrypt_json


async def test_entrada_grava_papel_direcao_e_conversa(session, redis_pool) -> None:
    servico = IngestionService(get_sessionmaker(), redis_pool)
    parsed = parse_meta_envelope(envelope_valido())

    (message_id,) = await servico.ingest(parsed)

    linha = await session.get(Message, message_id)
    assert linha is not None
    assert linha.role == MessageRole.LEAD
    assert linha.direction == MessageDirection.INBOUND
    assert linha.conversation_key == linha.sender_external_id


async def test_conteudo_vai_cifrado_para_o_banco(session, redis_pool) -> None:
    """Um SELECT cru nao pode devolver o que a Marina escreveu."""
    servico = IngestionService(get_sessionmaker(), redis_pool)
    parsed = parse_meta_envelope(envelope_valido())

    (message_id,) = await servico.ingest(parsed)

    cru = (
        await session.execute(
            sql("SELECT text_body, raw_payload FROM messages WHERE id = :id"),
            {"id": message_id},
        )
    ).one()
    assert isinstance(cru.text_body, bytes | memoryview)
    assert b"zona sul" not in bytes(cru.text_body)

    assert decrypt(bytes(cru.text_body), aad_de(message_id, "text_body")) is not None
    assert decrypt_json(bytes(cru.raw_payload), aad_de(message_id, "raw_payload")) is not None
```

> `envelope_valido()` já existe neste arquivo desde o TEC-122; use o helper que estiver lá. Se o corpo do texto dele não contiver "zona sul", ajuste a asserção para o texto que ele de fato manda — o ponto é que o texto em claro não aparece nos bytes.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_ingestion_service.py -v`
Expected: FAIL — a linha não tem `role`, ou o `INSERT` estoura por `conversation_key` NOT NULL.

- [ ] **Step 3: Implementar**

Em `src/mobia/domain/messages/service.py`, acrescente os imports:

```python
from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.infra.crypto import aad_de, encrypt, encrypt_json
```

E substitua a montagem de `valores` dentro de `_persist`:

```python
        valores = []
        for item in parsed:
            identificador = uuid.uuid4()
            valores.append(
                {
                    "id": identificador,
                    "channel": channel,
                    "provider_message_id": item.provider_message_id,
                    "sender_external_id": item.sender_external_id,
                    "recipient_external_id": item.recipient_external_id,
                    # Quem fala e o lead, entao a conversa e a dele. Na saida
                    # sender e recipient se invertem e esta coluna nao.
                    "conversation_key": item.sender_external_id,
                    "role": MessageRole.LEAD,
                    "direction": MessageDirection.INBOUND,
                    "content_type": item.content_type,
                    "text_body": encrypt(item.text_body, aad_de(identificador, "text_body")),
                    "raw_payload": encrypt_json(
                        item.raw_payload, aad_de(identificador, "raw_payload")
                    ),
                    "status": MessageStatus.RECEIVED,
                }
            )
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/ tests/features/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/domain/messages/service.py tests/integration/test_ingestion_service.py
git commit -m "feat(TEC-126): ingestao grava papel, direcao, conversa e conteudo cifrado"
```

---

## Task 6: O sweeper ignora a fala do agente

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_stalled.py`
- Modify: `tests/integration/test_sweep_stalled.py`

**Interfaces:**
- Consumes: `MessageDirection` (Task 2), modelo (Task 4)

- [ ] **Step 1: Escrever o teste que vai falhar**

Acrescente a `tests/integration/test_sweep_stalled.py`:

```python
async def test_sweeper_ignora_linha_de_saida(session, redis_pool, settings) -> None:
    """A fala do agente nao e mensagem recebida e nao volta para a fila.

    Sem o filtro, o sweeper do TEC-122 varreria a propria resposta do agente e
    a mandaria para `process_message` -- um efeito externo a mais por resposta.
    """
    identificador = uuid.uuid4()
    antigo = datetime.now(UTC) - timedelta(seconds=3600)
    session.add(
        Message(
            id=identificador,
            channel="whatsapp",
            provider_message_id=None,
            conversation_key="5511911112222",
            role=MessageRole.AGENTE,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.RECEIVED,
            created_at=antigo,
        )
    )
    await session.commit()

    assert await sweep_stalled(contexto(redis_pool, settings)) == 0
    assert await redis_pool.queued_jobs() == []
```

> O `status=MessageStatus.RECEIVED` aqui é deliberado e é o coração do teste: mesmo que alguém grave uma linha de saída com status de entrada, o filtro de direção tem de segurar. As outras duas defesas (status NULL e ausência de `provider_message_id`) não são exercitadas por este teste — este prova a que resta.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_sweep_stalled.py::test_sweeper_ignora_linha_de_saida -v`
Expected: FAIL — `assert 1 == 0`

- [ ] **Step 3: Implementar o filtro**

Em `_SELECIONAR_PARADAS`, acrescente a condição logo depois do `WHERE`:

```python
     WHERE direction = 'INBOUND'
       AND attempts < :max_attempts
```

E acrescente à docstring de `sweep_stalled`, antes do parágrafo sobre locks:

```
    O filtro `direction = 'INBOUND'` existe porque desde o TEC-126 a tabela
    guarda tambem a fala do agente. Varrer uma linha OUTBOUND a mandaria para
    `process_message`, que emitiria um efeito externo por uma mensagem que
    ninguem enviou. A linha de saida ja nasce com `status` NULL, o que sozinho
    bastaria -- o filtro esta aqui para que a garantia nao dependa de quem
    escreve lembrar disso.
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_sweep_stalled.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/workers/jobs/sweep_stalled.py tests/integration/test_sweep_stalled.py
git commit -m "fix(TEC-126): sweeper deixa de varrer a fala do proprio agente"
```

---

## Task 7: `MessageRecorder` e a tabela de preços

**Files:**
- Create: `src/mobia/domain/messages/recorder.py`
- Create: `tests/integration/test_recorder.py`
- Modify: `src/mobia/app/config.py`

**Interfaces:**
- Consumes: `crypto` (Task 1), `enums` (Task 2), `Message`/`MessageTelemetry` (Task 4)
- Produces:
  - `PRECOS_POR_MODELO: dict[str, tuple[Decimal, Decimal]]` em `mobia.app.config`
  - `custo_em_dolar(model: str, tokens_in: int, tokens_out: int) -> Decimal | None`
  - `MessageRecorder(session_factory).record_agent_message(...) -> uuid.UUID | None`

- [ ] **Step 1: Escrever os testes que vão falhar**

Crie `tests/integration/test_recorder.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select

from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.recorder import MessageRecorder, custo_em_dolar
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker


def recorder() -> MessageRecorder:
    return MessageRecorder(get_sessionmaker())


async def gravar(**extra) -> tuple[MessageRecorder, object]:
    argumentos = {
        "conversation_key": "5511911112222",
        "channel": "whatsapp",
        "text": "Ola! Em qual regiao voce procura?",
        "model": "claude-sonnet-5",
        "subagent": "qualificador",
        "tokens_in": 1200,
        "tokens_out": 180,
        "latency_ms": 1450,
    }
    argumentos.update(extra)
    instancia = recorder()
    return instancia, await instancia.record_agent_message(**argumentos)


async def test_grava_a_fala_do_agente_na_linha_do_tempo(session) -> None:
    _, message_id = await gravar()

    linha = await session.get(Message, message_id)
    assert linha is not None
    assert linha.role == MessageRole.AGENTE
    assert linha.direction == MessageDirection.OUTBOUND
    assert linha.conversation_key == "5511911112222"
    assert linha.status is None, "a fala do agente nao entra no pipeline de ingestao"
    assert linha.provider_message_id is None
    assert (
        decrypt(linha.text_body, aad_de(message_id, "text_body"))
        == "Ola! Em qual regiao voce procura?"
    )


async def test_telemetria_traz_tokens_custo_latencia_e_subagente(session) -> None:
    _, message_id = await gravar()

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.tokens_in == 1200
    assert telemetria.tokens_out == 180
    assert telemetria.latency_ms == 1450
    assert telemetria.subagent == "qualificador"
    assert telemetria.model == "claude-sonnet-5"
    assert telemetria.cost_usd == custo_em_dolar("claude-sonnet-5", 1200, 180)
    assert telemetria.cost_usd is not None and telemetria.cost_usd > 0


async def test_modelo_sem_preco_grava_lacuna_e_nao_zero(session, caplog) -> None:
    """Zero somaria silenciosamente no painel e faria o custo parecer menor."""
    import logging

    with caplog.at_level(logging.WARNING):
        _, message_id = await gravar(model="modelo-que-nao-existe")

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.cost_usd is None
    assert "telemetry.unknown_model" in caplog.text


async def test_falha_de_telemetria_preserva_a_mensagem(session, caplog) -> None:
    """O criterio pede que a resposta seja entregue mesmo sem telemetria.

    `subagent` e VARCHAR(32): um valor maior estoura o INSERT da telemetria e
    so dele -- e uma falha de banco de verdade, nao um mock.
    """
    import logging

    with caplog.at_level(logging.WARNING):
        _, message_id = await gravar(subagent="x" * 100)

    assert message_id is not None, "o recorder nao pode devolver None por causa da telemetria"

    linha = await session.get(Message, message_id)
    assert linha is not None, "a fala do agente sobrevive a falha de telemetria"

    ausente = await session.get(MessageTelemetry, message_id)
    assert ausente is None
    assert "telemetry.record_failed" in caplog.text


async def test_nunca_propaga_excecao(session) -> None:
    """Quem chama esta no meio de responder ao lead e nao pode ser derrubado."""
    _, message_id = await gravar(conversation_key="x" * 200)
    assert message_id is None


def test_custo_e_calculado_por_milhao_de_tokens() -> None:
    esperado = (Decimal(1200) / Decimal(1_000_000)) * Decimal("3.00") + (
        Decimal(180) / Decimal(1_000_000)
    ) * Decimal("15.00")
    assert custo_em_dolar("claude-sonnet-5", 1200, 180) == esperado.quantize(Decimal("0.000001"))


def test_modelo_desconhecido_nao_tem_custo() -> None:
    assert custo_em_dolar("modelo-que-nao-existe", 10, 10) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/Scripts/python -m pytest tests/integration/test_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mobia.domain.messages.recorder'`

- [ ] **Step 3: Acrescentar a tabela de preços**

Ao fim de `src/mobia/app/config.py`:

```python
# Preco em dolar por 1 milhao de tokens, (entrada, saida). O custo e calculado e
# **materializado** no momento do registro: mudar um preco aqui amanha nao pode
# reescrever o que ja foi gasto.
PRECOS_POR_MODELO: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("15.00"), Decimal("75.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5-20251001": (Decimal("1.00"), Decimal("5.00")),
}
```

Com `from decimal import Decimal` no topo do arquivo.

- [ ] **Step 4: Implementar `src/mobia/domain/messages/recorder.py`**

```python
import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import PRECOS_POR_MODELO
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.infra.crypto import aad_de, encrypt

log = structlog.get_logger(__name__)

_CENTAVO_DE_MILIONESIMO = Decimal("0.000001")


def custo_em_dolar(model: str, tokens_in: int, tokens_out: int) -> Decimal | None:
    """Devolve None para modelo sem preco cadastrado, nunca zero.

    Zero somaria silenciosamente no painel de custo e faria o gasto parecer
    menor do que foi. None aparece como lacuna e alguem conserta.
    """
    preco = PRECOS_POR_MODELO.get(model)
    if preco is None:
        return None
    entrada, saida = preco
    total = (Decimal(tokens_in) / Decimal(1_000_000)) * entrada + (
        Decimal(tokens_out) / Decimal(1_000_000)
    ) * saida
    return total.quantize(_CENTAVO_DE_MILIONESIMO)


class MessageRecorder:
    """Registra a fala do agente e a telemetria dela.

    Dois passos, nao uma transacao. Se os dois inserts fossem atomicos, uma
    falha de telemetria derrubaria junto o registro da fala -- e o criterio pede
    o oposto: a resposta e entregue normalmente e a falha de telemetria e
    registrada sem interromper o fluxo.

    E a mesma filosofia do `_try_enqueue` do TEC-122: persiste primeiro, o
    efeito secundario e otimista e engole a propria falha.

    Nenhum metodo propaga excecao. Quem chama esta no meio de responder ao lead.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_agent_message(
        self,
        *,
        conversation_key: str,
        channel: str,
        text: str,
        model: str,
        subagent: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        sender_external_id: str | None = None,
        recipient_external_id: str | None = None,
    ) -> uuid.UUID | None:
        identificador = uuid.uuid4()
        try:
            async with self._session_factory() as session:
                session.add(
                    Message(
                        id=identificador,
                        channel=channel,
                        provider_message_id=None,
                        sender_external_id=sender_external_id,
                        recipient_external_id=recipient_external_id,
                        conversation_key=conversation_key,
                        role=MessageRole.AGENTE,
                        direction=MessageDirection.OUTBOUND,
                        content_type=MessageContentType.TEXTO,
                        text_body=encrypt(text, aad_de(identificador, "text_body")),
                        raw_payload=None,
                        # NULL: a fala do agente nao participa do pipeline de
                        # ingestao e o sweeper nao pode reivindica-la.
                        status=None,
                    )
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "message.record_failed",
                conversation_key=conversation_key,
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return None

        await self._registrar_telemetria(
            identificador, model, subagent, tokens_in, tokens_out, latency_ms
        )
        return identificador

    async def _registrar_telemetria(
        self,
        message_id: uuid.UUID,
        model: str,
        subagent: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
    ) -> None:
        custo = custo_em_dolar(model, tokens_in, tokens_out)
        if custo is None:
            log.warning("telemetry.unknown_model", model=model, message_id=str(message_id))

        try:
            async with self._session_factory() as session:
                session.add(
                    MessageTelemetry(
                        message_id=message_id,
                        model=model,
                        subagent=subagent,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_usd=custo,
                        latency_ms=latency_ms,
                    )
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "telemetry.record_failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        log.info(
            "telemetry.recorded",
            message_id=str(message_id),
            model=model,
            subagent=subagent,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/Scripts/python -m pytest tests/integration/test_recorder.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 6: Provar a consulta que TEC-127 vai fazer**

É a razão de existir do índice `ix_messages_timeline` e da coluna `conversation_key`. Sem este teste, a história entrega o esquema sem nunca demonstrar que ele responde à pergunta que motivou o desenho.

Acrescente a `tests/integration/test_recorder.py`:

```python
async def test_timeline_intercala_entrada_e_saida_da_mesma_conversa(session) -> None:
    """A consulta que TEC-127 faz a cada turno.

    `sender` e `recipient` se invertem entre as direcoes; `conversation_key` nao
    — e por isso que ela existe.
    """
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from mobia.domain.messages.enums import MessageContentType
    from mobia.domain.messages.status import MessageStatus

    base = datetime.now(UTC) - timedelta(minutes=10)
    entrada = _uuid.uuid4()
    session.add(
        Message(
            id=entrada,
            channel="whatsapp",
            provider_message_id="wamid.TIMELINE",
            sender_external_id="5511911112222",
            recipient_external_id="222222222",
            conversation_key="5511911112222",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=base,
        )
    )
    await session.commit()

    _, saida = await gravar(conversation_key="5511911112222")

    # Outra conversa, para provar que o agrupamento nao vaza.
    _, outra = await gravar(conversation_key="5511999998888")

    linhas = (
        await session.scalars(
            select(Message)
            .where(Message.channel == "whatsapp", Message.conversation_key == "5511911112222")
            .order_by(Message.created_at.desc())
            .limit(20)
        )
    ).all()

    assert [linha.id for linha in linhas] == [saida, entrada]
    assert outra not in [linha.id for linha in linhas]
    assert [linha.direction for linha in linhas] == [
        MessageDirection.OUTBOUND,
        MessageDirection.INBOUND,
    ]
```

Run: `.venv/Scripts/python -m pytest tests/integration/test_recorder.py -v`
Expected: PASS, 8 testes.

- [ ] **Step 7: Lint e tipos**

Run: `.venv/Scripts/python -m ruff check src tests && .venv/Scripts/python -m ruff format src tests && .venv/Scripts/python -m mypy`
Expected: sem erro.

- [ ] **Step 8: Commit**

```bash
git add src/mobia/app/config.py src/mobia/domain/messages/recorder.py tests/integration/test_recorder.py
git commit -m "feat(TEC-126): recorder da fala do agente com telemetria best-effort"
```

---

## Task 8: Critérios de aceite como testes executáveis

Os quatro cenários Gherkin viram um arquivo só, no formato que o TEC-122 estabeleceu — cada cenário com o nome do critério, para que a tabela do README aponte para algo real.

**Files:**
- Create: `tests/features/test_telemetria_de_mensagens.py`
- Modify: `README.md`

- [ ] **Step 1: Escrever os quatro cenários**

Crie `tests/features/test_telemetria_de_mensagens.py`:

```python
"""Criterios de aceite do TEC-126 como testes executaveis.

Cada teste corresponde a um cenario Gherkin da historia. Ha sobreposicao
deliberada com os testes de unidade e integracao: estes existem para que o
criterio de aceite tenha um endereco, nao para cobrir codigo novo.
"""

import logging

from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.messages.schemas import parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker

TELEFONE = "5511987654321"


def envelope(texto: str = "quero apto na zona sul") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [
                                {
                                    "id": "wamid.CRITERIO",
                                    "from": TELEFONE,
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


async def test_registrar_mensagem_de_entrada_do_lead(session, redis_pool) -> None:
    """Cenario: Registrar mensagem de entrada do lead."""
    servico = IngestionService(get_sessionmaker(), redis_pool)

    (message_id,) = await servico.ingest(parse_meta_envelope(envelope()))

    linha = await session.get(Message, message_id)
    assert linha is not None
    assert linha.role == MessageRole.LEAD
    assert linha.channel == "whatsapp"
    assert linha.content_type == MessageContentType.TEXTO
    assert linha.direction == MessageDirection.INBOUND
    assert linha.created_at is not None


async def test_registrar_resposta_do_agente_com_custo(session) -> None:
    """Cenario: Registrar resposta do agente com custo."""
    recorder = MessageRecorder(get_sessionmaker())

    message_id = await recorder.record_agent_message(
        conversation_key=TELEFONE,
        channel="whatsapp",
        text="Ola! Em qual regiao voce procura?",
        model="claude-sonnet-5",
        subagent="qualificador",
        tokens_in=1200,
        tokens_out=180,
        latency_ms=1450,
    )

    telemetria = await session.get(MessageTelemetry, message_id)
    assert telemetria is not None
    assert telemetria.tokens_in == 1200
    assert telemetria.tokens_out == 180
    assert telemetria.cost_usd is not None and telemetria.cost_usd > 0
    assert telemetria.latency_ms == 1450
    assert telemetria.subagent == "qualificador"


async def test_conteudo_pessoal_nao_vaza_para_o_log(session, redis_pool, caplog) -> None:
    """Cenario: Conteudo pessoal nao vaza para o log."""
    servico = IngestionService(get_sessionmaker(), redis_pool)

    with caplog.at_level(logging.INFO):
        (message_id,) = await servico.ingest(
            parse_meta_envelope(envelope(f"me liga no {TELEFONE}"))
        )

    assert TELEFONE not in caplog.text
    assert "zona sul" not in caplog.text

    cru = await session.scalar(
        sql("SELECT text_body FROM messages WHERE id = :id"), {"id": message_id}
    )
    assert TELEFONE.encode() not in bytes(cru)
    assert decrypt(bytes(cru), aad_de(message_id, "text_body")) == f"me liga no {TELEFONE}"


async def test_falha_de_telemetria_nao_derruba_o_atendimento(session, caplog) -> None:
    """Cenario: Falha de telemetria nao derruba o atendimento."""
    recorder = MessageRecorder(get_sessionmaker())

    with caplog.at_level(logging.WARNING):
        message_id = await recorder.record_agent_message(
            conversation_key=TELEFONE,
            channel="whatsapp",
            text="Ola! Em qual regiao voce procura?",
            model="claude-sonnet-5",
            subagent="x" * 100,
            tokens_in=1200,
            tokens_out=180,
            latency_ms=1450,
        )

    assert message_id is not None
    assert await session.get(Message, message_id) is not None
    assert await session.get(MessageTelemetry, message_id) is None
    assert "telemetry.record_failed" in caplog.text
```

- [ ] **Step 2: Rodar**

Run: `.venv/Scripts/python -m pytest tests/features/test_telemetria_de_mensagens.py -v`
Expected: PASS, 4 testes. Se `test_conteudo_pessoal_nao_vaza_para_o_log` falhar em `TELEFONE not in caplog.text`, o culpado é um log que emite `sender_external_id` ou o próprio corpo — corrija o **log**, não o teste.

- [ ] **Step 3: Documentar no README**

Acrescente ao `README.md`, depois da seção do TEC-122:

```markdown
## TEC-126 — Telemetria de mensagens

| Cenário Gherkin | Teste |
|---|---|
| Registrar mensagem de entrada do lead | `tests/features/test_telemetria_de_mensagens.py::test_registrar_mensagem_de_entrada_do_lead` |
| Registrar resposta do agente com custo | `tests/features/test_telemetria_de_mensagens.py::test_registrar_resposta_do_agente_com_custo` |
| Conteúdo pessoal não vaza para o log | `tests/features/test_telemetria_de_mensagens.py::test_conteudo_pessoal_nao_vaza_para_o_log` |
| Falha de telemetria não derruba o atendimento | `tests/features/test_telemetria_de_mensagens.py::test_falha_de_telemetria_nao_derruba_o_atendimento` |

### Garantias

- `messages` é a linha do tempo da conversa: entrada e saída, agrupadas por
  `conversation_key` e ordenadas por `created_at`. `sender` e `recipient` se
  invertem entre as direções; `conversation_key` não.
- `text_body` e `raw_payload` são cifrados com AES-GCM antes do `INSERT`, com
  AAD `{message_id}:{coluna}` — ciphertext movido para outra linha não decifra.
  Em troca, `raw_payload` deixou de ser consultável por operador JSONB.
- Telemetria é gravada num segundo passo: falha nela perde o custo, nunca o
  registro da fala do agente.
- Modelo sem preço cadastrado grava `cost_usd` NULL, não zero.
- A chave de cifra vem de `CONTENT_ENCRYPTION_KEY` (32 bytes em base64). Rotação
  de chave não está implementada.
```

- [ ] **Step 4: Rodar a suíte inteira e os gates**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check src tests
.venv/Scripts/python -m ruff format --check src tests
.venv/Scripts/python -m mypy
```
Expected: tudo verde. É o mesmo conjunto que o CI do TEC-216 roda.

- [ ] **Step 5: Commit**

```bash
git add tests/features/test_telemetria_de_mensagens.py README.md
git commit -m "test(TEC-126): criterios de aceite como testes executaveis"
```

---

## Verificação final

- [ ] `.venv/Scripts/python -m pytest -q` — verde
- [ ] `.venv/Scripts/python -m pytest -m perf` — o teste de latência do TEC-122 continua dentro do orçamento. A cifra acrescenta um AES-GCM por mensagem ao caminho da requisição; se o p95 estourar 300 ms, isso é um achado real e precisa ser reportado, não contornado afrouxando o limite.
- [ ] `alembic downgrade 0003 && alembic upgrade head` — sem erro
- [ ] `ruff check`, `ruff format --check`, `mypy` — sem erro
- [ ] Nenhum `git grep -n "text_body" src | grep log` — nada loga conteúdo

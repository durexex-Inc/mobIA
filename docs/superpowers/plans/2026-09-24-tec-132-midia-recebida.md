# TEC-132 — Mídia recebida: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** imagem e documento recebidos pelo WhatsApp ficam guardados cifrados, com ponteiro na mensagem, e o lead recebe a confirmação e o pedido de texto sem que o agente afirme nada sobre o conteúdo.

**Architecture:**
- A legenda vira `text_body` no parser.
- A ingestão grava uma linha PENDENTE em `midias_recebidas` na mesma transação da mensagem e enfileira `baixar_midia`.
- O job resolve o `media_id` na Graph API, confere allowlist, teto e `sha256`, cifra os bytes com AES-GCM e grava por uma porta `ArmazemDeMidia`, com adaptador local e S3.
- No turno, uma mídia sem nenhum texto do lead na rajada recebe texto fixo antes da moderação e do modelo. Com texto, o turno segue normal, e o modelo vê um marcador dizendo que não enxerga a mídia.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, ARQ, httpx, `cryptography`, `aioboto3` (nova), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-132-midia-recebida-design.md`. Leia antes de começar. D1–D4 são referidas por número.

## Global Constraints

- **Só IMAGEM e DOCUMENTO** ganham linha em `midias_recebidas` e download. Áudio, vídeo, figurinha e localização não mudam.
- **O turno nunca espera o download nem lê a mídia.** O status do download não muda a resposta.
- Texto que o lead recebe: português **com** acento, exatamente assim:
  - `TEXTO_DA_CONFIRMACAO_DE_IMAGEM = "Recebi sua imagem! Por aqui eu ainda não consigo ver fotos. Me conta em texto qual imóvel ou característica te interessou?"`
  - `TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO = "Recebi seu arquivo! Por aqui eu ainda não consigo abrir documentos. Me conta em texto o que você precisa, que eu te ajudo?"`
- Marcadores do contexto, que são texto para o modelo e vão **sem** acento:
  - IMAGEM: `"(imagem recebida; o conteudo nao esta visivel para voce)"`
  - DOCUMENTO: `"(documento recebido; o conteudo nao esta visivel para voce)"`
- Comentários e docstrings em `src/` e `tests/`: português **sem** acento. Prosa em `docs/`: com acento.
- Log nunca leva a URL de download da Meta (carrega credencial), o nome do arquivo nem o conteúdo.
- Chave do objeto: `midias/{message_id}`. AAD da cifra: `aad_de(message_id, "midia")`.
- Teto padrão: 25 MB (`26_214_400` bytes). Allowlist: `image/jpeg`, `image/png`, `image/webp`, `application/pdf`, `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/vnd.ms-excel`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- O prompt de sistema **não muda**: `-k margem_do_orcamento -s` tem de dar o mesmo antes e depois.
- Commits: `tipo(TEC-132): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Gates antes de todo commit, sem pipe:
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- Ferramenta Grep, nunca `grep -rn` no shell sobre `tests/`. Basename de teste novo único entre `unit`, `integration` e `features`: confira com Glob antes.

## Review Focus

1. **Rajada "quero esse" + foto:** o texto pendente faz o turno ser o normal, e o "quero esse" é respondido. Testado em `test_rajada_com_texto_roda_o_turno_normal` (Task 6).
2. **Lead em opt-out manda foto:** nenhuma confirmação sai. Testado em `test_optout_nao_recebe_confirmacao_de_midia` (Task 6).
3. **`file_size` da Meta mentindo:** o streaming aborta no teto, sem baixar tudo. Testado em `test_estouro_do_teto_no_streaming_recusa` (Task 5).
4. **Reentrega da Meta da mesma mídia:** a UNIQUE descarta a mensagem, e nenhuma segunda linha de mídia nem segundo job surge. Testado em `test_reentrega_nao_cria_segunda_midia` (Task 4).
5. **Download que falha depois de a confirmação sair:** a confirmação continua certa, e a linha vai para FALHOU sem tocar a conversa. Testado em `test_4xx_marca_falhou_sem_retentar` e na feature (Task 5 e Task 7).

---

## Mapa de arquivos

| arquivo | responsabilidade |
| --- | --- |
| Modify `src/mobia/infra/crypto.py` | `encrypt_bytes` / `decrypt_bytes` |
| Modify `src/mobia/domain/messages/schemas.py` | a legenda vira `text_body` |
| Modify `src/mobia/domain/context/montagem.py` (`_SEM_TEXTO`, `_texto_da`) | os marcadores novos, também com legenda |
| Create `src/mobia/domain/midia/__init__.py` | pacote |
| Create `src/mobia/domain/midia/armazem.py` | porta, `ArmazemLocal`, `ArmazemS3`, `armazem_da_config` |
| Create `src/mobia/domain/midia/models.py` | `MidiaRecebida` + vocabulário de status e motivo |
| Create `src/mobia/domain/midia/repositorio.py` | ler e marcar status, listar pendentes |
| Create `src/mobia/domain/midia/politica.py` | allowlist, teto, `chave_do_objeto` |
| Create `src/mobia/domain/midia/graph.py` | cliente da Graph API: resolver e baixar em streaming |
| Create `src/mobia/domain/midia/confirmacao.py` | os dois textos, o kind e o rótulo de subagente |
| Create `src/mobia/workers/jobs/baixar_midia.py` | o job |
| Create `src/mobia/workers/jobs/sweep_midias_pendentes.py` | o cron |
| Create `alembic/versions/0042_midias_recebidas.py` | a tabela |
| Modify `src/mobia/app/config.py` | `midia_*` |
| Modify `src/mobia/infra/queue.py` | `enqueue_baixar_midia` |
| Modify `src/mobia/domain/messages/service.py` (`_persist`, `ingest`) | a linha PENDENTE na mesma transação e o enqueue |
| Modify `src/mobia/domain/messages/rajada.py` (`ha_fala_pendente_antes`) | `com_texto` |
| Modify `src/mobia/domain/agente/turno.py` (antes do `if corpo:` da moderação, ~l.1553) | a resposta fixa |
| Modify `src/mobia/workers/main.py` | `ctx["armazem"]`, as funções e o cron |
| Modify `pyproject.toml`, `.gitignore`, `.env.example` (se existir), `tests/conftest.py` (`TABELAS`) | |
| Modify `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | RN-01.4 E-01 |

---

### Task 1: cifra de bytes, legenda e marcadores

**Files:**
- Modify: `src/mobia/infra/crypto.py`, `src/mobia/domain/messages/schemas.py`, `src/mobia/domain/context/montagem.py`
- Test: `tests/unit/test_crypto.py` (acrescentar), `tests/unit/test_legenda_de_midia.py`, `tests/unit/test_marcador_de_midia.py`

**Interfaces:**
- Produces:
  - `encrypt_bytes(dados: bytes, aad: str) -> bytes` e `decrypt_bytes(blob: bytes, aad: str) -> bytes`, em `mobia.infra.crypto`.
  - `parse_meta_envelope` passa a preencher `text_body` com a legenda de imagem e de documento.
  - `_texto_da` rende o marcador de mídia, com e sem legenda.

- [ ] **Step 1: Testes que falham**

Em `tests/unit/test_crypto.py`, acrescente, seguindo o padrão de fixture de chave que o arquivo já usa:

```python
def test_bytes_cifrados_voltam_iguais() -> None:
    dados = bytes(range(256)) * 10
    blob = encrypt_bytes(dados, "m-1:midia")
    assert blob != dados
    assert decrypt_bytes(blob, "m-1:midia") == dados


def test_bytes_com_aad_errado_nao_decifram() -> None:
    blob = encrypt_bytes(b"conteudo", "m-1:midia")
    with pytest.raises(DecryptionError):
        decrypt_bytes(blob, "m-2:midia")
```

`tests/unit/test_legenda_de_midia.py`:

```python
"""A legenda de imagem e documento vira texto. TEC-132, D3."""

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import parse_meta_envelope


def _envelope(mensagem: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "pn-1"},
                            "messages": [{"id": "wamid.1", "from": "5548999990000", **mensagem}],
                        }
                    }
                ]
            }
        ]
    }


def test_imagem_com_legenda() -> None:
    [msg] = parse_meta_envelope(
        _envelope({"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg", "caption": "esse aqui"}})
    )
    assert (msg.content_type, msg.text_body) == (MessageContentType.IMAGEM, "esse aqui")


def test_documento_com_legenda() -> None:
    [msg] = parse_meta_envelope(
        _envelope({"type": "document", "document": {"id": "d1", "mime_type": "application/pdf", "caption": "contrato"}})
    )
    assert (msg.content_type, msg.text_body) == (MessageContentType.DOCUMENTO, "contrato")


def test_imagem_sem_legenda_fica_sem_texto() -> None:
    [msg] = parse_meta_envelope(_envelope({"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg"}}))
    assert msg.text_body is None


def test_legenda_so_de_espacos_fica_sem_texto() -> None:
    [msg] = parse_meta_envelope(
        _envelope({"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg", "caption": "   "}})
    )
    assert msg.text_body is None
```

`tests/unit/test_marcador_de_midia.py`. Monte `Message` em memória. O `text_body` tem de estar cifrado com `aad_de(id, "text_body")`, e `_texto_da` decifra. Use a mesma fixture de chave de `test_crypto.py`: confira em `tests/unit/` como os testes que chamam `decrypt` obtêm a chave.

```python
"""O modelo ve que recebeu midia e que nao a enxerga. TEC-132, D4."""

import uuid

from mobia.domain.context.montagem import _texto_da
from mobia.domain.messages.enums import MessageContentType, MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, encrypt


def _linha(tipo: MessageContentType, texto: str | None) -> Message:
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        role=MessageRole.LEAD,
        content_type=tipo,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
    )


def test_imagem_sem_legenda() -> None:
    assert _texto_da(_linha(MessageContentType.IMAGEM, None)) == (
        "[LEAD] (imagem recebida; o conteudo nao esta visivel para voce)"
    )


def test_imagem_com_legenda_leva_marcador_e_legenda() -> None:
    assert _texto_da(_linha(MessageContentType.IMAGEM, "esse aqui ta disponivel?")) == (
        "[LEAD] (imagem recebida; o conteudo nao esta visivel para voce) esse aqui ta disponivel?"
    )


def test_documento_sem_legenda() -> None:
    assert _texto_da(_linha(MessageContentType.DOCUMENTO, None)) == (
        "[LEAD] (documento recebido; o conteudo nao esta visivel para voce)"
    )


def test_audio_nao_muda() -> None:
    assert _texto_da(_linha(MessageContentType.AUDIO, None)) == "[LEAD] (audio, sem transcricao)"


def test_texto_nao_muda() -> None:
    assert _texto_da(_linha(MessageContentType.TEXTO, "oi")) == "[LEAD] oi"
```

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_crypto.py tests/unit/test_legenda_de_midia.py tests/unit/test_marcador_de_midia.py --tb=short`
Expected: FAIL (`ImportError` de `encrypt_bytes`; legenda `None`; marcador antigo).

- [ ] **Step 2: A cifra de bytes**

Em `infra/crypto.py`, extraia o miolo de `encrypt`/`decrypt` para operar sobre bytes e faça as versões `str` delegarem. Assim o layout (`versao || nonce || ct || tag`), a guarda de tamanho mínimo e a de versão ficam num lugar só:

```python
def encrypt_bytes(dados: bytes, aad: str) -> bytes:
    """A mesma cifra de `encrypt`, sobre bytes. TEC-132: o arquivo de midia."""
    nonce = os.urandom(NONCE_BYTES)
    return bytes([VERSAO_ATUAL]) + nonce + _cifra().encrypt(nonce, dados, aad.encode())


def decrypt_bytes(blob: bytes, aad: str) -> bytes:
    """Inverso de `encrypt_bytes`, com as mesmas guardas de `decrypt`."""
    # (mova para ca as guardas de tamanho minimo, versao e InvalidTag de
    # `decrypt`, sem mudar as mensagens)
    ...


def encrypt(texto: str | None, aad: str) -> bytes | None:
    if texto is None:
        return None
    # (mantenha o comentario do nonce)
    return encrypt_bytes(texto.encode(), aad)


def decrypt(blob: bytes | None, aad: str) -> str | None:
    if blob is None:
        return None
    return decrypt_bytes(blob, aad).decode()
```

O `...` acima é o corpo atual de `decrypt`, **movido e não reescrito**: as mensagens de `DecryptionError` ficam idênticas, e `tests/unit/test_crypto.py` inteiro tem de continuar passando.

- [ ] **Step 3: A legenda**

Em `parse_meta_envelope`, depois do `if content_type is MessageContentType.TEXTO:`:

```python
                elif content_type in (MessageContentType.IMAGEM, MessageContentType.DOCUMENTO):
                    # TEC-132, D3. A legenda e o que o lead DISSE junto da
                    # midia -- "esse aqui ta disponivel?" -- e vira texto para
                    # passar por tudo o que texto passa: moderacao, opt-out,
                    # pedido de humano e turno. Legenda so de espacos e o mesmo
                    # que legenda nenhuma.
                    chave = "image" if content_type is MessageContentType.IMAGEM else "document"
                    legenda = ((message.get(chave) or {}).get("caption") or "").strip()
                    text_body = legenda or None
```

- [ ] **Step 4: Os marcadores**

Em `montagem.py`, troque as entradas IMAGEM e DOCUMENTO de `_SEM_TEXTO` pelos marcadores das Global Constraints, e faça `_texto_da` prefixar o marcador também quando há corpo, **só para mídia**:

```python
# TEC-132, D4. Para IMAGEM e DOCUMENTO o marcador aparece mesmo com legenda: a
# legenda sozinha ("esse aqui ta disponivel?") esconderia do modelo que existe
# uma midia que ele nao ve, e e exatamente ai que ele inventaria o conteudo.
_MARCADOR_DE_MIDIA: dict[str, str] = {
    MessageContentType.IMAGEM: "(imagem recebida; o conteudo nao esta visivel para voce)",
    MessageContentType.DOCUMENTO: "(documento recebido; o conteudo nao esta visivel para voce)",
}
```

```python
    corpo = decrypt(linha.text_body, aad_de(linha.id, "text_body"))
    marcador = _MARCADOR_DE_MIDIA.get(linha.content_type)
    if marcador is not None:
        corpo = marcador if corpo is None else f"{marcador} {corpo}"
    elif corpo is None:
        corpo = _SEM_TEXTO.get(linha.content_type, _SEM_TEXTO_PADRAO)
    return f"[{linha.role}] {corpo}"
```

Tire IMAGEM e DOCUMENTO de `_SEM_TEXTO`, porque passaram para `_MARCADOR_DE_MIDIA`. Atualize o comentário de `_SEM_TEXTO`: ele diz que imagem e documento gravam `text_body` NULL "hoje", e isso deixa de ser verdade quando há legenda.

- [ ] **Step 5: Rodar e ver passar; procurar quem afirmava o marcador velho**

Procure com Grep em `tests/` os textos `imagem, sem descricao` e `documento, sem texto extraido`. Todo teste que os afirmava passa a afirmar o marcador novo. Não é regressão: é a D4.

Run: `./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q`
Expected: PASS.

- [ ] **Step 6: Gates e commit**

```bash
git add src/mobia/infra/crypto.py src/mobia/domain/messages/schemas.py src/mobia/domain/context/montagem.py tests/unit
git commit -m "feat(TEC-132): a legenda da midia vira texto, e o modelo e avisado de que nao enxerga a midia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: a porta de armazenamento, a política e a config

**Files:**
- Create: `src/mobia/domain/midia/__init__.py`, `src/mobia/domain/midia/armazem.py`, `src/mobia/domain/midia/politica.py`
- Modify: `src/mobia/app/config.py`, `pyproject.toml`, `.gitignore`
- Test: `tests/unit/test_politica_de_midia.py`, `tests/unit/test_armazem_de_midia.py`

**Interfaces:**
- Produces:
  - `class ArmazemDeMidia(Protocol)`: `async def guardar(self, chave: str, dados: bytes) -> None` e `async def ler(self, chave: str) -> bytes`.
  - `ArmazemLocal(diretorio: Path)` e `ArmazemS3(bucket: str, regiao: str, *, cliente: Callable[[], AbstractAsyncContextManager[Any]] | None = None)`.
  - `armazem_da_config(settings: Settings) -> ArmazemDeMidia`.
  - Em `politica.py`: `TIPOS_PERMITIDOS: frozenset[str]`, `tipo_permitido(mime: str) -> bool` (ignora parâmetros como `; codecs=`) e `chave_do_objeto(message_id: uuid.UUID) -> str`, que devolve `f"midias/{message_id}"`.
  - Settings:
    - `midia_armazem: Literal["local", "s3"] = "local"`
    - `midia_diretorio: str = ".midias"`
    - `midia_s3_bucket: str = ""`
    - `midia_s3_regiao: str = ""`
    - `midia_teto_bytes: int = 26_214_400`

- [ ] **Step 1: Testes que falham**

```python
# tests/unit/test_politica_de_midia.py
"""Allowlist e chave do objeto. TEC-132, D1 e D3."""

import uuid

import pytest

from mobia.domain.midia.politica import chave_do_objeto, tipo_permitido


@pytest.mark.parametrize(
    "mime",
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "IMAGE/JPEG",
        "image/jpeg; charset=binary",
    ],
)
def test_permitidos(mime: str) -> None:
    assert tipo_permitido(mime)


@pytest.mark.parametrize(
    "mime", ["image/gif", "application/zip", "application/x-msdownload", "text/html", ""]
)
def test_recusados(mime: str) -> None:
    assert not tipo_permitido(mime)


def test_a_chave_nao_leva_nada_alem_do_id() -> None:
    identificador = uuid.uuid4()
    assert chave_do_objeto(identificador) == f"midias/{identificador}"
```

```python
# tests/unit/test_armazem_de_midia.py
"""Os dois adaptadores da porta. TEC-132, D1."""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from mobia.domain.midia.armazem import ArmazemLocal, ArmazemS3


async def test_local_ida_e_volta(tmp_path) -> None:
    armazem = ArmazemLocal(tmp_path)
    await armazem.guardar("midias/abc", b"\x00\x01dados")
    assert await armazem.ler("midias/abc") == b"\x00\x01dados"
    assert (tmp_path / "midias" / "abc").exists()


async def test_local_recusa_chave_que_sai_do_diretorio(tmp_path) -> None:
    with pytest.raises(ValueError):
        await ArmazemLocal(tmp_path).guardar("../fora", b"x")


class _Corpo:
    def __init__(self, dados: bytes) -> None:
        self._dados = dados

    async def read(self) -> bytes:
        return self._dados


class _ClienteS3Falso:
    def __init__(self) -> None:
        self.objetos: dict[tuple[str, str], bytes] = {}

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: Any) -> dict:
        self.objetos[(Bucket, Key)] = Body
        return {}

    async def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": _Corpo(self.objetos[(Bucket, Key)])}


async def test_s3_ida_e_volta_contra_cliente_falso() -> None:
    falso = _ClienteS3Falso()

    @asynccontextmanager
    async def cliente():
        yield falso

    armazem = ArmazemS3("meu-bucket", "sa-east-1", cliente=cliente)
    await armazem.guardar("midias/abc", b"dados")
    assert falso.objetos[("meu-bucket", "midias/abc")] == b"dados"
    assert await armazem.ler("midias/abc") == b"dados"
```

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_politica_de_midia.py tests/unit/test_armazem_de_midia.py --tb=short`
Expected: FAIL na coleta (`ModuleNotFoundError`).

- [ ] **Step 2: A dependência**

Em `pyproject.toml`, acrescente `aioboto3` às dependências de runtime, com a mesma forma de restrição de versão das vizinhas, e instale: `./.venv/Scripts/python.exe -m pip install aioboto3`. Se o mypy reclamar de stubs, siga o padrão do `pyproject.toml` para bibliotecas sem tipos (`[[tool.mypy.overrides]]` com `ignore_missing_imports`). Não desligue a checagem do módulo inteiro.

- [ ] **Step 3: Implementar**

`politica.py`:

```python
"""O que a midia recebida pode ser, e onde ela mora. TEC-132, D1 e D3.

A allowlist e curta de proposito: o que ela aceita e o que o lead manda para
um corretor de imoveis -- foto de anuncio, PDF de proposta, planilha. Um
executavel ou um zip nao tem por que ser guardado, e guardar o que nao se sabe
o que e so aumenta o que ha para vazar.
"""

import uuid

TIPOS_PERMITIDOS: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


def tipo_permitido(mime: str) -> bool:
    # A Meta pode mandar parametros depois do tipo ("image/jpeg; codecs=...").
    return mime.split(";", 1)[0].strip().lower() in TIPOS_PERMITIDOS


def chave_do_objeto(message_id: uuid.UUID) -> str:
    """So o id: a chave aparece em log e em listagem de bucket (D1)."""
    return f"midias/{message_id}"
```

`armazem.py`:

```python
"""Onde o arquivo de midia mora. TEC-132, D1.

**O que chega aqui ja vem cifrado** (`encrypt_bytes`, AAD
`aad_de(message_id, "midia")`): a porta nao sabe cifrar e nao precisa. Um
bucket vazado, ou um diretorio copiado, entrega blobs que so a chave de
conteudo abre -- e a chave nao mora junto.
"""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, Protocol

from mobia.app.config import Settings


class ArmazemDeMidia(Protocol):
    async def guardar(self, chave: str, dados: bytes) -> None: ...

    async def ler(self, chave: str) -> bytes: ...


class ArmazemLocal:
    """Diretorio no disco. O padrao de desenvolvimento e dos testes."""

    def __init__(self, diretorio: Path) -> None:
        self._raiz = diretorio.resolve()

    def _caminho(self, chave: str) -> Path:
        caminho = (self._raiz / chave).resolve()
        # A chave vem do proprio codigo (`chave_do_objeto`), mas a porta nao
        # confia nisso: um `..` escaparia do diretorio.
        if not caminho.is_relative_to(self._raiz):
            raise ValueError("chave fora do diretorio do armazem")
        return caminho

    async def guardar(self, chave: str, dados: bytes) -> None:
        caminho = self._caminho(chave)

        def _gravar() -> None:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(dados)

        await asyncio.to_thread(_gravar)

    async def ler(self, chave: str) -> bytes:
        return await asyncio.to_thread(self._caminho(chave).read_bytes)


class ArmazemS3:
    """S3, para producao. O bucket e as credenciais sao da TEC-219."""

    def __init__(
        self,
        bucket: str,
        regiao: str,
        *,
        cliente: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        self._bucket = bucket
        self._regiao = regiao
        self._cliente = cliente or self._cliente_aioboto3

    def _cliente_aioboto3(self) -> AbstractAsyncContextManager[Any]:
        import aioboto3  # import tardio: so quem liga o S3 paga o import

        return aioboto3.Session().client("s3", region_name=self._regiao)

    async def guardar(self, chave: str, dados: bytes) -> None:
        async with self._cliente() as s3:
            await s3.put_object(Bucket=self._bucket, Key=chave, Body=dados)

    async def ler(self, chave: str) -> bytes:
        async with self._cliente() as s3:
            resposta = await s3.get_object(Bucket=self._bucket, Key=chave)
            dados: bytes = await resposta["Body"].read()
            return dados


def armazem_da_config(settings: Settings) -> ArmazemDeMidia:
    if settings.midia_armazem == "s3":
        return ArmazemS3(settings.midia_s3_bucket, settings.midia_s3_regiao)
    return ArmazemLocal(Path(settings.midia_diretorio))
```

Settings em `config.py`, perto de `whatsapp_api_base`, com o porquê em comentário no estilo do arquivo. Leia os vizinhos antes. Se o arquivo tiver validação de produção (procure `model_validator`), acrescente: com `midia_armazem == "s3"`, `midia_s3_bucket` não pode ser vazio. Teste unitário junto, no arquivo de testes de config que já existe (`tests/unit/test_config.py`), seguindo o padrão dos testes de validação de lá.

`.gitignore`: acrescente `.midias/`.

- [ ] **Step 4: Rodar, gates e commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q`
Expected: PASS.

```bash
git add src/mobia/domain/midia src/mobia/app/config.py pyproject.toml .gitignore tests/unit
git commit -m "feat(TEC-132): a midia tem onde morar, em disco ou no S3, e so aceita os tipos que um corretor recebe

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: a tabela `midias_recebidas` e o repositório

**Files:**
- Create: `src/mobia/domain/midia/models.py`, `src/mobia/domain/midia/repositorio.py`, `alembic/versions/0042_midias_recebidas.py`
- Modify: `tests/conftest.py` (`TABELAS`)
- Test: `tests/integration/test_midias_recebidas.py`

**Interfaces:**
- Produces:
  - Em `models.py`:
    - `class StatusDaMidia(StrEnum)`: PENDENTE, ARMAZENADA, RECUSADA, FALHOU.
    - `class MotivoDaMidia(StrEnum)`: TIPO_NAO_PERMITIDO = "tipo_nao_permitido", ACIMA_DO_TETO = "acima_do_teto", SHA256_DIVERGENTE = "sha256_divergente", RECUSADA_PELA_META = "recusada_pela_meta", TENTATIVAS_ESGOTADAS = "tentativas_esgotadas", EXPIRADA = "expirada".
    - `class MidiaRecebida(Base)`, com as colunas da D2.
  - Em `repositorio.py`:
    - `def linha_pendente(message_id: uuid.UUID, raw_payload: dict[str, Any], content_type: MessageContentType) -> dict[str, Any] | None` monta o `values` do INSERT a partir do envelope. Devolve None se o tipo não for mídia ou se o envelope não trouxer `id`.
    - `async def ler_midia(session, message_id) -> MidiaRecebida | None`.
    - `async def marcar(session_factory, message_id, *, status: StatusDaMidia, motivo: MotivoDaMidia | None = None, chave: str | None = None, tamanho: int | None = None) -> None`.
    - `async def pendentes_para_reenfileirar(session_factory, *, mais_velhas_que: timedelta, mais_novas_que: timedelta, limite: int) -> list[uuid.UUID]`.
    - `async def expirar_pendentes(session_factory, *, mais_velhas_que: timedelta) -> int`.

- [ ] **Step 1: Testes que falham**

```python
"""A linha de midia e o seu ciclo de status. TEC-132, D2."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.midia.models import MidiaRecebida, MotivoDaMidia, StatusDaMidia
from mobia.domain.midia.repositorio import (
    expirar_pendentes,
    linha_pendente,
    marcar,
    pendentes_para_reenfileirar,
)
from mobia.infra.db import get_sessionmaker

ENVELOPE_IMAGEM = {"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg", "sha256": "ab" * 32}}


def test_linha_pendente_de_imagem() -> None:
    identificador = uuid.uuid4()
    linha = linha_pendente(identificador, ENVELOPE_IMAGEM, MessageContentType.IMAGEM)
    assert linha == {
        "message_id": identificador,
        "media_id_da_meta": "m1",
        "mime_type": "image/jpeg",
        "sha256": "ab" * 32,
        "status": StatusDaMidia.PENDENTE,
    }


def test_linha_pendente_de_documento() -> None:
    envelope = {"type": "document", "document": {"id": "d1", "mime_type": "application/pdf", "filename": "rg.pdf"}}
    linha = linha_pendente(uuid.uuid4(), envelope, MessageContentType.DOCUMENTO)
    assert linha is not None
    # O nome do arquivo NAO vira coluna (D2): fica cifrado no raw_payload.
    assert "filename" not in linha and linha["sha256"] is None


def test_texto_e_audio_nao_geram_linha() -> None:
    assert linha_pendente(uuid.uuid4(), {"type": "text"}, MessageContentType.TEXTO) is None
    assert linha_pendente(uuid.uuid4(), {"type": "audio", "audio": {"id": "a"}}, MessageContentType.AUDIO) is None


def test_envelope_sem_id_nao_gera_linha() -> None:
    assert linha_pendente(uuid.uuid4(), {"type": "image", "image": {}}, MessageContentType.IMAGEM) is None
```

Os testes de integração (`marcar`, `pendentes_para_reenfileirar` e `expirar_pendentes`) precisam de uma `Message` real por causa da FK. Crie-a como `tests/integration/test_vinculos_de_sessao.py` faz (a TEC-129 deixou o padrão das colunas NOT NULL). Escreva:

- `test_marcar_armazenada_grava_chave_e_tamanho`
- `test_pendente_antiga_e_reenfileiravel_e_nova_nao`: ajuste `criado_em` com `update(...)` para 20 minutos atrás e para 1 minuto atrás; com `mais_velhas_que=10min` e `mais_novas_que=7d`, só a de 20 minutos volta.
- `test_pendente_de_oito_dias_expira`: ela vira FALHOU com `EXPIRADA` e não volta em `pendentes_para_reenfileirar`.
- `test_armazenada_nunca_e_reenfileirada`.

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_midias_recebidas.py --tb=short`
Expected: FAIL na coleta.

- [ ] **Step 2: Modelo, migration e repositório**

Modelo: siga o formato de `src/mobia/domain/identidade/models.py` (TEC-129), com FK `messages.id` `ON DELETE CASCADE` e a docstring explicando os porquês da D2: tabela à parte, nome de arquivo fora, CASCADE porque a mídia é da mensagem. `status` e `motivo` são `String(16)` e `String(32)` sem CHECK. Leia `alembic/versions/0037_check_no_vocabulario_de_messages.py` antes de decidir. Se o repo usar CHECK para vocabulário novo, faça igual, com o CHECK no modelo e na migration, como a 0037.

Migration `0042_midias_recebidas.py`, `down_revision = "0041"`, com `downgrade` que desfaz tudo. Índice parcial para a varredura: `CREATE INDEX ix_midias_recebidas_pendentes ON midias_recebidas (criado_em) WHERE status = 'PENDENTE'`, que é o único caminho de leitura por status.

`linha_pendente`:

```python
_CHAVE_DO_ENVELOPE = {MessageContentType.IMAGEM: "image", MessageContentType.DOCUMENTO: "document"}


def linha_pendente(
    message_id: uuid.UUID, raw_payload: dict[str, Any], content_type: MessageContentType
) -> dict[str, Any] | None:
    chave = _CHAVE_DO_ENVELOPE.get(content_type)
    if chave is None:
        return None
    midia = raw_payload.get(chave) or {}
    media_id = midia.get("id")
    if not media_id:
        # Envelope sem id nao tem o que baixar. A mensagem existe e o turno
        # confirma do mesmo jeito; so nao ha ponteiro a guardar.
        return None
    return {
        "message_id": message_id,
        "media_id_da_meta": str(media_id),
        "mime_type": str(midia.get("mime_type") or ""),
        "sha256": midia.get("sha256"),
        "status": StatusDaMidia.PENDENTE,
    }
```

`marcar` faz UPDATE com `atualizado_em=now()`. `pendentes_para_reenfileirar` e `expirar_pendentes` filtram `status == PENDENTE` e a faixa de `criado_em`.

`TABELAS` em `tests/conftest.py`: acrescente `"midias_recebidas"` com o comentário do porquê, no estilo dos vizinhos.

- [ ] **Step 3: Migrar, rodar, gates e commit**

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/integration/test_midias_recebidas.py tests/integration/test_migrations.py --tb=short
```
Expected: PASS. Um `[WinError 64]` isolado no setup é ruído desta máquina (CLAUDE.md): rode de novo antes de concluir qualquer coisa.

```bash
git add src/mobia/domain/midia alembic/versions/0042_midias_recebidas.py tests/conftest.py tests/integration/test_midias_recebidas.py
git commit -m "feat(TEC-132): a midia recebida tem linha propria, com o ponteiro e o estado do download

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: a ingestão grava a mídia pendente e enfileira o download

**Files:**
- Modify: `src/mobia/domain/messages/service.py` (`_persist`, `ingest`), `src/mobia/infra/queue.py`
- Test: `tests/integration/test_ingestao_de_midia.py`

**Interfaces:**
- Consumes: `linha_pendente`, `MidiaRecebida` (Task 3).
- Produces: `BAIXAR_MIDIA_JOB = "baixar_midia"` e `async def enqueue_baixar_midia(pool: ArqRedis, message_id: uuid.UUID) -> bool`, com `_job_id=f"midia:{message_id}"`, em `infra/queue.py`.

- [ ] **Step 1: Testes que falham**

Use o `IngestionService` real com o `redis_pool` dos testes, como faz `tests/integration/test_ingestion_service.py`. Leia esse arquivo antes e copie o padrão de envelope e de fixture.

- `test_imagem_gera_midia_pendente_e_job`: depois do `ingest`, existe uma linha PENDENTE com `media_id_da_meta`, e `await redis_pool.zscore("arq:queue", f"midia:{message_id}")` não é None.
- `test_texto_nao_gera_midia_nem_job`.
- `test_reentrega_nao_cria_segunda_midia`: o mesmo envelope duas vezes deixa uma mensagem, uma linha de mídia e um job.
- `test_documento_gera_midia_pendente`.
- `test_falha_no_enqueue_da_midia_nao_derruba_a_ingestao`: com `monkeypatch` em `enqueue_baixar_midia` levantando `RuntimeError`, o `ingest` devolve o id, o `process_message` foi enfileirado e a mídia ficou PENDENTE (a varredura da Task 5 a recupera).

- [ ] **Step 2: Implementar**

`infra/queue.py`, seguindo `enqueue_process_message`:

```python
BAIXAR_MIDIA_JOB = "baixar_midia"


async def enqueue_baixar_midia(pool: ArqRedis, message_id: uuid.UUID) -> bool:
    """Enfileira o download da midia de uma mensagem. TEC-132, D3.

    Mesmo `_job_id` estavel do `process_message`, pela mesma razao: a varredura
    de pendentes re-enfileira sem multiplicar trabalho enquanto o job estiver
    na fila. E `baixar_midia` e registrado com `keep_result=0` em
    `workers/main.py` pelo mesmo motivo do irmao.
    """
    job = await pool.enqueue_job(BAIXAR_MIDIA_JOB, str(message_id), _job_id=f"midia:{message_id}")
    return job is not None
```

`_persist`: depois do INSERT de `messages` e **na mesma sessão, antes do `commit`**, monte as linhas com `linha_pendente` só para os ids inseridos. Case pelo `provider_message_id` do `RETURNING`, como o código já faz para o texto. Grave-as com `pg_insert(MidiaRecebida).values(...).on_conflict_do_nothing()`. Na mesma transação, porque uma mensagem de mídia sem linha de mídia seria uma mídia que nenhuma varredura encontra.

`_persist` passa a devolver também quais ids são de mídia, por exemplo mudando o retorno para uma tupla de três. Leia quem consome o retorno, que é só `ingest`, e ajuste o mínimo.

`ingest`: depois do `_try_enqueue` de cada mensagem, se ela tem mídia, chame um `_try_enqueue_midia(message_id)` que engole e loga falha (`midia.enqueue_failed`, só com `message_id` e `reason`), no mesmo espírito do `_try_enqueue`. Falha no enqueue da mídia nunca pode impedir o `process_message`.

- [ ] **Step 3: Rodar, gates e commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_ingestao_de_midia.py tests/integration/test_ingestion_service.py --tb=short`
Expected: PASS.

```bash
git commit -am "feat(TEC-132): a ingestao grava a midia pendente junto da mensagem e enfileira o download"
```

(com os arquivos novos adicionados e a linha `Co-Authored-By` no corpo.)

---

### Task 5: o job `baixar_midia`, o cliente da Graph API e a varredura

**Files:**
- Create: `src/mobia/domain/midia/graph.py`, `src/mobia/workers/jobs/baixar_midia.py`, `src/mobia/workers/jobs/sweep_midias_pendentes.py`
- Modify: `src/mobia/workers/main.py`
- Test: `tests/integration/test_baixar_midia.py`, `tests/integration/test_sweep_midias_pendentes.py`

**Interfaces:**
- Consumes: `ArmazemDeMidia`, `armazem_da_config`, `chave_do_objeto`, `tipo_permitido` (Task 2); `ler_midia`, `marcar`, `pendentes_para_reenfileirar`, `expirar_pendentes` (Task 3); `enqueue_baixar_midia` (Task 4); `encrypt_bytes`, `aad_de` (Task 1).
- Produces:
  - `graph.py`:
    - `class MidiaDaMeta(NamedTuple)`: `url: str`, `mime_type: str`, `tamanho: int | None`.
    - `async def resolver(media_id: str, *, cliente: httpx.AsyncClient) -> MidiaDaMeta`.
    - `async def baixar(url: str, *, teto: int, cliente: httpx.AsyncClient) -> bytes`.
    - As exceções `MidiaIndisponivel` (retentável: 5xx, rede), `MidiaRecusada` (4xx) e `MidiaAcimaDoTeto`.
  - `async def baixar_midia(ctx: dict[str, Any], message_id: str) -> str`, que devolve o status final gravado ou `"retentar"`.
  - `async def sweep_midias_pendentes(ctx: dict[str, Any], limite: int = 100) -> int`.

- [ ] **Step 1: Testes do job, que falham**

O cliente é injetável: o job lê `ctx.get("cliente_http_da_meta")` e, sem ele, abre um `httpx.AsyncClient` próprio. Nos testes, passe um `httpx.AsyncClient(transport=httpx.MockTransport(handler))` e `ctx["armazem"] = ArmazemLocal(tmp_path)`. O `handler` responde:
- `GET .../{media_id}` com `{"url": "https://lookaside.fbsbx.com/x", "mime_type": ..., "file_size": ...}`;
- `GET https://lookaside.fbsbx.com/x` com os bytes.

Casos:
- `test_sucesso_armazena_cifrado`: status ARMAZENADA, `chave_no_armazem == f"midias/{id}"`, `bytes == len(dados)`. O arquivo em disco é **diferente** dos dados e `decrypt_bytes(arquivo, aad_de(id, "midia")) == dados`. Os dois `GET` levam `Authorization: Bearer <token>`: afirme isso no `handler`.
- `test_tipo_fora_da_allowlist_recusa_sem_baixar`: o `mime_type` da resolução é `application/zip`, o status fica RECUSADA com `TIPO_NAO_PERMITIDO`, e o segundo `GET` nunca é chamado.
- `test_file_size_acima_do_teto_recusa_sem_baixar`.
- `test_estouro_do_teto_no_streaming_recusa`: `file_size` diz 10 bytes, o corpo tem teto+1, o status fica RECUSADA com `ACIMA_DO_TETO`, e nada é gravado no armazém.
- `test_sha256_divergente_falha`.
- `test_4xx_marca_falhou_sem_retentar`: status FALHOU com `RECUSADA_PELA_META`, e o job devolve `"falhou"` sem levantar.
- `test_5xx_pede_retry`: com `ctx["job_try"] = 1`, levanta `arq.Retry`; com `ctx["job_try"] = 5` (a última), grava FALHOU com `TENTATIVAS_ESGOTADAS` e não levanta.
- `test_midia_ja_armazenada_nao_baixa_de_novo`: idempotente para o re-enqueue da varredura.
- `test_mensagem_sem_linha_de_midia_nao_faz_nada`.
- `test_log_nao_leva_a_url`: com `structlog.testing.capture_logs()`, nenhum evento contém `lookaside`.

- [ ] **Step 2: Implementar `graph.py`**

```python
"""Buscar na Graph API a midia que o lead mandou. TEC-132, D3.

Dois passos, porque e assim que a Meta entrega: o `media_id` do envelope se
resolve numa URL temporaria, e a URL exige o MESMO bearer para baixar. **A URL
nunca vai para log**: ela e credencial de curta duracao.
"""
```

- `resolver`: `GET {settings.whatsapp_api_base}/{media_id}` com `Authorization: Bearer {settings.whatsapp_access_token}`.
- `baixar`: `async with cliente.stream("GET", url, headers=...)`. Acumula `aiter_bytes()` e levanta `MidiaAcimaDoTeto` assim que o total passar de `teto`.
- Mapeamento de erros:
  - `httpx.TransportError` e status >= 500 levantam `MidiaIndisponivel`;
  - 400 a 499 levanta `MidiaRecusada`;
  - use `settings.whatsapp_api_base` e o token; o timeout segue `TIMEOUT_SEGUNDOS` de `domain/outbound/whatsapp.py`, importado ou copiado com o porquê.

- [ ] **Step 3: Implementar o job**

```python
MAXIMO_DE_TENTATIVAS = 5  # o mesmo `max_tries` do registro em workers/main.py


async def baixar_midia(ctx: dict[str, Any], message_id: str) -> str:
    identificador = uuid.UUID(message_id)
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    async with session_factory() as sessao:
        midia = await ler_midia(sessao, identificador)
    if midia is None or midia.status != StatusDaMidia.PENDENTE:
        return "nada_a_fazer"
    ...
```

A sequência é a da D3:
1. Resolver.
2. Conferir o tipo na allowlist (o tipo da resolução, que é o que a Meta diz do arquivo) e o `tamanho` contra o teto.
3. Baixar em streaming.
4. Conferir o `sha256` (`hashlib.sha256(dados).hexdigest()`), só quando o envelope trouxe um.
5. `encrypt_bytes(dados, aad_de(identificador, "midia"))`.
6. `armazem.guardar(chave_do_objeto(identificador), blob)`.
7. `marcar(ARMAZENADA, chave=..., tamanho=len(dados))`.

Na falha:
- `MidiaIndisponivel` com `ctx.get("job_try", 1) < MAXIMO_DE_TENTATIVAS` levanta `Retry(defer=30 * job_try)`;
- `MidiaIndisponivel` na última tentativa grava FALHOU com `TENTATIVAS_ESGOTADAS`;
- `MidiaRecusada` grava FALHOU com `RECUSADA_PELA_META`;
- `MidiaAcimaDoTeto` grava RECUSADA com `ACIMA_DO_TETO`.

Cada desfecho loga `midia.<status>`, com `message_id` e `motivo`.

**Falha do `armazem.guardar`** (disco cheio, S3 fora) é tratada como `MidiaIndisponivel`: retenta. Escreva um teste para isso também (`test_falha_do_armazem_retenta`), com um armazém que levanta.

- [ ] **Step 4: A varredura**

`sweep_midias_pendentes`:
1. `expirar_pendentes(mais_velhas_que=7 dias)`;
2. `pendentes_para_reenfileirar(mais_velhas_que=10 min, mais_novas_que=7 dias, limite)`;
3. `enqueue_baixar_midia` para cada uma, logando a falha por linha sem abortar as outras, como faz a `sweep_stalled`.

Devolve quantas re-enfileirou. Os dois prazos são constantes nomeadas no módulo, com o porquê: 10 minutos é bem acima do job normal; 7 dias fica abaixo da retenção da mídia na Meta.

Testes (`tests/integration/test_sweep_midias_pendentes.py`):
- re-enfileira só a PENDENTE antiga, confirmando com `zscore` no `redis_pool`;
- expira a de 8 dias;
- falha no enqueue de uma não impede as outras.

- [ ] **Step 5: Registrar no worker**

Em `workers/main.py`:
- no `startup`: `ctx["armazem"] = armazem_da_config(settings)`;
- em `functions`: `func(baixar_midia, keep_result=0, max_tries=MAXIMO_DE_TENTATIVAS)` e `func(sweep_midias_pendentes, keep_result=0)`;
- em `cron_jobs`: `cron(sweep_midias_pendentes, minute={0, 5, ..., 55}, run_at_startup=False)`.

Cada um leva comentário no estilo dos vizinhos: por que `keep_result=0` e por que de 5 em 5 minutos (o prazo é de 10 minutos, e segundos de precisão não compram nada). Confira se há um teste que enumera `functions` ou `cron_jobs` (Grep por `WorkerSettings` em `tests/`) e atualize-o.

- [ ] **Step 6: Rodar, gates e commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_baixar_midia.py tests/integration/test_sweep_midias_pendentes.py tests/unit --tb=short -q`
Expected: PASS.

Commit: `feat(TEC-132): o download da midia resolve, confere e guarda cifrado, com retentativa e varredura propria`.

---

### Task 6: a resposta fixa no turno

**Files:**
- Create: `src/mobia/domain/midia/confirmacao.py`
- Modify: `src/mobia/domain/messages/rajada.py` (`ha_fala_pendente_antes`), `src/mobia/domain/agente/turno.py`
- Test: `tests/integration/test_turno_midia.py`, e acrescentar em `tests/integration/test_rajada.py` (confira o nome real do arquivo que testa `ha_fala_pendente_antes`)

**Interfaces:**
- Produces:
  - Em `confirmacao.py`:
    - `TEXTO_DA_CONFIRMACAO_DE_IMAGEM` e `TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO` (Global Constraints);
    - `KIND_DA_CONFIRMACAO_DE_MIDIA = "confirmacao_de_midia"`;
    - `SUBAGENTE_MIDIA = "midia"`;
    - `CONFIRMACOES_DE_MIDIA: dict[str, str]`, que mapeia `content_type` para o texto.
  - `ha_fala_pendente_antes(..., com_texto: bool = False)`.

- [ ] **Step 1: `com_texto`**

Teste primeiro: uma rajada com uma imagem sem legenda pendente dá `False` com `com_texto=True` e `True` sem ele; com um texto pendente, dá `True` nos dois. Depois, na consulta de `ha_fala_pendente_antes`, quando `com_texto` for verdadeiro, acrescente `Message.text_body.is_not(None)` às condições. Documente o parâmetro na docstring: por que a mídia do turno só responde fixo sem texto pendente (D4).

- [ ] **Step 2: Testes do turno, que falham**

Use os dublês de turno que os testes de integração do turno já usam. Um bom modelo é `tests/integration/test_turno_optout.py`, com o classificador falso que conta `chamadas` e um outbound que registra os envios. Crie a mensagem de mídia gravando direto uma `Message` IMAGEM com `text_body` nulo, como aqueles testes gravam as deles.

- `test_imagem_sem_legenda_recebe_texto_fixo_sem_chamar_o_modelo`: o texto enviado é `TEXTO_DA_CONFIRMACAO_DE_IMAGEM`, eventualmente prefixado pela identificação no primeiro contato (afirme com `endswith` ou compare com a identificação montada como o próprio turno monta). O kind é `confirmacao_de_midia`, e `classificador.chamadas == 0`.
- `test_documento_sem_legenda_recebe_o_texto_de_documento`.
- `test_optout_nao_recebe_confirmacao_de_midia`: com um `OptoutEvent` do par, nada é enviado.
- `test_rajada_com_texto_roda_o_turno_normal`: uma `Message` TEXTO do lead mais antiga, pendente, depois a IMAGEM; o turno da IMAGEM chama o classificador (`chamadas == 1`) e não envia o texto fixo.
- `test_imagem_com_legenda_roda_o_turno_normal`.
- `test_atendimento_humano_silencia_a_confirmacao`.

- [ ] **Step 3: Implementar**

`confirmacao.py`, com docstring dizendo por que a confirmação é fixa: garantia total de não afirmar nada sobre o conteúdo, e zero token. Os textos das Global Constraints entram **verbatim**.

Em `turno.py`, imediatamente antes do `if corpo:` que abre a moderação de entrada (~l.1553):

```python
    # TEC-132, D4. Midia sem nenhum texto do lead na rajada: resposta fixa,
    # sem modelo. Aqui, e nao antes, porque as guardas de opt-out, atendimento
    # humano e conversa encerrada ja rodaram -- quem pediu silencio nao recebe
    # "recebi sua imagem". E antes da moderacao e do classificador porque nao
    # ha texto a moderar nem o que perguntar ao modelo: um texto fixo e a unica
    # forma de GARANTIR que nada se afirma sobre o conteudo.
    #
    # "Na rajada" e nao "nesta mensagem": com "quero esse" + foto o debounce
    # roda o turno na foto, e responder fixo ali deixaria o "quero esse" sem
    # resposta. Havendo texto pendente, o turno segue normal e o modelo ve a
    # midia marcada (`_MARCADOR_DE_MIDIA`, em `context/montagem.py`).
    confirmacao = CONFIRMACOES_DE_MIDIA.get(message.content_type)
    if confirmacao is not None and corpo is None:
        async with session_factory() as sessao_da_rajada:
            ha_texto_pendente = await ha_fala_pendente_antes(
                sessao_da_rajada, message, com_texto=True
            )
        if not ha_texto_pendente:
            return await _entregar_texto_fixo(
                session_factory,
                message=message,
                outbound=outbound,
                recorder_texto=confirmacao,
                kind=KIND_DA_CONFIRMACAO_DE_MIDIA,
                subagent=SUBAGENTE_MIDIA,
            )
```

**Antes de usar `SUBAGENTE_MIDIA`**, confira com Grep onde o `subagent` é gravado (telemetria, recorder) e se existe CHECK ou Literal sobre o vocabulário. Se existir, acrescente `"midia"` a ele, com migration se o CHECK for de banco. Se isso for desproporcional, use o rótulo existente mais próximo e registre no relatório.

Atualize a docstring de `_entregar_texto_fixo`, que enumera os chamadores e os kinds deles, porque passa a ter mais um. É "comentário não mente".

- [ ] **Step 4: Rodar, gates e commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_midia.py tests/integration/test_turno_optout.py tests/integration/test_moderacao_na_rajada.py --tb=short
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```
Expected: PASS, e a margem igual à de antes.

Commit: `feat(TEC-132): a midia sem texto recebe confirmacao fixa, sem modelo, e a rajada com texto segue o turno normal`.

---

### Task 7: cenários da card, SRS, comentários e suíte

**Files:**
- Test: `tests/features/test_recebimento_de_midia.py`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (abaixo da RN-01.4, ~l.131)

- [ ] **Step 1: Os três cenários, ponta a ponta**

O caminho inteiro:
1. O envelope da Meta entra pela rota do webhook (veja `tests/features/test_recepcao_de_mensagem.py` para montar o POST assinado).
2. `process_message` roda com os dublês.
3. `baixar_midia` roda com `MockTransport` e `ArmazemLocal(tmp_path)`.

Os três cenários:
- *Reconhecer imagem recebida sem interpretá-la*: a linha é IMAGEM; `midias_recebidas` fica ARMAZENADA depois do job; o texto enviado é o fixo de imagem; o classificador não foi chamado.
- *Pedir por texto a informação que a mídia traria*: imagem sem texto recebe um texto que pergunta ("Me conta em texto").
- *Documento recebido segue a mesma regra*: PDF, DOCUMENTO, ARMAZENADA, texto fixo de documento.

Mais um, da Review Focus 5: a confirmação sai mesmo quando o download depois falha com 404; a linha fica FALHOU e a mensagem fica PROCESSED.

- [ ] **Step 2: Emenda ao SRS**

Logo abaixo da linha da RN-01.4:

```markdown
  - **Emenda E-01 (TEC-132, 24/09/2026):** a mídia é guardada fora do banco, cifrada pela aplicação antes de sair do processo (AES-GCM, a mesma chave de conteúdo), com o ponteiro numa tabela ligada à mensagem. Só imagem e documento são guardados, e só nos tipos que um corretor recebe (JPEG, PNG, WebP, PDF, Word, Excel), até 25 MB. A legenda que acompanha a mídia é tratada como texto do lead. Sem nenhum texto do lead na rajada, a confirmação é uma mensagem fixa, sem o modelo, e é essa a garantia de "não interpretar": com legenda, o turno segue normal e o modelo é avisado de que não vê a mídia, o que torna a garantia probabilística. O download é assíncrono, e a confirmação não depende dele. A retenção da RNF-22 ainda não se aplica à mídia, porque não há job de retenção.
```

- [ ] **Step 3: Comentários e gates**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada ALTERADO e VIZINHO. Em especial:
- o comentário de `_SEM_TEXTO` (Task 1);
- a docstring de `_entregar_texto_fixo` (Task 6);
- o comentário de `domain/messages/canais.py`, que cita a TEC-132 como possível fonte de canal novo. Ela não traz canal, então corrija.

Depois, os três gates e o gate novo da TEC-299: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py origin/main --checar`.

- [ ] **Step 4: Suíte**

Por blocos, com o Postgres reiniciado entre eles (CLAUDE.md, "Quando o `-n 8` derruba o Postgres"). Guarde o hash e as contagens.

- [ ] **Step 5: Commit**

`docs(TEC-132): a RN-01.4 ganha a E-01, e os comentarios que citavam midia sem texto passam a dizer o que e verdade`.

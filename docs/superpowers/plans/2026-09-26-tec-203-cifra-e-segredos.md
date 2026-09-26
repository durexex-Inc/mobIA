# TEC-203 — Cifra do telefone do lead e proteção de segredos: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cifrar o telefone do lead com blind index, abrir rotação de chave, exigir TLS em produção, ler segredos só de ambiente/arquivo montado e bloquear segredo commitado com gitleaks.

**Architecture:** o `conversation_key` de 20 tabelas passa a guardar `HMAC(LEAD_INDICE_CHAVE, "channel:valor_cru")`; o valor cru vive cifrado em `identidades_de_lead` e só é revelado nas bordas que precisam dele (envio WhatsApp, CRM, e-mail de agendamento, dashboard). A chave de conteúdo vira keyring com blob v2 (`versão ‖ id ‖ nonce ‖ ct ‖ tag`). A migration `0061` e o script de rotação usam o mesmo núcleo de reindexação.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.1 async, Alembic, ARQ 0.28, pydantic-settings 2.15, `cryptography` (AESGCM), GitHub Actions, gitleaks.

**Spec:** `docs/superpowers/specs/2026-09-26-tec-203-cifra-e-segredos-design.md` — leia antes de qualquer task.

## Global Constraints

- Gates antes de todo commit, nesta ordem: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy` (sem argumento).
- Comentários e docstrings em `src/` e `tests/`: português **sem acento**; texto que o corretor/lead recebe: **com acento**; prosa em `docs/`: com acento.
- Comentário explica o porquê; comentário que o código desmente é defeito.
- Citação de código em `.md` por âncora `arquivo.py::Nome`, **nunca** por número de linha em linha nova; `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar` antes do PR.
- Commits: `tipo(TEC-203): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Migration nova: `0061`, `down_revision = "0060"`. Listas copiadas na migration são **literais** (migration aplicada não muda quando o código muda).
- Nada muda fora de produção em TLS: compose local sem TLS.
- Unitários sem Docker: `./.venv/Scripts/python.exe -m pytest tests/unit`. Integração exige `docker compose up -d`.
- Suíte inteira UMA vez no fim (Task 11), por blocos se o `-n 8` derrubar o Postgres (ver `CLAUDE.md`).

## Review Focus

1. **`wa_id` sem o nono dígito** (`554899990000`): o envio vai para o mesmo `wa_id` cru que chegou, e a busca do dashboard pelo número com o 9 (`48 99999-0000`) acha o lead. → testes na Task 8.
2. **Identidade ausente no envio**: `WhatsAppOutbound` não faz POST nenhum e levanta `EnvioRecusado`. → teste na Task 8.
3. **Resumo gravado antes da migration** continua legível depois dela (o AAD depende da chave e é recifrado). → teste na Task 6.
4. **Reindexação rodada duas vezes, ou retomada depois de interrompida**, dá o mesmo banco. → teste na Task 6.
5. **Evento de auditoria antigo** continua achável pelo lead depois da migration (`lead_ref` recalculado), e a trigger de imutabilidade volta ligada. → teste na Task 6.

---

## Mapa de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `.gitleaks.toml` (novo) | regras + allowlist por valor exato | 1 |
| `.github/workflows/ci.yml` | job `segredos` | 1 |
| `src/mobia/app/config.py` | `.env` fora de produção, `secrets_dir`, keyring, chave de índice, guardas | 2, 4, 5 |
| `src/mobia/infra/tls.py` (novo) | `SSLContext` TLS 1.3 e checagem de DSN | 3 |
| `src/mobia/infra/db.py`, `alembic/env.py`, `src/mobia/infra/queue.py` | TLS em produção | 3 |
| `src/mobia/infra/crypto.py` | keyring, blob v2 | 4 |
| `src/mobia/domain/identidade/indice.py` (novo) | `chave_de`, `indice_de_telefone`, `registrar`, `revelar`, `telefones_de` | 5, 6 |
| `src/mobia/infra/rotacao.py` (novo) | aviso dos 90 dias | 5 |
| `src/mobia/domain/identidade/models.py` | `IdentidadeDeLead`; `VinculoDeSessao` cifrado | 6 |
| `src/mobia/domain/identidade/reindexacao.py` (novo) | núcleo da reindexação (sync, sobre `Connection`) | 6 |
| `alembic/versions/0061_identidade_do_lead_cifrada.py` (novo) | tabela, backfill, vínculos | 6 |
| `scripts/reindexar_leads.py` (novo) | rotação da chave de índice / do `lead_ref` | 6 |
| `src/mobia/domain/messages/service.py`, `api/routes/widget.py`, `identidade/repositorio.py` | entrada | 7 |
| `outbound/whatsapp.py`, `crm/payload.py`, `workers/jobs/exportar_crm.py`, `agendamento/mensagens.py`, `confirmacao.py`, `cancelamento.py`, `leads/repositorio.py`, `identidade/absorcao.py`, `admin/reativar.py` | bordas | 8 |
| `src/mobia/admin/recifrar.py` + `scripts/recifrar.py` (novos) | recifra para aposentar chave | 9 |
| `docs/seguranca/segredos.md` (novo), SRS, docstrings | runbook e emendas | 11 |

---

### Task 1: gitleaks bloqueante no CI

**Files:**
- Create: `.gitleaks.toml`
- Modify: `.github/workflows/ci.yml` (job novo `segredos`, depois de `qualidade`)

**Interfaces:** nenhuma com código Python.

- [ ] **Step 1: Instalar o gitleaks localmente e escolher a versão**

```bash
gh release view --repo gitleaks/gitleaks --json tagName -q .tagName
```
Anote a tag (ex.: `v8.28.0`). Baixe `gitleaks_<versao>_windows_x64.zip` para o scratchpad e o `gitleaks_<versao>_checksums.txt`; guarde a linha `linux_x64.tar.gz` do checksum — é ela que vai no CI.

- [ ] **Step 2: Varrer o histórico inteiro ANTES de escrever a allowlist**

```bash
<scratchpad>/gitleaks.exe git --redact --report-format json --report-path <scratchpad>/historico.json .
```
Para cada achado, classifique: (a) default de desenvolvimento commitado de propósito (`CHAVE_DE_DESENVOLVIMENTO`, `SEGREDO_DE_JWT_DE_DESENVOLVIMENTO`, `CHAVE_DO_LEAD_DE_DESENVOLVIMENTO`, `TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO`, `dev-app-secret`, `dev-verify-token`, a sentinela `tec302-sentinela-do-token-nao-vaza`, valores de `.env.example`); (b) chave falsa de teste; (c) **qualquer outra coisa**.

**Se houver achado do tipo (c): PARE a task e reporte ao Eduardo** com arquivo, commit e regra (sem o valor). Rotacionar e reescrever histórico é decisão dele.

- [ ] **Step 3: Escrever `.gitleaks.toml`**

```toml
# TEC-203, RNF-14. Estende as regras padrao; a allowlist e por VALOR exato,
# nunca por arquivo: um segredo real colado no config.py continua sendo pego.
# Cada valor abaixo e default de desenvolvimento commitado de proposito e
# recusado em producao por um validator de `Settings`.
title = "mobIA"

[extend]
useDefault = true

[allowlist]
description = "defaults de desenvolvimento, recusados em producao"
regexTarget = "match"
regexes = [
  '''ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE=''',
  '''dev-jwt-secret-nao-use-em-producao''',
  '''dev-auditoria-chave-do-lead-nao-use-em-producao''',
  '''dev-indice-do-lead-nao-use-em-producao''',
  '''dev-catalogo-token''',
  '''tec302-sentinela-do-token-nao-vaza''',
]
```
Acrescente só os valores (a) e (b) do Step 2 que o gitleaks de fato acusou, cada um com comentário de uma linha dizendo de onde vem. `dev-indice-do-lead-nao-use-em-producao` entra agora porque a Task 5 o cria.

- [ ] **Step 4: Confirmar que o histórico passa com a allowlist**

Run: `<scratchpad>/gitleaks.exe git --config .gitleaks.toml --redact .`
Expected: `no leaks found`, exit 0.

- [ ] **Step 5: Confirmar que a allowlist não é larga demais**

```bash
t=$(mktemp -d); echo "token = \"ghp_$(head -c 400 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 36)\"" > "$t/plantado.py"
<scratchpad>/gitleaks.exe dir --config .gitleaks.toml "$t"; echo EXIT=$?
```
Expected: `leaks found: 1`, `EXIT=1`.

- [ ] **Step 6: Job no CI** — acrescente em `.github/workflows/ci.yml`, entre `qualidade` e `testes`:

```yaml
  segredos:
    name: Segredos
    runs-on: ubuntu-latest
    env:
      GITLEAKS_VERSAO: "<versao sem o v, ex.: 8.28.0>"
      GITLEAKS_SHA256: "<sha256 do linux_x64.tar.gz, do checksums.txt>"
    steps:
      # Historico inteiro: em PR o intervalo vai do merge-base ao HEAD; na
      # main, tudo. Um clone raso esconderia o commit que trouxe o segredo.
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      # Binario fixado por versao e checksum, e nao a gitleaks-action: a v2
      # dela exige licenca paga em repositorio de organizacao.
      - name: Instalar gitleaks
        run: |
          curl -sSfL -o gitleaks.tar.gz \
            "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSAO}/gitleaks_${GITLEAKS_VERSAO}_linux_x64.tar.gz"
          echo "${GITLEAKS_SHA256}  gitleaks.tar.gz" | sha256sum -c -
          tar -xzf gitleaks.tar.gz gitleaks
          sudo mv gitleaks /usr/local/bin/

      # Autoteste, no molde da sentinela do bundle (TEC-302): uma allowlist
      # larga demais deixaria o gate verde para sempre sem ninguem notar. O
      # token e gerado aqui para nao existir em arquivo versionado.
      - name: Autoteste do gitleaks
        run: |
          t=$(mktemp -d)
          echo "token = \"ghp_$(head -c 400 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 36)\"" > "$t/plantado.py"
          if gitleaks dir --config .gitleaks.toml --no-banner "$t"; then
            echo "::error::gitleaks nao acusou o token plantado -- a allowlist engoliu a regra"
            exit 1
          fi

      - name: Varrer os commits
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            gitleaks git --config .gitleaks.toml --redact --no-banner \
              --log-opts="origin/${{ github.base_ref }}..HEAD" .
          else
            gitleaks git --config .gitleaks.toml --redact --no-banner .
          fi
```

- [ ] **Step 7: Validar o YAML** — `./.venv/Scripts/python.exe -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"` (se `yaml` não estiver na venv, `pip install pyyaml` só localmente). Expected: sem erro.

- [ ] **Step 8: Commit**

```bash
git add .gitleaks.toml .github/workflows/ci.yml
git commit -m "ci(TEC-203): gitleaks bloqueia segredo commitado e se autotesta"
```

---

### Task 2: segredos só de ambiente ou arquivo montado em produção

**Files:**
- Modify: `src/mobia/app/config.py` (`get_settings`, validator novo)
- Test: `tests/unit/test_config_segredos.py` (novo)

**Interfaces:**
- Produces: `get_settings()` passa `_env_file=None` em produção e `_secrets_dir` de `MOBIA_SECRETS_DIR`. `ConfiguracaoInsegura` quando `ENVIRONMENT` de produção veio de arquivo.

- [ ] **Step 1: Testes que falham**

```python
"""TEC-203, D5: em producao o `.env` nao e lido, e segredo vem de env ou arquivo montado."""

import pytest

from mobia.app.config import ConfiguracaoInsegura, Settings, get_settings


@pytest.fixture
def em_diretorio_com_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for nome in ("ENVIRONMENT", "JWT_SEGREDO", "MOBIA_SECRETS_DIR"):
        monkeypatch.delenv(nome, raising=False)
    return tmp_path


def test_fora_de_producao_o_env_continua_valendo(em_diretorio_com_env):
    (em_diretorio_com_env / ".env").write_text("WHATSAPP_VERIFY_TOKEN=do-arquivo\n")
    assert get_settings().whatsapp_verify_token == "do-arquivo"


def test_em_producao_o_env_nao_e_lido(em_diretorio_com_env, monkeypatch, segredos_de_producao):
    (em_diretorio_com_env / ".env").write_text("WHATSAPP_VERIFY_TOKEN=do-arquivo\n")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert get_settings().whatsapp_verify_token != "do-arquivo"


def test_ambiente_de_producao_vindo_do_arquivo_reprova(em_diretorio_com_env):
    (em_diretorio_com_env / ".env").write_text("ENVIRONMENT=production\n")
    with pytest.raises(ConfiguracaoInsegura, match="ENVIRONMENT"):
        get_settings()


def test_segredo_de_arquivo_montado(em_diretorio_com_env, monkeypatch):
    montados = em_diretorio_com_env / "segredos"
    montados.mkdir()
    (montados / "whatsapp_verify_token").write_text("montado")
    monkeypatch.setenv("MOBIA_SECRETS_DIR", str(montados))
    assert get_settings().whatsapp_verify_token == "montado"
```

`segredos_de_producao` é uma fixture nova em `tests/unit/conftest.py` (crie se não existir; se existir, acrescente) que põe em `monkeypatch.setenv` valores válidos de produção para todo segredo que tem guarda — `CONTENT_ENCRYPTION_KEY` (base64 de 32 bytes aleatórios), `JWT_SEGREDO` (48 chars), `CATALOGO_ADMIN_TOKEN`, `AUDITORIA_CHAVE_DO_LEAD`, e o que mais a construção de `Settings` em produção exigir (leia os validators e o `workers/main.py`). As Tasks 3–5 acrescentam os seus a esta mesma fixture.

- [ ] **Step 2: Rodar e ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_config_segredos.py -v`. Expected: `test_em_producao_o_env_nao_e_lido`, `test_ambiente_de_producao_vindo_do_arquivo_reprova` e `test_segredo_de_arquivo_montado` falham.

- [ ] **Step 3: Implementar** em `config.py`:

```python
import os
```
Substitua `get_settings`:

```python
def get_settings() -> Settings:
    """Monta `Settings` com as fontes que o ambiente permite. TEC-203, D5.

    **Em producao o `.env` nao e lido.** Segredo em producao vem do secret
    manager da plataforma, que o entrega como variavel de ambiente ou arquivo
    montado; um `.env` no servidor e justamente o segredo em arquivo que a
    RNF-14 proibe. A decisao olha `os.environ` e nao `Settings`, porque e ela
    que decide se o arquivo entra -- ler o arquivo para descobrir se pode le-lo
    seria circular. Quem pusesse `ENVIRONMENT=production` so no `.env` escapa
    daqui; o validator `_recusar_producao_declarada_em_arquivo` o pega.

    `MOBIA_SECRETS_DIR` aponta o diretorio de arquivos montados (um arquivo por
    segredo, nome do campo em minusculas), no formato de Docker, K8s e ECS.
    """
    em_producao = os.environ.get("ENVIRONMENT", "").strip().lower() in _AMBIENTES_DE_PRODUCAO
    return Settings(
        _env_file=None if em_producao else ".env",
        _secrets_dir=os.environ.get("MOBIA_SECRETS_DIR") or None,
    )
```
E o validator, junto dos outros `_recusar_*`:

```python
    @model_validator(mode="after")
    def _recusar_producao_declarada_em_arquivo(self) -> "Settings":
        """`ENVIRONMENT` de producao tem de vir do ambiente, nao do `.env`.

        Sem isto, `ENVIRONMENT=production` escrito so no `.env` ligaria todas
        as guardas de producao -- e o `.env` teria sido lido, que e o que
        `get_settings` existe para impedir.
        """
        declarado = os.environ.get("ENVIRONMENT", "").strip().lower()
        if self.em_producao and declarado not in _AMBIENTES_DE_PRODUCAO:
            raise ConfiguracaoInsegura(
                f"ENVIRONMENT={self.environment} veio de arquivo, nao do ambiente. "
                "Em producao o ambiente e declarado pela plataforma, e o .env nao e lido."
            )
        return self
```
Atenção: testes existentes que constroem `Settings(environment="production", ...)` direto (sem env var) passam a reprovar com essa guarda. Rode `grep -rn 'environment="prod\|environment="production' tests` e, nesses testes, troque para `monkeypatch.setenv("ENVIRONMENT", "production")` + `Settings()`, ou acrescente `monkeypatch.setenv("ENVIRONMENT", <o mesmo valor>)` antes da construção. Não afrouxe a guarda.

- [ ] **Step 4: Rodar** — `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`. Expected: todos passam.

- [ ] **Step 5: `.env.example`** — acrescente, perto do topo, o comentário:
```
# Em producao este arquivo NAO e lido (TEC-203): segredos vem do ambiente ou
# de arquivos em MOBIA_SECRETS_DIR, entregues pelo secret manager da plataforma.
```

- [ ] **Step 6: Gates e commit**

```bash
git add src/mobia/app/config.py tests/unit .env.example
git commit -m "feat(TEC-203): em producao segredo vem do ambiente ou de arquivo montado, nunca do .env"
```

---

### Task 3: TLS 1.3 exigido em produção para Postgres e Redis

**Files:**
- Create: `src/mobia/infra/tls.py`
- Modify: `src/mobia/infra/db.py::get_engine`, `alembic/env.py`, `src/mobia/infra/queue.py::redis_settings`
- Test: `tests/unit/test_tls.py` (novo)

**Interfaces:**
- Produces: `contexto_tls() -> ssl.SSLContext`; `argumentos_de_conexao_do_banco(settings) -> dict[str, object]`; `exigir_redis_com_tls(dsn: str) -> None` (levanta `ConfiguracaoInsegura`).

- [ ] **Step 1: Testes que falham**

```python
"""TEC-203, D6: TLS 1.3 com verificacao de certificado em producao; nada muda fora dela."""

import ssl

import pytest

from mobia.app.config import ConfiguracaoInsegura, Settings
from mobia.infra.tls import argumentos_de_conexao_do_banco, contexto_tls, exigir_redis_com_tls


def test_contexto_exige_tls_13_e_verifica_certificado():
    contexto = contexto_tls()
    assert contexto.minimum_version == ssl.TLSVersion.TLSv1_3
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname is True


def test_fora_de_producao_o_banco_conecta_sem_tls():
    assert argumentos_de_conexao_do_banco(Settings()) == {}


def test_em_producao_o_banco_recebe_o_contexto(monkeypatch, segredos_de_producao):
    monkeypatch.setenv("ENVIRONMENT", "production")
    argumentos = argumentos_de_conexao_do_banco(Settings())
    assert isinstance(argumentos["ssl"], ssl.SSLContext)


def test_redis_sem_tls_reprova():
    with pytest.raises(ConfiguracaoInsegura, match="rediss://"):
        exigir_redis_com_tls("redis://cache:6379/0")


def test_redis_com_tls_passa():
    exigir_redis_com_tls("rediss://cache:6379/0")
```

- [ ] **Step 2: Ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_tls.py -v`. Expected: `ModuleNotFoundError: mobia.infra.tls`.

- [ ] **Step 3: `src/mobia/infra/tls.py`**

```python
"""TLS das conexoes que saem do processo para infraestrutura nossa. TEC-203, D6.

So producao. Fora dela o compose local nao tem TLS, e exigi-lo quebraria a
maquina de todo mundo por uma protecao que so faz sentido em rede alheia.

**O piso 1.3 vale para o Postgres e nao para o Redis.** O `RedisSettings` do
ARQ 0.28 nao expoe versao minima de TLS; ali se exige `rediss://` e
verificacao de certificado, e a divergencia esta registrada no spec. APIs de
terceiros ficam com o piso padrao do `ssl`, que negocia 1.3 quando o servidor
oferece -- forcar 1.3 num servidor que nao controlamos derrubaria a
integracao no dia em que ele oferecer so 1.2.
"""

import ssl

from mobia.app.config import ConfiguracaoInsegura, Settings


def contexto_tls() -> ssl.SSLContext:
    contexto = ssl.create_default_context()
    contexto.minimum_version = ssl.TLSVersion.TLSv1_3
    return contexto


def argumentos_de_conexao_do_banco(settings: Settings) -> dict[str, object]:
    """`connect_args` do engine: o contexto TLS em producao, nada fora dela."""
    if not settings.em_producao:
        return {}
    return {"ssl": contexto_tls()}


def exigir_redis_com_tls(dsn: str) -> None:
    if not dsn.startswith("rediss://"):
        raise ConfiguracaoInsegura(
            "REDIS_URL sem TLS em producao. Use rediss://; o Redis gerenciado do "
            "provedor oferece TLS, e sem ele fila e rate limit trafegam em claro."
        )
```

- [ ] **Step 4: Ligar nos três pontos**

`db.py::get_engine`:
```python
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args=argumentos_de_conexao_do_banco(settings),
        )
```
(import `from mobia.infra.tls import argumentos_de_conexao_do_banco`).

`alembic/env.py`, em `run_async_migrations`, passe o mesmo `connect_args` ao `async_engine_from_config`:
```python
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=argumentos_de_conexao_do_banco(get_settings()),
    )
```

`queue.py::redis_settings`:
```python
def redis_settings() -> RedisSettings:
    settings = get_settings()
    redis = RedisSettings.from_dsn(settings.redis_url)
    if settings.em_producao:
        exigir_redis_com_tls(settings.redis_url)
        # `from_dsn` liga `ssl` para rediss://; o que falta e exigir que o
        # certificado valha para o host. O default do ARQ nao verifica.
        redis.ssl_cert_reqs = "required"
        redis.ssl_check_hostname = True
    return redis
```

Confirme com `grep -rn "RedisSettings\|from_url(" src` que não há outro cliente Redis fora de `queue.py` (o levantamento achou só este). Se houver, aplique a mesma exigência.

- [ ] **Step 5: Rodar** — `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`. Expected: passa.

- [ ] **Step 6: Gates e commit**

```bash
git add src/mobia/infra/tls.py src/mobia/infra/db.py src/mobia/infra/queue.py alembic/env.py tests/unit
git commit -m "feat(TEC-203): producao so conecta ao Postgres por TLS 1.3 e ao Redis por rediss"
```

---

### Task 4: keyring da chave de conteúdo e blob v2

**Files:**
- Modify: `src/mobia/app/config.py` (campos e validator), `src/mobia/infra/crypto.py`
- Test: `tests/unit/test_crypto_keyring.py` (novo); ajustar `grep -rln VERSAO_ATUAL tests src`

**Interfaces:**
- Produces:
  - `Settings.content_encryption_keys: dict[str, str]` (id `AAAAMMDD` → base64), `Settings.content_encryption_key_ativa: str`.
  - `crypto.VERSAO_LEGADA = 1`, `crypto.VERSAO_COM_ID = 2`.
  - `crypto.id_da_chave(blob: bytes) -> int | None` — id do keyring (v2) ou `None` (v1, chave legada).
  - `crypto.id_da_chave_ativa() -> int | None` — o id que cifra agora, ou `None` se o keyring está vazio (grava v1).
  - `encrypt_bytes`/`decrypt_bytes` mantêm a assinatura.

- [ ] **Step 1: Testes que falham**

```python
"""TEC-203, D1: o keyring. v1 continua decifrando; v2 carrega o id da chave."""

import base64
import os

import pytest

from mobia.app.config import Settings
from mobia.infra import crypto
from mobia.infra.crypto import DecryptionError, decrypt_bytes, encrypt_bytes, id_da_chave


def _chave() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def keyring(monkeypatch):
    chaves = {"20260101": _chave(), "20260926": _chave()}

    def configurar(ativa: str | None, **extra: str) -> None:
        valores = {"content_encryption_keys": chaves, **extra}
        if ativa is not None:
            valores["content_encryption_key_ativa"] = ativa
        monkeypatch.setattr(crypto, "get_settings", lambda: Settings(**valores))

    return configurar


def test_sem_keyring_grava_v1_como_antes(monkeypatch):
    blob = encrypt_bytes(b"oi", "aad")
    assert blob[0] == crypto.VERSAO_LEGADA
    assert id_da_chave(blob) is None
    assert decrypt_bytes(blob, "aad") == b"oi"


def test_com_keyring_grava_v2_com_a_ativa(keyring):
    keyring("20260926")
    blob = encrypt_bytes(b"oi", "aad")
    assert blob[0] == crypto.VERSAO_COM_ID
    assert id_da_chave(blob) == 20260926
    assert decrypt_bytes(blob, "aad") == b"oi"


def test_blob_da_chave_anterior_continua_decifrando(keyring):
    keyring("20260101")
    antigo = encrypt_bytes(b"oi", "aad")
    keyring("20260926")
    assert decrypt_bytes(antigo, "aad") == b"oi"


def test_v1_decifra_com_keyring_configurado(keyring):
    legado = encrypt_bytes(b"oi", "aad")  # antes do keyring, com a chave legada
    keyring("20260926")
    assert decrypt_bytes(legado, "aad") == b"oi"


def test_id_fora_do_keyring_reprova_sem_ecoar_o_aad(keyring):
    keyring("20260926")
    blob = bytearray(encrypt_bytes(b"oi", "telefone-do-lead"))
    blob[1:5] = (20991231).to_bytes(4, "big")
    with pytest.raises(DecryptionError) as erro:
        decrypt_bytes(bytes(blob), "telefone-do-lead")
    assert "telefone-do-lead" not in str(erro.value)


def test_id_adulterado_para_outra_chave_do_keyring_nao_autentica(keyring):
    keyring("20260926")
    blob = bytearray(encrypt_bytes(b"oi", "aad"))
    blob[1:5] = (20260101).to_bytes(4, "big")
    with pytest.raises(DecryptionError):
        decrypt_bytes(bytes(blob), "aad")


def test_ativa_fora_do_keyring_reprova_na_construcao():
    with pytest.raises(ValueError, match="ativa"):
        Settings(content_encryption_keys={"20260926": _chave()}, content_encryption_key_ativa="20260101")


def test_id_que_nao_e_data_reprova():
    with pytest.raises(ValueError, match="AAAAMMDD"):
        Settings(content_encryption_keys={"chave1": _chave()}, content_encryption_key_ativa="chave1")


def test_chave_que_nao_tem_32_bytes_reprova():
    curta = base64.b64encode(os.urandom(16)).decode()
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(content_encryption_keys={"20260926": curta}, content_encryption_key_ativa="20260926")
```

Acrescente ao arquivo de guardas de produção existente (ache com `grep -rln "_recusar_chave_de_desenvolvimento" tests`) um caso: em produção, `CONTENT_ENCRYPTION_KEYS` contendo `CHAVE_DE_DESENVOLVIMENTO` como valor reprova com `ConfiguracaoInsegura`.

- [ ] **Step 2: Ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_crypto_keyring.py -v`.

- [ ] **Step 3: Config** — em `Settings`, logo abaixo de `content_encryption_key`:

```python
    # TEC-203, D1. O keyring: id (a data de criacao, AAAAMMDD) -> chave base64.
    # Vazio, tudo continua como antes -- grava v1 com `content_encryption_key`,
    # que passa a ser a chave LEGADA e segue decifrando todo blob v1. Com
    # chaves, a gravacao sai em v2 com a ativa e as demais so decifram. O id e
    # data para que a idade da chave se leia dele sem campo a mais (ver o aviso
    # dos 90 dias em `infra/rotacao.py`).
    content_encryption_keys: dict[str, str] = {}
    content_encryption_key_ativa: str = ""
```
Validator (perto dos outros):

```python
    @model_validator(mode="after")
    def _validar_keyring(self) -> "Settings":
        """Keyring errado falharia so na primeira cifra -- aqui falha na subida."""
        if not self.content_encryption_keys:
            if self.content_encryption_key_ativa:
                raise ValueError("CONTENT_ENCRYPTION_KEY_ATIVA sem CONTENT_ENCRYPTION_KEYS")
            return self
        for identificador, chave in self.content_encryption_keys.items():
            data_do_id(identificador)
            if len(base64.b64decode(chave)) != 32:
                raise ValueError(f"a chave {identificador} do keyring nao tem 32 bytes apos o base64")
            if self.em_producao and chave == CHAVE_DE_DESENVOLVIMENTO:
                raise ConfiguracaoInsegura(
                    f"a chave {identificador} do keyring e a de desenvolvimento e "
                    f"ENVIRONMENT={self.environment}."
                )
        if self.content_encryption_key_ativa not in self.content_encryption_keys:
            raise ValueError(
                f"a chave ativa {self.content_encryption_key_ativa!r} nao esta no keyring"
            )
        return self
```
E a função de módulo (em `config.py`, acima de `Settings`; importe `base64` e `from datetime import date`):

```python
def data_do_id(identificador: str) -> date:
    """O id de chave e a data em que ela nasceu. TEC-203, D1."""
    try:
        if len(identificador) != 8 or not identificador.isdigit():
            raise ValueError
        return date(int(identificador[:4]), int(identificador[4:6]), int(identificador[6:]))
    except ValueError:
        raise ValueError(f"id de chave {identificador!r} nao e uma data AAAAMMDD") from None
```

- [ ] **Step 4: `crypto.py`** — substitua o bloco de `VERSAO_ATUAL` até `decrypt_bytes`, preservando `marca_do_aad`, `aad_de` e as funções de texto/json:

```python
# Byte de versao a frente do blob. v1 foi a unica ate a TEC-203 e continua
# decifrando para sempre, com a chave legada (`content_encryption_key`). v2
# carrega o id da chave do keyring logo depois da versao, e e ele que permite
# duas chaves validas ao mesmo tempo -- a razao de o byte existir desde a
# TEC-126. O id nao entra no AAD: ele ESCOLHE a chave, e adulterado escolhe
# outra, sob a qual a tag nao autentica.
VERSAO_LEGADA = 1
VERSAO_COM_ID = 2
ID_BYTES = 4

_TAMANHO_MINIMO_V1 = 1 + NONCE_BYTES + TAG_BYTES
_TAMANHO_MINIMO_V2 = 1 + ID_BYTES + NONCE_BYTES + TAG_BYTES


def _decodificar(chave_b64: str, nome: str) -> bytes:
    chave = base64.b64decode(chave_b64)
    if len(chave) != CHAVE_BYTES:
        raise ValueError(f"{nome} deve ter {CHAVE_BYTES} bytes apos o base64, tem {len(chave)}")
    return chave


def _chave_legada() -> bytes:
    return _decodificar(get_settings().content_encryption_key, "content_encryption_key")


def _chave_do_keyring(identificador: int) -> bytes | None:
    chave = get_settings().content_encryption_keys.get(f"{identificador:08d}")
    return None if chave is None else _decodificar(chave, f"a chave {identificador}")


def id_da_chave_ativa() -> int | None:
    """O id que cifra agora, ou `None` com o keyring vazio (grava v1)."""
    ativa = get_settings().content_encryption_key_ativa
    return int(ativa) if ativa else None


def id_da_chave(blob: bytes) -> int | None:
    """O id do keyring que cifrou o blob; `None` e v1, a chave legada.

    Existe para o `recifrar` saber o que ainda falta reescrever sem decifrar.
    """
    if blob[:1] == bytes([VERSAO_COM_ID]) and len(blob) >= _TAMANHO_MINIMO_V2:
        return int.from_bytes(blob[1 : 1 + ID_BYTES], "big")
    return None
```
`_chave_da_marca` passa a derivar da chave ativa quando houver:

```python
    ativa = id_da_chave_ativa()
    base = _chave_legada() if ativa is None else _chave_do_keyring(ativa)
    assert base is not None  # `_validar_keyring` garante que a ativa esta no keyring
    return HKDF(algorithm=hashes.SHA256(), length=CHAVE_BYTES, salt=None,
                info=b"mobia/marca-do-aad/v1").derive(base)
```
(Mantenha a docstring; a "Consequencia aceita" dela já cobre a troca da ativa — acrescente "ou a chave ativa do keyring" onde ela fala da troca da `content_encryption_key`.)

```python
def encrypt_bytes(dados: bytes, aad: str) -> bytes:
    """A mesma cifra de `encrypt`, sobre bytes. TEC-132: o arquivo de midia."""
    # Nonce novo a cada chamada: o mesmo conteudo cifra diferente toda vez, entao
    # busca por igualdade sobre conteudo deixa de existir. E intencional.
    nonce = os.urandom(NONCE_BYTES)
    ativa = id_da_chave_ativa()
    if ativa is None:
        return bytes([VERSAO_LEGADA]) + nonce + AESGCM(_chave_legada()).encrypt(nonce, dados, aad.encode())
    chave = _chave_do_keyring(ativa)
    assert chave is not None  # `_validar_keyring` garante que a ativa esta no keyring
    cabecalho = bytes([VERSAO_COM_ID]) + ativa.to_bytes(ID_BYTES, "big")
    return cabecalho + nonce + AESGCM(chave).encrypt(nonce, dados, aad.encode())


def decrypt_bytes(blob: bytes, aad: str) -> bytes:
    """Inverso de `encrypt_bytes`, com as mesmas guardas de `decrypt`."""
    # Sem as guardas de tamanho um blob curto sai como ValueError cru do
    # `cryptography` ("Nonce must be between 8 and 128 bytes") e quem captura
    # DecryptionError nao pega. A mensagem nunca carrega o blob nem o AAD.
    versao = blob[0] if blob else None
    if versao == VERSAO_LEGADA:
        if len(blob) < _TAMANHO_MINIMO_V1:
            raise DecryptionError(f"blob de {len(blob)} bytes, minimo {_TAMANHO_MINIMO_V1}: aad={marca_do_aad(aad)}")
        chave, inicio = _chave_legada(), 1
    elif versao == VERSAO_COM_ID:
        if len(blob) < _TAMANHO_MINIMO_V2:
            raise DecryptionError(f"blob de {len(blob)} bytes, minimo {_TAMANHO_MINIMO_V2}: aad={marca_do_aad(aad)}")
        identificador = int.from_bytes(blob[1 : 1 + ID_BYTES], "big")
        encontrada = _chave_do_keyring(identificador)
        if encontrada is None:
            raise DecryptionError(f"chave {identificador} fora do keyring: aad={marca_do_aad(aad)}")
        chave, inicio = encontrada, 1 + ID_BYTES
    else:
        # Versao desconhecida nao e tentada: parsear com o layout errado
        # produziria InvalidTag e esconderia a causa real.
        raise DecryptionError(f"versao de cifra desconhecida {versao}: aad={marca_do_aad(aad)}")
    nonce, corpo = blob[inicio : inicio + NONCE_BYTES], blob[inicio + NONCE_BYTES :]
    try:
        return AESGCM(chave).decrypt(nonce, corpo, aad.encode())
    except InvalidTag as exc:
        raise DecryptionError(f"conteudo nao autentica: aad={marca_do_aad(aad)}") from exc
```
Remova `_cifra`, `_TAMANHO_MINIMO` e `VERSAO_ATUAL`; `grep -rn "VERSAO_ATUAL\|_cifra()\|_TAMANHO_MINIMO\b" src tests alembic` e troque cada uso por `VERSAO_LEGADA` / o equivalente. A migration `0004` que importar `VERSAO_ATUAL` recebe `VERSAO_LEGADA` (é o que ela sempre gravou).

- [ ] **Step 5: Rodar** — `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`. Expected: passa.

- [ ] **Step 6: Gates e commit**

```bash
git add src/mobia/app/config.py src/mobia/infra/crypto.py tests alembic
git commit -m "feat(TEC-203): a chave de conteudo vira keyring e o blob v2 carrega o id da chave"
```

---

### Task 5: chave de índice, `chave_de`, `indice_de_telefone` e o aviso dos 90 dias

**Files:**
- Modify: `src/mobia/app/config.py`, `src/mobia/app/main.py::lifespan`, `src/mobia/workers/main.py::startup`
- Create: `src/mobia/domain/identidade/indice.py` (só as funções puras nesta task), `src/mobia/infra/rotacao.py`
- Test: `tests/unit/test_indice_do_lead.py`, `tests/unit/test_rotacao.py` (novos)

**Interfaces:**
- Produces:
  - `Settings.lead_indice_chave: str` (default `CHAVE_DO_INDICE_DE_DESENVOLVIMENTO = "dev-indice-do-lead-nao-use-em-producao"`), `Settings.lead_indice_chave_id: str` (default `"20260926"`).
  - `indice.chave_de(channel: str, valor: str) -> str` — 64 hex.
  - `indice.indice_de_telefone(canonico: str) -> str` — 64 hex.
  - `rotacao.chaves_vencidas(settings: Settings, hoje: date) -> list[str]`; `rotacao.avisar_rotacao_vencida(settings: Settings, hoje: date | None = None) -> None`.

- [ ] **Step 1: Testes que falham**

`tests/unit/test_indice_do_lead.py`:
```python
"""TEC-203, D2: a chave do lead e o HMAC do valor CRU; o telefone tem indice proprio."""

import re

from mobia.domain.identidade.indice import chave_de, indice_de_telefone


def test_chave_e_hex_de_64_e_deterministica():
    chave = chave_de("whatsapp", "5548999990000")
    assert re.fullmatch(r"[0-9a-f]{64}", chave)
    assert chave == chave_de("whatsapp", "5548999990000")


def test_canal_faz_parte_do_dominio():
    assert chave_de("whatsapp", "abc") != chave_de("web", "abc")


def test_wa_id_com_e_sem_o_nono_digito_sao_conversas_distintas():
    # Espelha a chave de antes da TEC-203, que era o wa_id cru.
    assert chave_de("whatsapp", "554899990000") != chave_de("whatsapp", "5548999990000")


def test_indice_de_telefone_nao_colide_com_chave_do_whatsapp():
    assert indice_de_telefone("5548999990000") != chave_de("whatsapp", "5548999990000")


def test_trocar_a_chave_de_indice_muda_a_chave(monkeypatch):
    from mobia.app.config import Settings
    from mobia.domain.identidade import indice

    antes = chave_de("whatsapp", "5548999990000")
    monkeypatch.setattr(indice, "get_settings", lambda: Settings(lead_indice_chave="outra" * 8))
    assert chave_de("whatsapp", "5548999990000") != antes
```

`tests/unit/test_rotacao.py`:
```python
"""TEC-203, D1: chave com mais de 90 dias gera aviso, e nunca derruba a subida."""

import base64
import os
from datetime import date

from mobia.app.config import Settings
from mobia.infra.rotacao import chaves_vencidas


def _keyring(ativa: str) -> dict[str, object]:
    return {
        "content_encryption_keys": {ativa: base64.b64encode(os.urandom(32)).decode()},
        "content_encryption_key_ativa": ativa,
    }


def test_chaves_novas_nao_vencem():
    settings = Settings(**_keyring("20260901"), lead_indice_chave_id="20260901")
    assert chaves_vencidas(settings, date(2026, 11, 30)) == []


def test_chave_de_conteudo_com_91_dias_vence():
    settings = Settings(**_keyring("20260601"), lead_indice_chave_id="20260926")
    assert chaves_vencidas(settings, date(2026, 8, 31)) == ["CONTENT_ENCRYPTION_KEY_ATIVA"]


def test_chave_de_indice_vence_pelo_proprio_id():
    settings = Settings(lead_indice_chave_id="20260101")
    assert chaves_vencidas(settings, date(2026, 9, 26)) == ["LEAD_INDICE_CHAVE_ID"]


def test_keyring_vazio_nao_tem_idade_para_vencer():
    assert "CONTENT_ENCRYPTION_KEY_ATIVA" not in chaves_vencidas(Settings(), date(2030, 1, 1))
```

- [ ] **Step 2: Ver falhar** — `./.venv/Scripts/python.exe -m pytest tests/unit/test_indice_do_lead.py tests/unit/test_rotacao.py -v`.

- [ ] **Step 3: Config** — constante no topo, junto dos outros defaults:

```python
# A chave do blind index do lead em desenvolvimento (TEC-203, D2). Mesmo molde
# da CHAVE_DE_DESENVOLVIMENTO: commitada de proposito, e recusada em producao.
# Quem a tiver recalcula a chave de qualquer telefone e acha a conversa dele.
CHAVE_DO_INDICE_DE_DESENVOLVIMENTO = "dev-indice-do-lead-nao-use-em-producao"
```
Campos, abaixo de `auditoria_chave_do_lead`:

```python
    # TEC-203, D2. A chave do HMAC que o `conversation_key` guarda no lugar do
    # telefone. Propria, e nao a de cifra nem a do `lead_ref`: chaves com
    # funcoes diferentes nao se reaproveitam. O id e a data de criacao, para o
    # aviso dos 90 dias; trocar esta chave exige `scripts/reindexar_leads.py`
    # com o servico parado (ver `docs/seguranca/segredos.md`).
    lead_indice_chave: str = CHAVE_DO_INDICE_DE_DESENVOLVIMENTO
    lead_indice_chave_id: str = "20260926"
```
Validator, no molde de `_recusar_chave_do_lead_de_desenvolvimento_em_producao`:

```python
    @model_validator(mode="after")
    def _recusar_chave_de_indice_de_desenvolvimento_em_producao(self) -> "Settings":
        """TEC-203. Chave de HMAC publicamente conhecida nao falha: ela so deixa
        qualquer um recalcular a chave de um telefone e achar a conversa dele."""
        data_do_id(self.lead_indice_chave_id)
        if self.em_producao and self.lead_indice_chave == CHAVE_DO_INDICE_DE_DESENVOLVIMENTO:
            raise ConfiguracaoInsegura(
                "LEAD_INDICE_CHAVE esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Gere uma: "
                'python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        return self
```
Acrescente `LEAD_INDICE_CHAVE` à fixture `segredos_de_producao` e ao `.env.example` (com o default de dev e o comentário de que é recusado em produção).

- [ ] **Step 4: `src/mobia/domain/identidade/indice.py`**

```python
"""A chave do lead e a porta para o valor cru dele. TEC-203, D2.

O `conversation_key` de toda tabela guarda `chave_de(channel, valor)`, e nao o
valor: no WhatsApp o valor e o telefone. O valor cru mora cifrado em
`identidades_de_lead` e sai so por `revelar`/`telefones_de`, nas bordas que
precisam dele.

**`chave_de` nao normaliza, de proposito.** Antes desta card a chave era o
`wa_id` cru, e dois `wa_id` diferentes (com e sem o 9) eram duas conversas; o
envio vai para o `wa_id` que a Meta mandou. Normalizar aqui juntaria as duas e
mandaria para uma grafia que a Meta talvez nao reconheca. Quem precisa do
TELEFONE -- busca, absorcao, o vinculo do widget -- usa `indice_de_telefone`,
sobre a forma canonica de `telefone.normalizar`.

Unico modulo que conhece `lead_indice_chave`.
"""

import hashlib
import hmac

from mobia.app.config import get_settings


def _hmac(mensagem: str) -> str:
    chave = get_settings().lead_indice_chave.encode("utf-8")
    return hmac.new(chave, mensagem.encode("utf-8"), hashlib.sha256).hexdigest()


def chave_de(channel: str, valor: str) -> str:
    """HMAC-SHA256 de `channel:valor`, em hex. Cabe no `String(64)` de sempre."""
    return _hmac(f"{channel}:{valor}")


def indice_de_telefone(canonico: str) -> str:
    """HMAC de `telefone:{canonico}`. O prefixo o separa de qualquer chave de canal."""
    return _hmac(f"telefone:{canonico}")
```

- [ ] **Step 5: `src/mobia/infra/rotacao.py`**

```python
"""O aviso de chave vencida. TEC-203, D1, RNF-14 (rotacao a cada 90 dias).

**Aviso, e nunca recusa.** Derrubar a producao porque uma data passou e pior
que o risco que a regra mitiga, e quem agenda a rotacao e o runbook, nao a
subida do processo. O log existe para o alarme do provedor pegar.
"""

from datetime import UTC, date, datetime, timedelta

import structlog

from mobia.app.config import Settings, data_do_id

log = structlog.get_logger(__name__)

VALIDADE = timedelta(days=90)


def chaves_vencidas(settings: Settings, hoje: date) -> list[str]:
    vencidas = []
    ativa = settings.content_encryption_key_ativa
    if ativa and hoje - data_do_id(ativa) > VALIDADE:
        vencidas.append("CONTENT_ENCRYPTION_KEY_ATIVA")
    if hoje - data_do_id(settings.lead_indice_chave_id) > VALIDADE:
        vencidas.append("LEAD_INDICE_CHAVE_ID")
    return vencidas


def avisar_rotacao_vencida(settings: Settings, hoje: date | None = None) -> None:
    """So em producao: em desenvolvimento a chave default nunca roda, e o aviso seria ruido."""
    if not settings.em_producao:
        return
    for nome in chaves_vencidas(settings, hoje or datetime.now(UTC).date()):
        log.warning("seguranca.rotacao_vencida", chave=nome, validade_dias=VALIDADE.days)
```
Chame `avisar_rotacao_vencida(get_settings())` no início de `app/main.py::lifespan` e de `workers/main.py::startup` (depois de onde `settings` já é obtido).

- [ ] **Step 6: Rodar** — `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`.

- [ ] **Step 7: Gates e commit**

```bash
git add src tests .env.example
git commit -m "feat(TEC-203): a chave do lead e o HMAC do valor cru e chave vencida gera aviso"
```

---

### Task 6: identidade do lead, migration `0061` e reindexação

**Files:**
- Modify: `src/mobia/domain/identidade/models.py` (acrescentar `IdentidadeDeLead`; `VinculoDeSessao` cifrado), `src/mobia/domain/identidade/indice.py` (funções de banco)
- Create: `src/mobia/domain/identidade/reindexacao.py`, `alembic/versions/0061_identidade_do_lead_cifrada.py`, `scripts/reindexar_leads.py`
- Modify: `tests/conftest.py` (`TABELAS` ganha `identidades_de_lead`)
- Test: `tests/integration/test_reindexacao_do_lead.py`, `tests/unit/test_tabelas_com_chave_de_lead.py` (novos)

**Interfaces:**
- Consumes: `chave_de`, `indice_de_telefone` (Task 5); `encrypt`/`decrypt` (Task 4).
- Produces:
  - `models.IdentidadeDeLead` (`identidades_de_lead`: `channel String(32)` PK, `conversation_key String(64)` PK, `valor_cifrado LargeBinary`, `criado_em timestamptz`).
  - `models.aad_da_identidade(channel, conversation_key) -> str`; `models.aad_do_vinculo(channel, conversation_key) -> str`.
  - `VinculoDeSessao.telefone_cifrado: bytes`, `VinculoDeSessao.telefone_indice: str` (sem `telefone`).
  - `indice.IdentidadeAusente(Exception)`.
  - `async indice.registrar(session: AsyncSession, channel: str, valor: str) -> str` — upsert sem commit.
  - `async indice.revelar(session: AsyncSession, channel: str, chave: str) -> str`.
  - `async indice.telefones_de(session: AsyncSession, pares: Sequence[tuple[str, str]]) -> dict[tuple[str, str], str | None]` — canônico (só dígitos com `55`) ou `None`.
  - `reindexacao.TABELAS_COM_CHAVE_DE_LEAD: tuple[str, ...]`.
  - `reindexacao.reindexar(conn: Connection, *, tabelas: Sequence[str], nova_chave: Callable[[str, str], str], modo: Literal["migracao", "rotacao", "reversao"], chave_do_lead_antiga: str, chave_do_lead_nova: str) -> int` — devolve quantos pares mudaram.

- [ ] **Step 1: Modelos** — em `identidade/models.py`:

```python
def aad_da_identidade(channel: str, conversation_key: str) -> str:
    """Amarra o valor cifrado a sua propria linha. Prefixado por tamanho pelo
    mesmo motivo de `context/models.py::aad_do_resumo`."""
    return aad_de(f"{len(channel)}:{channel}:{conversation_key}", "identidade_do_lead")


def aad_do_vinculo(channel: str, conversation_key: str) -> str:
    return aad_de(f"{len(channel)}:{channel}:{conversation_key}", "telefone_do_vinculo")


class IdentidadeDeLead(Base):
    """O valor cru por tras de um `conversation_key`. TEC-203, D2.

    No WhatsApp o valor e o telefone; no web, a sessao. As ~20 tabelas que
    guardam o `conversation_key` guardam o HMAC dele, e esta e a unica linha
    onde o valor existe -- cifrado, e so revelado por `indice.revelar`.
    """

    __tablename__ = "identidades_de_lead"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor_cifrado: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```
Em `VinculoDeSessao`, troque a coluna `telefone` e o índice:

```python
    # TEC-203. O telefone cifrado e o indice dele. Ate a TEC-203 o numero
    # ficava em claro, "como o conversation_key do WhatsApp ja e"; os dois
    # deixaram de ser. A absorcao e a busca consultam `telefone_indice`.
    telefone_cifrado: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    telefone_indice: Mapped[str] = mapped_column(String(64), nullable=False)
    ...
    __table_args__ = (Index("ix_vinculos_de_sessao_telefone_indice", "telefone_indice"),)
```
Atualize a docstring do módulo: o parágrafo "O lado WhatsApp nao precisa: o `conversation_key` dele ja e o numero" passa a dizer que a absorção revela o `wa_id`, normaliza e consulta por `telefone_indice`.

- [ ] **Step 2: Funções de banco em `indice.py`**

```python
class IdentidadeAusente(Exception):
    """Chave sem identidade. E bug de dado, nunca caso de negocio."""


async def registrar(session: AsyncSession, channel: str, valor: str) -> str:
    """Grava a identidade se ainda nao existe; devolve a chave. Nao commita --
    entra na mesma transacao de quem grava a linha que usa a chave."""
    chave = chave_de(channel, valor)
    await session.execute(
        pg_insert(IdentidadeDeLead)
        .values(
            channel=channel,
            conversation_key=chave,
            valor_cifrado=encrypt(valor, aad_da_identidade(channel, chave)),
        )
        .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
    )
    return chave


async def revelar(session: AsyncSession, channel: str, chave: str) -> str:
    blob = await session.scalar(
        select(IdentidadeDeLead.valor_cifrado).where(
            IdentidadeDeLead.channel == channel, IdentidadeDeLead.conversation_key == chave
        )
    )
    if blob is None:
        # Sem o valor na mensagem: a chave nao e dado pessoal, mas o canal
        # basta para diagnosticar e o log agregado nao precisa de mais.
        raise IdentidadeAusente(f"sem identidade para uma chave do canal {channel}")
    valor = decrypt(bytes(blob), aad_da_identidade(channel, chave))
    assert valor is not None
    return valor


async def telefones_de(
    session: AsyncSession, pares: Sequence[tuple[str, str]]
) -> dict[tuple[str, str], str | None]:
    """O telefone canonico de cada lead, pelas duas origens. TEC-129 e TEC-203.

    No WhatsApp e o `wa_id` normalizado; no web, o que o lead digitou no
    widget, se digitou. `None` e "nao ha telefone", nunca a chave no lugar.
    """
    resultado: dict[tuple[str, str], str | None] = {par: None for par in pares}
    if not pares:
        return resultado
    linhas = await session.execute(
        select(IdentidadeDeLead.channel, IdentidadeDeLead.conversation_key, IdentidadeDeLead.valor_cifrado)
        .where(IdentidadeDeLead.channel == CANAL_WHATSAPP)
        .where(IdentidadeDeLead.conversation_key.in_([k for c, k in pares if c == CANAL_WHATSAPP]))
    )
    for channel, chave, blob in linhas:
        valor = decrypt(bytes(blob), aad_da_identidade(channel, chave))
        resultado[(channel, chave)] = normalizar(valor) if valor else None
    vinculos = await session.execute(
        select(VinculoDeSessao.channel, VinculoDeSessao.conversation_key, VinculoDeSessao.telefone_cifrado)
        .where(tuple_(VinculoDeSessao.channel, VinculoDeSessao.conversation_key).in_(
            [par for par in pares if par[0] != CANAL_WHATSAPP]
        ))
    )
    for channel, chave, blob in vinculos:
        resultado[(channel, chave)] = decrypt(bytes(blob), aad_do_vinculo(channel, chave))
    return resultado
```
Imports: `from collections.abc import Sequence`, `select`, `tuple_`, `pg_insert`, `AsyncSession`, `CANAL_WHATSAPP` (de `domain/messages/canais.py`), `normalizar`, `encrypt`/`decrypt`, os modelos e AADs. Se `tuple_(...).in_([])` gerar SQL inválido, curto-circuite a consulta quando a lista estiver vazia.

- [ ] **Step 3: Núcleo da reindexação** — `src/mobia/domain/identidade/reindexacao.py`:

```python
"""A reindexacao do lead: a mesma maquina para a migration e para a rotacao. TEC-203, D3.

Troca o `conversation_key` de cada par, em todas as tabelas, e arrasta junto o
que depende dele: identidade, remetente/destinatario das mensagens, evento de
rate limit, `lead_ref` da trilha, AAD do resumo e do vinculo.

Tres modos, e a diferenca entre eles e so DE ONDE vem o valor cru:

- `migracao` (0061, subida): o par que nao tem identidade ainda guarda o valor
  cru na coluna. O que ja tem identidade ja foi reindexado -- e a idempotencia
  que deixa retomar uma subida interrompida.
- `rotacao` (script, chave de indice nova): todo par tem identidade; o valor
  vem dela. Par sem identidade aqui e bug, e reprova.
- `reversao` (0061, descida): o valor vem da identidade e VIRA a chave; nada e
  gravado em `identidades_de_lead`, que a descida apaga em seguida.

**Tabelas imutaveis.** `lead_score_audit`, `conversation_intent_audit` e
`eventos_auditoria` recusam UPDATE por trigger. A reindexacao desliga a
trigger de cada uma, reescreve e religa, na mesma transacao. E excecao
declarada: trocar o pseudonimo do lead nao altera o fato registrado, e manter
o telefone em claro numa tabela imutavel seria a violacao que a TEC-203
existe para eliminar.

Sync, sobre `Connection`: a migration roda dentro do `run_sync` do Alembic, e
o script abre a mesma coisa com `engine.begin()` + `run_sync`.
"""

from collections.abc import Callable, Sequence
from typing import Literal

from sqlalchemy import Connection, text

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.context.models import aad_do_resumo
from mobia.domain.identidade.models import aad_da_identidade, aad_do_vinculo
from mobia.infra.crypto import decrypt, encrypt

# Toda tabela com `conversation_key`. `tests/unit/test_tabelas_com_chave_de_lead.py`
# reprova se aparecer uma fora daqui -- a proxima tabela nao escapa da rotacao
# em silencio. A 0061 NAO usa esta lista: tem copia literal, porque migration
# aplicada nao muda quando o codigo muda.
TABELAS_COM_CHAVE_DE_LEAD = (
    "agendamentos",
    "atendimento_humano",
    "consentimentos",
    "conversas",
    "conversation_intent",
    "conversation_intent_audit",
    "conversation_summaries",
    "followups",
    "handoffs",
    "janelas_propostas",
    "lead_qualification",
    "lead_score_audit",
    "lista_de_espera",
    "messages",
    "moderation_events",
    "optout_events",
    "recomendacoes",
    "referencias_de_lead",
    "tarefas_de_corretor",
    "vinculos_de_sessao",
)

TRIGGERS_DE_IMUTABILIDADE = {
    "lead_score_audit": "lead_score_audit_imutavel",
    "conversation_intent_audit": "conversation_intent_audit_imutavel",
    "eventos_auditoria": "eventos_auditoria_imutavel",
}

Modo = Literal["migracao", "rotacao", "reversao"]


def _pares(conn: Connection, tabelas: Sequence[str]) -> list[tuple[str, str]]:
    uniao = " UNION ".join(
        f"SELECT channel, conversation_key FROM {t} WHERE conversation_key IS NOT NULL" for t in tabelas
    )
    return [(c, k) for c, k in conn.execute(text(uniao))]


def _identidade(conn: Connection, channel: str, chave: str) -> str | None:
    blob = conn.execute(
        text("SELECT valor_cifrado FROM identidades_de_lead WHERE channel = :c AND conversation_key = :k"),
        {"c": channel, "k": chave},
    ).scalar()
    return None if blob is None else decrypt(bytes(blob), aad_da_identidade(channel, chave))


def _triggers(conn: Connection, acao: Literal["DISABLE", "ENABLE"]) -> None:
    for tabela, trigger in TRIGGERS_DE_IMUTABILIDADE.items():
        conn.execute(text(f"ALTER TABLE {tabela} {acao} TRIGGER {trigger}"))


def reindexar(
    conn: Connection,
    *,
    tabelas: Sequence[str],
    nova_chave: Callable[[str, str], str],
    modo: Modo,
    chave_do_lead_antiga: str,
    chave_do_lead_nova: str,
) -> int:
    mudados = 0
    _triggers(conn, "DISABLE")
    try:
        for channel, atual in _pares(conn, tabelas):
            valor = _identidade(conn, channel, atual)
            if valor is None:
                if modo != "migracao":
                    raise RuntimeError(f"par do canal {channel} sem identidade no modo {modo}")
                valor = atual
            novo = nova_chave(channel, valor)
            if novo == atual and chave_do_lead_antiga == chave_do_lead_nova:
                continue
            _mover(conn, tabelas, channel, atual, novo, valor, modo)
            _recalcular_lead_ref(conn, channel, atual, novo, chave_do_lead_antiga, chave_do_lead_nova)
            mudados += 1
    finally:
        _triggers(conn, "ENABLE")
    return mudados


def _mover(conn: Connection, tabelas: Sequence[str], channel: str, atual: str, novo: str, valor: str, modo: Modo) -> None:
    if novo == atual:
        return
    parametros = {"c": channel, "atual": atual, "novo": novo}
    # O resumo le com o AAD da chave velha antes de a linha mudar de chave.
    resumo = conn.execute(
        text("SELECT resumo FROM conversation_summaries WHERE channel = :c AND conversation_key = :atual"),
        parametros,
    ).scalar()
    telefone_do_vinculo = conn.execute(
        text("SELECT telefone_cifrado FROM vinculos_de_sessao WHERE channel = :c AND conversation_key = :atual"),
        parametros,
    ).scalar() if _tem_coluna(conn, "vinculos_de_sessao", "telefone_cifrado") else None

    for tabela in tabelas:
        conn.execute(
            text(f"UPDATE {tabela} SET conversation_key = :novo WHERE channel = :c AND conversation_key = :atual"),
            parametros,
        )
    for coluna in ("sender_external_id", "recipient_external_id"):
        conn.execute(
            text(
                f"UPDATE messages SET {coluna} = :novo "
                f"WHERE channel = :c AND conversation_key = :novo AND {coluna} = :atual"
            ),
            parametros,
        )
    conn.execute(
        text("UPDATE rate_limit_events SET chave = :novo WHERE escopo = 'numero' AND channel = :c AND chave = :atual"),
        parametros,
    )
    if resumo is not None:
        texto = decrypt(bytes(resumo), aad_do_resumo(channel, atual))
        conn.execute(
            text("UPDATE conversation_summaries SET resumo = :r WHERE channel = :c AND conversation_key = :novo"),
            {**parametros, "r": encrypt(texto, aad_do_resumo(channel, novo))},
        )
    if telefone_do_vinculo is not None:
        telefone = decrypt(bytes(telefone_do_vinculo), aad_do_vinculo(channel, atual))
        conn.execute(
            text("UPDATE vinculos_de_sessao SET telefone_cifrado = :t WHERE channel = :c AND conversation_key = :novo"),
            {**parametros, "t": encrypt(telefone, aad_do_vinculo(channel, novo))},
        )

    conn.execute(
        text("DELETE FROM identidades_de_lead WHERE channel = :c AND conversation_key = :atual"), parametros
    )
    if modo != "reversao":
        conn.execute(
            text(
                "INSERT INTO identidades_de_lead (channel, conversation_key, valor_cifrado) "
                "VALUES (:c, :novo, :v) ON CONFLICT DO NOTHING"
            ),
            {**parametros, "v": encrypt(valor, aad_da_identidade(channel, novo))},
        )


def _recalcular_lead_ref(conn: Connection, channel: str, atual: str, novo: str, antiga: str, nova: str) -> None:
    conn.execute(
        text("UPDATE eventos_auditoria SET lead_ref = :novo WHERE lead_ref = :antigo"),
        {"antigo": lead_ref(channel, atual, chave=antiga), "novo": lead_ref(channel, novo, chave=nova)},
    )


def _tem_coluna(conn: Connection, tabela: str, coluna: str) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": tabela, "c": coluna},
    ).scalar())
```
Nota de desempenho para quem implementa: é um loop por par com ~25 statements. É aceitável para o volume da PR-01 e é o que o spec pede (janela de manutenção); não otimize com tabela temporária sem medir antes.

A rotação precisa também recalcular `telefone_indice` dos vínculos (depende da chave de índice). Acrescente:

```python
def reindexar_telefones_dos_vinculos(conn: Connection, indice: Callable[[str], str]) -> None:
    """Rotacao: o `telefone_indice` depende da chave de indice, e o par do
    vinculo nao muda por isso -- entao nao passa pelo loop de `reindexar`."""
    linhas = conn.execute(text("SELECT channel, conversation_key, telefone_cifrado FROM vinculos_de_sessao")).all()
    for channel, chave, blob in linhas:
        telefone = decrypt(bytes(blob), aad_do_vinculo(channel, chave))
        assert telefone is not None
        conn.execute(
            text("UPDATE vinculos_de_sessao SET telefone_indice = :i WHERE channel = :c AND conversation_key = :k"),
            {"i": indice(telefone), "c": channel, "k": chave},
        )
```

- [ ] **Step 4: Migration `alembic/versions/0061_identidade_do_lead_cifrada.py`**

```python
"""o telefone do lead sai do conversation_key e passa a morar cifrado

TEC-203, RNF-13, RT-08. Revoga, para o lead, a doutrina da Emenda E-01 ("o que
este sistema cifra e conteudo, nunca identificador").

Cria `identidades_de_lead`, troca o `conversation_key` de todas as tabelas
pelo HMAC do valor (`indice.chave_de`) e cifra o telefone de
`vinculos_de_sessao`. O backfill e em Python pela razao da 0004: o banco nao
tem a chave.

**Lista de tabelas copiada, e nao importada** de `reindexacao.TABELAS_COM_CHAVE_DE_LEAD`:
migration aplicada nao muda quando o codigo muda, e uma tabela criada depois
da 0061 nao existe ainda quando ela roda num banco novo.

**Desliga e religa as triggers de imutabilidade** das tres trilhas -- ver a
docstring de `domain/identidade/reindexacao.py`.

Revision ID: 0061
Revises: 0060
"""

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op
from mobia.app.config import get_settings
from mobia.domain.identidade.indice import chave_de, indice_de_telefone
from mobia.domain.identidade.models import aad_do_vinculo
from mobia.domain.identidade.reindexacao import reindexar
from mobia.infra.crypto import decrypt, encrypt

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_TABELAS = (
    "agendamentos", "atendimento_humano", "consentimentos", "conversas",
    "conversation_intent", "conversation_intent_audit", "conversation_summaries",
    "followups", "handoffs", "janelas_propostas", "lead_qualification",
    "lead_score_audit", "lista_de_espera", "messages", "moderation_events",
    "optout_events", "recomendacoes", "referencias_de_lead", "tarefas_de_corretor",
    "vinculos_de_sessao",
)  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "identidades_de_lead",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("valor_cifrado", sa.LargeBinary, nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    conn = op.get_bind()
    chave_do_lead = get_settings().auditoria_chave_do_lead
    reindexar(
        conn, tabelas=_TABELAS, nova_chave=chave_de, modo="migracao",
        chave_do_lead_antiga=chave_do_lead, chave_do_lead_nova=chave_do_lead,
    )

    # O vinculo muda de forma DEPOIS do loop: o AAD do telefone cifrado usa o
    # par, e o par ja e o definitivo aqui.
    op.add_column("vinculos_de_sessao", sa.Column("telefone_cifrado", sa.LargeBinary, nullable=True))
    op.add_column("vinculos_de_sessao", sa.Column("telefone_indice", sa.String(64), nullable=True))
    for channel, chave, telefone in conn.execute(
        text("SELECT channel, conversation_key, telefone FROM vinculos_de_sessao")
    ).all():
        conn.execute(
            text(
                "UPDATE vinculos_de_sessao SET telefone_cifrado = :t, telefone_indice = :i "
                "WHERE channel = :c AND conversation_key = :k"
            ),
            {"t": encrypt(telefone, aad_do_vinculo(channel, chave)), "i": indice_de_telefone(telefone),
             "c": channel, "k": chave},
        )
    op.alter_column("vinculos_de_sessao", "telefone_cifrado", nullable=False)
    op.alter_column("vinculos_de_sessao", "telefone_indice", nullable=False)
    op.drop_index("ix_vinculos_de_sessao_telefone", table_name="vinculos_de_sessao")
    op.drop_column("vinculos_de_sessao", "telefone")
    op.create_index("ix_vinculos_de_sessao_telefone_indice", "vinculos_de_sessao", ["telefone_indice"])


def downgrade() -> None:
    """Devolve o valor em claro as colunas. E o que um downgrade deve fazer:
    voltar ao estado de antes, e antes o telefone estava em claro."""
    conn = op.get_bind()
    op.add_column("vinculos_de_sessao", sa.Column("telefone", sa.String(16), nullable=True))
    for channel, chave, blob in conn.execute(
        text("SELECT channel, conversation_key, telefone_cifrado FROM vinculos_de_sessao")
    ).all():
        conn.execute(
            text("UPDATE vinculos_de_sessao SET telefone = :t WHERE channel = :c AND conversation_key = :k"),
            {"t": decrypt(bytes(blob), aad_do_vinculo(channel, chave)), "c": channel, "k": chave},
        )
    op.drop_index("ix_vinculos_de_sessao_telefone_indice", table_name="vinculos_de_sessao")
    op.drop_column("vinculos_de_sessao", "telefone_indice")
    op.drop_column("vinculos_de_sessao", "telefone_cifrado")
    op.alter_column("vinculos_de_sessao", "telefone", nullable=False)
    op.create_index("ix_vinculos_de_sessao_telefone", "vinculos_de_sessao", ["telefone"])

    chave_do_lead = get_settings().auditoria_chave_do_lead
    reindexar(
        conn, tabelas=_TABELAS, nova_chave=lambda _channel, valor: valor, modo="reversao",
        chave_do_lead_antiga=chave_do_lead, chave_do_lead_nova=chave_do_lead,
    )
    op.drop_table("identidades_de_lead")
```
Atenção à ordem na descida: `_mover` só recifra o telefone do vínculo se a coluna `telefone_cifrado` existir — na descida ela já foi removida antes do loop, e é isso que se quer (o telefone já voltou em claro).

- [ ] **Step 5: Guarda de tabelas** — `tests/unit/test_tabelas_com_chave_de_lead.py`:

```python
"""TEC-203, D3: toda tabela com `conversation_key` entra na reindexacao."""

import mobia.app.modelos  # noqa: F401 -- ver a nota abaixo
from mobia.domain.identidade.reindexacao import TABELAS_COM_CHAVE_DE_LEAD
from mobia.domain.messages.models import Base


def test_toda_tabela_com_conversation_key_esta_na_lista():
    com_chave = {t.name for t in Base.metadata.tables.values() if "conversation_key" in t.c}
    assert com_chave == set(TABELAS_COM_CHAVE_DE_LEAD)
```
Nota: o import da primeira linha precisa ser o módulo que registra **todos** os modelos no `Base.metadata` (procure o que `alembic/env.py` importa para `target_metadata` e use o mesmo). Exclua `identidades_de_lead` do conjunto esperado se ela aparecer (ela tem `conversation_key` mas é a própria identidade — acrescente-a num `- {"identidades_de_lead"}` com comentário).

- [ ] **Step 6: Teste de integração da migration** — `tests/integration/test_reindexacao_do_lead.py`. Siga o molde de `tests/integration/test_migrations.py` (fixture que faz `alembic downgrade 0060`, semeia em SQL cru, `alembic upgrade head` e garante o retorno ao head no teardown). Casos:

```python
TELEFONE = "5548999990000"
SEM_O_NOVE = "554899990000"


async def test_nenhuma_coluna_guarda_o_telefone_depois_da_subida(esquema_na_0060_semeado):
    """Semeia TELEFONE em messages (entrada e saida), lead_qualification,
    lead_score_audit, conversation_intent_audit, handoffs, optout_events,
    rate_limit_events (escopo numero) e um vinculo web com telefone TELEFONE;
    sobe; varre toda coluna de texto das tabelas de TABELAS_COM_CHAVE_DE_LEAD
    + rate_limit_events + vinculos e afirma que TELEFONE nao aparece."""


async def test_o_par_vira_chave_de_e_a_identidade_revela_o_cru(...):
    # conversation_key == chave_de("whatsapp", TELEFONE) em todas;
    # revelar(...) == TELEFONE; para SEM_O_NOVE, a chave e a de SEM_O_NOVE (distinta).


async def test_resumo_de_antes_continua_legivel(...):
    # semeia conversation_summaries.resumo cifrado com aad_do_resumo("whatsapp", TELEFONE);
    # depois da subida, ler_resumo(session, "whatsapp", chave_de(...)) devolve o texto.


async def test_evento_de_auditoria_de_antes_e_achado_pelo_lead(...):
    # registra evento com lead=("whatsapp", TELEFONE) antes; depois, montar_filtro com o par novo acha o evento.


async def test_trigger_de_imutabilidade_volta_ligada(...):
    # depois da subida, UPDATE lead_score_audit ... levanta (a trigger recusa).


async def test_rodar_a_reindexacao_de_novo_nao_muda_nada(...):
    # chama reindexar(modo="migracao") outra vez via run_sync; devolve 0 e o banco fica igual.


async def test_descida_devolve_os_valores_originais(...):
    # sobe, desce para 0060, e o conversation_key e o vinculo voltam a TELEFONE.
```
Escreva o corpo de cada um (SQL cru para semear, porque o esquema é o da 0060 e os modelos já são os novos). Acrescente `identidades_de_lead` a `TABELAS` em `tests/conftest.py` com um comentário de uma linha.

- [ ] **Step 7: Script de rotação** — `scripts/reindexar_leads.py`:

```python
"""Rotaciona a chave de indice do lead, ou a do `lead_ref`. TEC-203, D1/D3.

Roda com webhook e worker PARADOS: reescreve o `conversation_key` de ~20
tabelas, inclusive PK, numa transacao so. Ver `docs/seguranca/segredos.md`.

Chave de indice nova: ponha a nova em LEAD_INDICE_CHAVE (e LEAD_INDICE_CHAVE_ID)
e rode sem argumento. Chave do `lead_ref` nova: ponha a nova em
AUDITORIA_CHAVE_DO_LEAD, a velha em AUDITORIA_CHAVE_DO_LEAD_ANTERIOR, e rode.
"""

import asyncio
import os
import sys

from mobia.app.config import get_settings
from mobia.domain.identidade.indice import chave_de, indice_de_telefone
from mobia.domain.identidade.reindexacao import (
    TABELAS_COM_CHAVE_DE_LEAD,
    reindexar,
    reindexar_telefones_dos_vinculos,
)
from mobia.infra.db import dispose_engine, get_engine


async def _rodar() -> int:
    atual = get_settings().auditoria_chave_do_lead
    anterior = os.environ.get("AUDITORIA_CHAVE_DO_LEAD_ANTERIOR") or atual
    async with get_engine().begin() as conexao:
        mudados = await conexao.run_sync(
            lambda conn: reindexar(
                conn, tabelas=TABELAS_COM_CHAVE_DE_LEAD, nova_chave=chave_de, modo="rotacao",
                chave_do_lead_antiga=anterior, chave_do_lead_nova=atual,
            )
        )
        await conexao.run_sync(lambda conn: reindexar_telefones_dos_vinculos(conn, indice_de_telefone))
    await dispose_engine()
    print(f"{mudados} lead(s) reindexado(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_rodar()))
```
Acrescente um teste de integração: grava um lead pela migration com a chave A, troca `lead_indice_chave` para B (monkeypatch em `indice.get_settings`), roda `reindexar(modo="rotacao")` + `reindexar_telefones_dos_vinculos`, e afirma que a chave passa a ser `chave_de` sob B, que `revelar` ainda devolve o telefone e que o `telefone_indice` do vínculo é o de B.

- [ ] **Step 8: Rodar** — com `docker compose up -d`: `./.venv/Scripts/python.exe -m pytest tests/unit tests/integration/test_reindexacao_do_lead.py tests/integration/test_migrations.py --tb=short`. Expected: passa. (O resto da integração pode estar vermelho até a Task 10: a entrada ainda grava valor cru.)

- [ ] **Step 9: Gates e commit**

```bash
git add src alembic scripts tests
git commit -m "feat(TEC-203): o conversation_key vira HMAC e o telefone do lead passa a morar cifrado"
```

---

### Task 7: a entrada grava a chave e a identidade

**Files:**
- Modify: `src/mobia/domain/messages/service.py` (`IngestionService.ingest`, `IngestionService._persist`), `src/mobia/api/routes/widget.py`, `src/mobia/domain/identidade/repositorio.py`
- Test: `tests/integration/test_ingestao_cifra_o_remetente.py` (novo)

**Interfaces:**
- Consumes: `chave_de`, `indice_de_telefone`, `registrar` (Tasks 5–6).
- Produces: `vincular_sessao(session_factory, *, channel, conversation_key, telefone, message_id)` mantém a assinatura (cifra por dentro); `sessoes_vinculadas(session, telefone_indice: str, *, limite=None)` — o parâmetro muda de nome e de significado.

- [ ] **Step 1: Teste que falha**

```python
"""TEC-203: a ingestao grava a chave no lugar do remetente, e a identidade junto."""

from sqlalchemy import select

from mobia.domain.identidade.indice import chave_de, revelar
from mobia.domain.messages.models import Message
from mobia.domain.messages.service import IngestionService


async def test_mensagem_do_whatsapp_grava_a_chave_e_a_identidade(banco_limpo, session_factory, parsed_de):
    await IngestionService(session_factory, None).ingest([parsed_de("5548999990000")])
    async with session_factory() as session:
        linha = (await session.scalars(select(Message))).one()
        chave = chave_de("whatsapp", "5548999990000")
        assert linha.conversation_key == chave
        assert linha.sender_external_id == chave
        assert await revelar(session, "whatsapp", chave) == "5548999990000"
```
Use as fixtures de `tests/integration/test_ingestion_service.py` para montar o `ParsedMessage` e o `session_factory` (copie o helper se ele for local àquele arquivo). Acrescente um caso para o widget: sessão aberta, fala com telefone "meu número é 48 99999-0000" → `vinculos_de_sessao` tem `telefone_indice == indice_de_telefone("5548999990000")` e nenhuma coluna guarda o número (siga o molde dos testes existentes do widget — `grep -rln "vincular_sessao\|/widget" tests/integration`).

- [ ] **Step 2: Ver falhar.**

- [ ] **Step 3: `ingest`** — logo depois de `if not parsed: return []`, calcule as chaves uma vez e use-as no rate limit, no log e no evento:

```python
        # TEC-203. A chave do lead no lugar do remetente, em toda parte:
        # coluna, rate limit, log e evento. O remetente cru so existe aqui, na
        # memoria, e na identidade cifrada que `_persist` grava.
        chave_de_remetente = {
            item.provider_message_id: chave_de(channel, item.sender_external_id) for item in parsed
        }
        gravadas = await self._persist(parsed, channel, chave_de_remetente)
```
Remova `remetente_de` e troque as três leituras dele por `chave_de_remetente.get(provider_message_id, "")`.

- [ ] **Step 4: `_persist`** — nova assinatura `_persist(self, parsed, channel, chave_de_remetente: dict[str, str])`; em `valores`:

```python
                    "sender_external_id": chave_de_remetente[item.provider_message_id],
                    ...
                    # Quem fala e o lead, entao a conversa e a dele. Na saida
                    # sender e recipient se invertem e esta coluna nao.
                    "conversation_key": chave_de_remetente[item.provider_message_id],
```
e, dentro do `async with self._session_factory() as session:`, **antes** do `execute(statement)`:

```python
            # A identidade entra na mesma transacao das mensagens: chave gravada
            # sem identidade seria um lead a quem nao se consegue responder.
            for remetente in {item.sender_external_id for item in parsed}:
                await registrar(session, channel, remetente)
```
Atualize a docstring de `_persist` se ela descrever o que vai em `conversation_key`.

- [ ] **Step 5: `identidade/repositorio.py`**

`vincular_sessao`, valores:
```python
                .values(
                    channel=channel,
                    conversation_key=conversation_key,
                    telefone_cifrado=encrypt(telefone, aad_do_vinculo(channel, conversation_key)),
                    telefone_indice=indice_de_telefone(telefone),
                    message_id=message_id,
                )
```
`sessoes_vinculadas(session, telefone_indice: str, *, limite=None)` e `.where(VinculoDeSessao.telefone_indice == telefone_indice)`; docstring: "Os pares das sessoes cujo telefone tem este indice".

- [ ] **Step 6: `widget.py`** — em `chat`, logo depois de `sessao, retomada = identidade`:

```python
    # TEC-203. O servidor trata a sessao pela chave dela, como toda conversa;
    # o navegador segue recebendo a sessao crua, que e a credencial dele. A
    # central assina pelo mesmo `canal_da_sessao(chave)` em que `WebOutbound`
    # publica -- o `para` do payload e o `conversation_key`, que e a chave.
    chave = chave_de(CANAL_WEB, sessao)
```
Troque por `chave`: `central.abrir(sessao)` → `central.abrir(chave)`; `central.fechar(sessao, fila)` → `central.fechar(chave, fila)`; em `_anunciar`, `historico_da_sessao(..., sessao=sessao, ...)` → passe `chave` (acrescente o parâmetro `chave` a `_anunciar`; o frame `{"tipo": "sessao", "sessao": sessao}` continua com a sessão crua). Em `_ler_do_lead` e onde houver `registrar_consentimento(conversation_key=sessao)` e `vincular_sessao(conversation_key=sessao)`, use `chave_de(CANAL_WEB, sessao)` (calcule uma vez no começo da função). **Não mude** `ParsedMessage(sender_external_id=sessao, provider_message_id=_chave_do_id(sessao, ...))`: a ingestão faz o HMAC.

Confira com `grep -n "sessao" src/mobia/api/routes/widget.py` que nenhum uso de `sessao` como `conversation_key` ou chave da central ficou para trás.

- [ ] **Step 7: Rodar** — `./.venv/Scripts/python.exe -m pytest tests/unit tests/integration/test_ingestao_cifra_o_remetente.py --tb=short`.

- [ ] **Step 8: Gates e commit**

```bash
git add src tests
git commit -m "feat(TEC-203): a entrada grava a chave do lead e a identidade cifrada, nunca o remetente"
```

---

### Task 8: as bordas que precisam do telefone

**Files:**
- Modify: `src/mobia/domain/outbound/whatsapp.py::WhatsAppOutbound._deliver`, `src/mobia/domain/crm/payload.py::montar`, `src/mobia/workers/jobs/exportar_crm.py`, `src/mobia/domain/agendamento/mensagens.py` (`aviso_ao_corretor`, `aviso_de_cancelamento`), `src/mobia/domain/agendamento/confirmacao.py`, `src/mobia/domain/agendamento/cancelamento.py`, `src/mobia/domain/leads/repositorio.py`, `src/mobia/domain/identidade/absorcao.py::absorver_sessoes_vinculadas`, `src/mobia/admin/reativar.py`
- Test: `tests/integration/test_bordas_do_telefone.py` (novo) + ajustes nos testes existentes desses módulos

**Interfaces:**
- Consumes: `revelar`, `telefones_de`, `IdentidadeAusente`, `chave_de`, `indice_de_telefone`.
- Produces:
  - `montar(*, handoff_id, dossie, telefone: str | None, resumo, resumo_fallback)`, `VERSAO_DO_PAYLOAD = 2`, `lead.telefone` (`"+55..."` ou `None`).
  - `aviso_ao_corretor(..., lead: str, link)` e `aviso_de_cancelamento(..., lead: str, link)` no lugar de `channel`/`conversation_key`.
  - `mensagens.descrever_lead(channel: str, telefone: str | None) -> str`.

- [ ] **Step 1: Testes que falham** (`tests/integration/test_bordas_do_telefone.py`):

```python
async def test_envio_ao_whatsapp_vai_para_o_wa_id_cru(banco_limpo, session_factory, httpx_mock_ou_cliente_falso):
    # registra identidade de "554899990000" (sem o 9), manda via WhatsAppOutbound com
    # payload {"para": chave_de("whatsapp", "554899990000"), "de": "123", "texto": "oi"};
    # o corpo do POST tem "to": "554899990000".


async def test_envio_sem_identidade_nao_chama_a_meta(banco_limpo, session_factory, cliente_falso):
    # payload com "para" que nao tem identidade -> send levanta/retorna o caminho de
    # EnvioRecusado e o cliente falso nao recebeu POST nenhum.


async def test_busca_pelo_numero_com_o_nove_acha_wa_id_sem_o_nove(...):
    # lead WhatsApp "554899990000"; listar_leads com termo "(48) 99999-0000" o devolve.


async def test_busca_por_pedaco_do_numero_nao_acha(...):
    # termo "9999" nao devolve o lead (so numero completo, decisao da TEC-203).


async def test_listagem_mascara_o_telefone_revelado(...):
    # telefone == "+55 48 9****-**00"


async def test_revelar_devolve_o_telefone_das_duas_origens(...):
    # WhatsApp: "+5548999990000"; web com vinculo: o digitado; web sem vinculo: None.


async def test_absorcao_casa_sessao_web_com_o_whatsapp_do_mesmo_numero(...):
    # sessao web vinculada a "5548999990000"; absorver_sessoes_vinculadas no par WhatsApp
    # de "5548999990000" devolve o par da sessao.


async def test_payload_do_crm_leva_o_telefone(...):
    # montar(..., telefone="5548999990000") -> payload["lead"]["telefone"] == "+5548999990000",
    # payload["versao"] == 2.
```
Use os dublês que os testes existentes de cada módulo já usam (`grep -rln "WhatsAppOutbound(" tests`, `grep -rln "listar_leads" tests`, `grep -rln "absorver_sessoes_vinculadas" tests`).

- [ ] **Step 2: Ver falhar.**

- [ ] **Step 3: `WhatsAppOutbound._deliver`** — no começo do método:

```python
        # TEC-203. O `para` e a chave do lead; o `wa_id` cru sai da identidade
        # aqui, no ultimo instante, e so existe na memoria deste envio.
        try:
            async with self._session_factory() as session:
                destino = await revelar(session, CANAL_WHATSAPP, payload["para"])
        except IdentidadeAusente as exc:
            log.warning("outbound.identidade_ausente", message_id=str(message_id), kind=kind)
            # Permanente: tentar de novo nao cria a identidade que falta.
            raise EnvioRecusado("identidade ausente") from exc
```
e `"to": destino`. Confira que `_deliver` roda depois das guardas e da reserva (sim: `GuardedOutbound.send`) — a identidade ausente deixa a reserva, como toda `EnvioRecusado`.

- [ ] **Step 4: CRM** — `montar` ganha `telefone: str | None` e:

```python
        "lead": {
            "canal": dossie.canal,
            # Desde a v2 (TEC-203), `conversa` e o pseudonimo do lead, e nao
            # mais o telefone; quem precisa ligar le `telefone`.
            "conversa": dossie.conversa,
            "telefone": f"+{telefone}" if telefone else None,
            ...
```
`VERSAO_DO_PAYLOAD = 2` (o significado de `conversa` mudou — a regra das linhas de comentário acima da constante manda subir). Em `exportar_crm.py`, antes de `montar(`, obtenha `telefone = (await telefones_de(session, [(dossie.canal, dossie.conversa)]))[(dossie.canal, dossie.conversa)]` numa sessão (abra uma com o `session_factory` que o job já tem, se não houver sessão aberta ali).

- [ ] **Step 5: E-mails de agendamento** — em `mensagens.py`:

```python
def descrever_lead(channel: str, telefone: str | None) -> str:
    """A linha "Lead:" do e-mail ao corretor. TEC-203: o telefone revelado,
    porque o corretor precisa dele para a visita; o par ja nao o carrega."""
    return f"{channel} +{telefone}" if telefone else f"{channel} (sem telefone informado)"
```
Em `aviso_ao_corretor` e `aviso_de_cancelamento`, troque os parâmetros `channel: str, conversation_key: str` por `lead: str` e a linha por `linhas.append(f"Lead: {lead}")`. Nos chamadores (`confirmacao.py::_avisar_corretor` e `cancelamento.py`, perto de onde montam o `link`), obtenha o telefone com `telefones_de` numa sessão do `session_factory` e passe `lead=descrever_lead(channel, telefone)`. Atualize os testes existentes de `mensagens.py` (`grep -rln "aviso_ao_corretor\|aviso_de_cancelamento" tests`).

- [ ] **Step 6: Dashboard** — em `leads/repositorio.py`:

`_onde_a_busca_bate`:
```python
    digitos = _SO_DIGITOS.sub("", termo)
    canonico = normalizar(digitos) if digitos else None
    if canonico is not None:
        # TEC-203: so numero completo. O par guarda o HMAC do `wa_id` cru, e o
        # `wa_id` pode ter chegado sem o 9 -- dai as duas grafias.
        alvos.append(base.c.conversation_key.in_([chave_de(CANAL_WHATSAPP, g) for g in grafias_do_wa_id(canonico)]))
        alvos.append(
            select(VinculoDeSessao.channel)
            .where(
                VinculoDeSessao.channel == base.c.channel,
                VinculoDeSessao.conversation_key == base.c.conversation_key,
                VinculoDeSessao.telefone_indice == indice_de_telefone(canonico),
            )
            .exists()
        )
```
com, em `identidade/telefone.py`:
```python
def grafias_do_wa_id(canonico: str) -> tuple[str, ...]:
    """As formas em que a Meta pode entregar este numero. TEC-203.

    A Meta entrega parte dos celulares brasileiros sem o 9 (ver a docstring do
    modulo); a busca por telefone precisa das duas para achar o `wa_id`.
    """
    if len(canonico) == 13 and canonico[4] == "9":
        return (canonico, canonico[:4] + canonico[5:])
    return (canonico,)
```
(e um teste unitário dela em `tests/unit/`). Atualize a docstring de `_onde_a_busca_bate` (ela descreve busca por substring).

Listagem: remova `_telefone_da_sessao` e a coluna `telefone_da_sessao` de `_consulta`; em `listar_leads`, depois de `visiveis`:
```python
    telefones = await telefones_de(session, [(linha.channel, linha.conversation_key) for linha in visiveis])
```
e `telefone=mascarar_telefone(t) if (t := telefones[(linha.channel, linha.conversation_key)]) else None`. Reescreva o comentário "O telefone sai de duas origens" para dizer que `telefones_de` junta as duas.

`valor_revelado`:
```python
    if campo != CAMPO_TELEFONE:
        return None
    telefone = (await telefones_de(session, [par]))[par]
    return f"+{telefone}" if telefone else None
```

- [ ] **Step 7: Absorção** — em `absorver_sessoes_vinculadas`:

```python
    if channel != CANAL_WHATSAPP:
        return ()
    async with session_factory() as session:
        try:
            wa_id = await revelar(session, CANAL_WHATSAPP, conversation_key)
        except IdentidadeAusente:
            return ()
        telefone = normalizar(wa_id)
        if telefone is None:
            return ()
        pares = await sessoes_vinculadas(
            session, indice_de_telefone(telefone), limite=MAXIMO_DE_SESSOES_VINCULADAS
        )
        ...
```
(o resto da função continua dentro do mesmo `async with`).

- [ ] **Step 8: `admin/reativar.py`** — `--key` passa a ser o valor cru (telefone ou sessão), e `_executar` calcula `conversation_key=chave_de(channel, key)`. Atualize o help (`"telefone do lead (WhatsApp) ou sessao (web)"`) e a docstring do módulo.

- [ ] **Step 9: Varrer usos de valor cru que sobraram**

```bash
grep -rn "normalizar(.*conversation_key\|mascarar_telefone(.*conversation_key\|VinculoDeSessao.telefone\b\|\.telefone ==" src
```
Expected: nenhum resultado. Cada um que aparecer é um consumidor que tratava a chave como telefone — trate com `telefones_de`/`revelar`.

- [ ] **Step 10: Rodar** — `./.venv/Scripts/python.exe -m pytest tests/unit tests/integration/test_bordas_do_telefone.py --tb=short`.

- [ ] **Step 11: Gates e commit**

```bash
git add src tests
git commit -m "feat(TEC-203): so envio, CRM, e-mail ao corretor e dashboard revelam o telefone"
```

---

### Task 9: `recifrar` para aposentar uma chave do keyring

**Files:**
- Create: `src/mobia/admin/recifrar.py`, `scripts/recifrar.py`
- Test: `tests/unit/test_colunas_cifradas.py`, `tests/integration/test_recifrar.py` (novos)

**Interfaces:**
- Consumes: `id_da_chave`, `id_da_chave_ativa`, `encrypt_bytes`, `decrypt_bytes` (Task 4); AADs de `messages`, `context/models.py`, `handoff/models.py`, `usuarios/models.py`, `identidade/models.py`.
- Produces: `COLUNAS_CIFRADAS: tuple[ColunaCifrada, ...]`; `async recifrar(session_factory, *, lote: int = 500, so_contar: bool = False) -> dict[str, dict[int | None, int]]` — por coluna, quantos blobs há por id de chave (`None` = v1).

- [ ] **Step 1: Guarda de cobertura** — `tests/unit/test_colunas_cifradas.py`:

```python
"""TEC-203: toda coluna LargeBinary cifrada esta no `recifrar`, ou declara por que nao."""

from sqlalchemy import LargeBinary

import mobia.app.modelos  # noqa: F401 -- o mesmo import da guarda de tabelas (Task 6)
from mobia.admin.recifrar import COLUNAS_CIFRADAS
from mobia.domain.messages.models import Base

# LargeBinary que NAO e cifrado. Cada entrada diz por que.
NAO_CIFRADAS = {
    ("imoveis", "arquivo"),  # ajuste ao nome real: o arquivo do catalogo, que e dado publico
}


def test_toda_coluna_binaria_esta_coberta():
    binarias = {
        (t.name, c.name)
        for t in Base.metadata.tables.values()
        for c in t.c
        if isinstance(c.type, LargeBinary)
    }
    cobertas = {(c.tabela, c.coluna) for c in COLUNAS_CIFRADAS}
    assert binarias == cobertas | NAO_CIFRADAS
```
(Descubra o nome real da tabela/coluna do catálogo com `grep -rn "LargeBinary" src/mobia/domain/*/models.py`.)

- [ ] **Step 2: `src/mobia/admin/recifrar.py`**

```python
"""Reescreve todo blob de outra chave com a chave ativa. TEC-203, D1.

E o passo que permite TIRAR uma chave do keyring. Roda com o servico de pe:
cada lote e uma transacao curta, e uma linha recifrada no meio de uma leitura
continua decifravel pelas duas chaves enquanto as duas estiverem no keyring.

**Nao cobre os arquivos de midia** (`.midias/` ou S3, TEC-132). Enquanto houver
midia gravada sob uma chave, ela fica no keyring -- ver o spec da TEC-203.
"""

import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.context.models import aad_do_resumo
from mobia.domain.handoff.models import aad_do_resumo_de_handoff
from mobia.domain.identidade.models import aad_da_identidade, aad_do_vinculo
from mobia.domain.usuarios.models import aad_do_totp
from mobia.infra.crypto import aad_de, decrypt_bytes, encrypt_bytes, id_da_chave, id_da_chave_ativa


@dataclass(frozen=True)
class ColunaCifrada:
    tabela: str
    chave_primaria: tuple[str, ...]
    coluna: str
    aad: Callable[..., str]


COLUNAS_CIFRADAS = (
    ColunaCifrada("messages", ("id",), "text_body", lambda i: aad_de(i, "text_body")),
    ColunaCifrada("messages", ("id",), "raw_payload", lambda i: aad_de(i, "raw_payload")),
    ColunaCifrada("messages", ("id",), "envelope_context", lambda i: aad_de(i, "envelope_context")),
    ColunaCifrada("conversation_summaries", ("channel", "conversation_key"), "resumo", aad_do_resumo),
    ColunaCifrada("handoffs", ("id",), "resumo", aad_do_resumo_de_handoff),
    ColunaCifrada("usuarios", ("id",), "totp_segredo", aad_do_totp),
    ColunaCifrada("identidades_de_lead", ("channel", "conversation_key"), "valor_cifrado", aad_da_identidade),
    ColunaCifrada("vinculos_de_sessao", ("channel", "conversation_key"), "telefone_cifrado", aad_do_vinculo),
)


async def recifrar(
    session_factory: async_sessionmaker[AsyncSession], *, lote: int = 500, so_contar: bool = False
) -> dict[str, dict[int | None, int]]:
    ativa = id_da_chave_ativa()
    if ativa is None and not so_contar:
        raise RuntimeError("keyring vazio: nao ha chave ativa para onde recifrar")
    relatorio: dict[str, dict[int | None, int]] = {}
    for alvo in COLUNAS_CIFRADAS:
        contagem: Counter[int | None] = Counter()
        pk = ", ".join(alvo.chave_primaria)
        ultimo: tuple[object, ...] | None = None
        while True:
            async with session_factory() as session:
                depois = f"WHERE ({pk}) > :ultimo" if ultimo is not None else ""
                linhas = (
                    await session.execute(
                        text(
                            f"SELECT {pk}, {alvo.coluna} FROM {alvo.tabela} {depois} "
                            f"ORDER BY {pk} LIMIT :lote"
                        ),
                        {"lote": lote, **({"ultimo": ultimo} if ultimo is not None else {})},
                    )
                ).all()
                if not linhas:
                    break
                for linha in linhas:
                    *chaves, blob = linha
                    ultimo = tuple(chaves)
                    if blob is None:
                        continue
                    atual = id_da_chave(bytes(blob))
                    if so_contar or atual == ativa:
                        contagem[atual] += 1
                        continue
                    aad = alvo.aad(*chaves)
                    novo = encrypt_bytes(decrypt_bytes(bytes(blob), aad), aad)
                    onde = " AND ".join(f"{c} = :pk{n}" for n, c in enumerate(alvo.chave_primaria))
                    await session.execute(
                        text(f"UPDATE {alvo.tabela} SET {alvo.coluna} = :novo WHERE {onde}"),
                        {"novo": novo, **{f"pk{n}": v for n, v in enumerate(chaves)}},
                    )
                    contagem[ativa] += 1
                await session.commit()
        relatorio[f"{alvo.tabela}.{alvo.coluna}"] = dict(contagem)
    return relatorio
```
Se a comparação de tupla `({pk}) > :ultimo` não aceitar bind de tupla no asyncpg, gere um bind por coluna (`(a, b) > (:u0, :u1)`). Confira o tipo de `id` de cada tabela (UUID) e o nome real das colunas (`envelope_context`, `totp_segredo`, `resumo`) contra os modelos.

`scripts/recifrar.py`: `argparse` com `--so-contar`; chama `recifrar(get_sessionmaker(), so_contar=...)`, imprime o relatório por coluna e termina com uma linha `blobs fora da chave ativa: N`.

- [ ] **Step 3: Teste de integração** — `tests/integration/test_recifrar.py`: grava uma mensagem sob a chave A (keyring `{A}`, ativa A), passa para keyring `{A, B}` ativa B, roda `recifrar`, afirma que `id_da_chave` do `text_body` é B e que ele decifra; e que, depois, keyring `{B}` sozinho ainda decifra.

- [ ] **Step 4: Rodar, gates e commit**

```bash
git add src/mobia/admin/recifrar.py scripts/recifrar.py tests
git commit -m "feat(TEC-203): recifrar reescreve com a chave ativa o que ainda esta sob outra"
```

---

### Task 10: a suíte existente conversa com a chave

**Files:** testes em `tests/` que quebraram com a mudança de semântica.

- [ ] **Step 1: Rodar por blocos, com diagnóstico**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short -q -p no:randomly
./.venv/Scripts/python.exe -m pytest tests/features --tb=short -q
```
Guarde a lista de falhas.

- [ ] **Step 2: Classificar cada falha** em uma de três:
  1. **Teste que ingere um telefone e consulta por ele** (`conversation_key == "5511..."` depois de passar por `IngestionService`/webhook/widget) → passa a consultar por `chave_de(channel, "5511...")`.
  2. **Teste que afirma o `to` ou o `para` enviado** → `para` é a chave; o `to` HTTP é o cru (só no teste do `WhatsAppOutbound`).
  3. **Qualquer outra coisa** → é possível regressão: investigue com superpowers:systematic-debugging antes de mexer no teste. Não "conserte" teste que denuncia defeito.

  Falhas com `ConnectionResetError`/`CannotConnectNowError`/`[WinError 64]` não são desta card — ver `CLAUDE.md`, rode o arquivo sozinho.

- [ ] **Step 3: Ajustar os testes de categoria 1 e 2**, arquivo por arquivo. Para fixtures que semeiam o par direto no banco e só o leem de volta, **não mude nada**: a chave é opaca e o teste continua válido.

- [ ] **Step 4: Rodar os três blocos de novo.** Expected: tudo verde, ou só falhas ambientais documentadas.

- [ ] **Step 5: Gates e commit** — um commit por grupo coerente, cada um dizendo no corpo por que o teste mudou:

```bash
git commit -m "test(TEC-203): testes que entram pela ingestao consultam pela chave do lead"
```

---

### Task 11: runbook, emendas, docstrings e verificação final

**Files:**
- Create: `docs/seguranca/segredos.md`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (emendas aninhadas), `alembic/versions/0012_auditoria_de_score.py`, `0035_auditoria_de_intencao.py`, `0053_eventos_auditoria.py` (docstring), `src/mobia/domain/auditoria/referencia.py` (docstring), `src/mobia/domain/limites/models.py` (comentário de `chave`), `app/logging.py` (se o comentário de `_CHAVES_MASCARADAS` disser que `conversation_key` é telefone), `docs/superpowers/specs/2026-09-26-tec-203-cifra-e-segredos-design.md` (status)

- [ ] **Step 1: `docs/seguranca/segredos.md`** — com acento, para quem opera. Seções: *Quais segredos existem* (tabela: nome, função, onde vive em produção, como gerar — copie os comandos dos validators); *Como chegam à aplicação* (env ou `MOBIA_SECRETS_DIR`; `.env` não é lido em produção); *Rotação a cada 90 dias* com um procedimento por tipo: keyring (acrescentar, ativar, `scripts/recifrar.py`, remover quando o relatório der zero, mídia fica), chave de índice (parar webhook e worker, trocar `LEAD_INDICE_CHAVE`/`_ID`, `python scripts/reindexar_leads.py`, subir), chave do `lead_ref` (idem, com `AUDITORIA_CHAVE_DO_LEAD_ANTERIOR`), JWT (troca derruba sessões), tokens de terceiros (no provedor); *O aviso `seguranca.rotacao_vencida`*; *Branch protection* — o comando para tornar `Segredos` required check:

```bash
gh api -X POST repos/durexex-Inc/<repo>/branches/main/protection/required_status_checks/contexts -f 'contexts[]=Segredos'
```
(o Eduardo roda; confira o nome do repo com `gh repo view --json nameWithOwner`).

- [ ] **Step 2: Emendas ao SRS** — aninhadas, sem reescrever o texto original, no formato do `CLAUDE.md`:
  - abaixo da Emenda E-01 (a do Corretor): `Emenda E-nn (TEC-203, 26/09/2026)`: a doutrina "cifra-se conteúdo, nunca identificador" deixa de valer para o telefone do lead, que passa a morar cifrado com blind index; corretor e usuário seguem em claro.
  - abaixo do RNF-13: TLS com terceiros tem piso negociado, não 1.3 forçado; Redis exige TLS com certificado verificado, sem piso de versão (limite do ARQ 0.28).
  - abaixo do RNF-14: a chave de índice rotaciona por reindexação com o serviço parado; o `lead_ref` rotaciona com a chave anterior; mídia não é recifrada.
  Use o próximo número de emenda livre em cada regra (leia a regra antes).

- [ ] **Step 3: Docstrings que a card tornou falsas**
  - 0012, 0035, 0053: acrescente um parágrafo "**Exceção (TEC-203):** a reindexação do lead desliga esta trigger na própria transação para trocar o pseudônimo do lead — ver `domain/identidade/reindexacao.py`."
  - `referencia.py`: a chave "não pode rodar" → pode, pelo `scripts/reindexar_leads.py` com `AUDITORIA_CHAVE_DO_LEAD_ANTERIOR`. E o parágrafo de abertura ("No WhatsApp, `conversation_key` E o telefone") passa ao passado, dizendo o que é hoje.
  - `limites/models.py`, comentário de `chave`: no escopo `numero` passa a ser a chave do lead; o número se recupera pela identidade.
  - Rode `grep -rn "conversation_key.*telefone\|e o telefone\|E o telefone" src alembic` e releia cada comentário que afirmar que o `conversation_key` é o telefone.

- [ ] **Step 4: Listagem de comentários**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
```
Releia cada `ALTERADO` e `VIZINHO`; corrija o que o código desmente. `--checar` deve sair 0.

- [ ] **Step 5: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 6: gitleaks sobre a branch** — `<scratchpad>/gitleaks.exe git --config .gitleaks.toml --redact --log-opts="origin/main..HEAD" .` Expected: `no leaks found`.

- [ ] **Step 7: Suíte inteira UMA vez** — `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short`; se o Postgres cair, por blocos (Task 10, Step 1). Guarde hash e resultado.

- [ ] **Step 8: Status do spec** — `**Status:** implementado, PR aberto`.

- [ ] **Step 9: Commit**

```bash
git add docs src alembic
git commit -m "docs(TEC-203): runbook de segredos, emendas ao SRS e docstrings que a cifra tornou falsas"
```

# TEC-344 — Embed do chat: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma linha de `<script>` no site da imobiliária desenha um botão com a cor, a posição e o nome configurados, e no primeiro clique abre `/embed/chat` num iframe; nenhuma falha vira erro de JS no site.

**Architecture:** O backend ganha dois campos na configuração versionada do agente e um endpoint público `GET /widget/aparencia/{slug}` conferido contra `TENANT_SLUG`. O Next ganha o route handler `/embed/aparencia` (CORS `*`, cache de 60 s), a página `/embed/chat` e a CSP `frame-ancestors *` em `/embed/*`. O loader é JavaScript puro em `frontend/public/widget.js`, sem build, com gate de 5 KB gzip no CI.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (Python 3.13); Next.js 16 App Router + React 19; Vitest 5 + jsdom + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-27-tec-344-embed-do-chat-design.md` — leia antes de qualquer task; as decisões D1–D9 e as lacunas L1–L5 são citadas por número abaixo.

## Global Constraints

- Comentários e docstrings em `src/`, `tests/` e `frontend/src/`: português **sem acento**. Texto que o visitante lê: **com acento** (CLAUDE.md, TEC-267). Valor citado em comentário segue o valor.
- Commits: `tipo(TEC-344): o que passou a ser verdade`, assunto sem acento, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Gates Python antes de cada commit que toque `.py`: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy` (sem argumento).
- Gates frontend antes de cada commit que toque `frontend/`: `npm run lint` e `npm test`, dentro de `frontend/`.
- Loader: **≤ 5120 bytes gzip**, sem dependências, sem etapa de build, ES2019 (o `catch {}` sem variável é o que puxa de ES2017 para ES2019: `catch (_)` reprova no `no-unused-vars` do ESLint).
- Formato do JSON de aparência, igual em toda a cadeia (API → route handler → loader): `{"nomeDoAssistente": string | null, "corPrimaria": "#RRGGBB", "posicaoDoBotao": "DIREITA" | "ESQUERDA"}`.
- Cor válida: `^#[0-9A-Fa-f]{6}$`. Padrão: `#1D4ED8`. Posição padrão: `DIREITA`.
- Nome exibido quando `nomeDoAssistente` é nulo: `Assistente virtual`.
- Tempos do loader: aparência em até **5000 ms**; `mobia:pronto` em até **10000 ms**.
- Código se cita em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha (TEC-299; `comentarios_tocados.py --checar` reprova).

## Review Focus

1. **`posicaoDoBotao` com nome de propriedade herdada** (`"constructor"`, `"toString"`) — o loader tem de recusar, e não tratar a função herdada como lado válido. Teste na Task 7.
2. **Snippet colado duas vezes, ou loader carregado de novo por um SPA** — um botão só. Teste na Task 7.
3. **`postMessage` com `tipo: 'mobia:pronto'` vindo de outra origem ou de outra janela** — ignorado; o prazo de 10 s continua valendo. Teste na Task 7.
4. **`tenant` com barra, ponto ou maiúscula** (`../../health`, `A`) — o Next não monta caminho de API com ele; responde 404 sem chamar o FastAPI. Teste na Task 5.
5. **Cor com canal alfa ou sem `#`** (`#0A7F5AFF`, `0A7F5A`) — recusada em `validar()` e no loader. Testes nas Tasks 1 e 7.

---

### Task 1: Cor primária e posição do botão no domínio

**Files:**
- Modify: `src/mobia/domain/configuracao/vigente.py`
- Test: `tests/unit/test_configuracao_do_agente.py`

**Interfaces:**
- Produces: `PosicaoDoBotao` (StrEnum `DIREITA`/`ESQUERDA`), `COR_PRIMARIA_PADRAO = "#1D4ED8"`, campos `ConfiguracaoDoAgente.cor_primaria: str` e `ConfiguracaoDoAgente.posicao_do_botao: PosicaoDoBotao`, ambos com padrão; `validar()` recusa cor fora de `#RRGGBB` com a mensagem `cor primaria ... nao e #RRGGBB` e posição desconhecida com `posicao do botao ... desconhecida`.

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/unit/test_configuracao_do_agente.py`, acrescente `COR_PRIMARIA_PADRAO` e `PosicaoDoBotao` ao import de `mobia.domain.configuracao.vigente`, acrescente ao `parametrize` de `test_fora_da_faixa_e_recusado`, depois das linhas da TEC-191:

```python
        # TEC-344, D1.
        ({"cor_primaria": "0A7F5A"}, "nao e #RRGGBB"),
        ({"cor_primaria": "#0A7F5"}, "nao e #RRGGBB"),
        ({"cor_primaria": "#0A7F5AFF"}, "nao e #RRGGBB"),
        ({"cor_primaria": "red"}, "nao e #RRGGBB"),
        ({"posicao_do_botao": "CIMA"}, "posicao do botao 'CIMA' desconhecida"),
```

E, depois de `test_orcamento_nulo_e_o_padrao_e_e_aceito`:

```python
def test_a_aparencia_padrao_e_botao_a_direita_na_cor_neutra() -> None:
    """TEC-344, D1: antes desta card nao havia botao, entao o padrao nao
    preserva comportamento nenhum -- so precisa ser valido."""
    config = padrao()

    assert config.cor_primaria == COR_PRIMARIA_PADRAO == "#1D4ED8"
    assert config.posicao_do_botao is PosicaoDoBotao.DIREITA
    assert validar(config) == config


def test_cor_e_posicao_do_tenant_sao_aceitas() -> None:
    config = validar(
        aplicar(
            padrao(), {"cor_primaria": "#0a7f5a", "posicao_do_botao": PosicaoDoBotao.ESQUERDA}
        )
    )

    assert config.cor_primaria == "#0a7f5a"
    assert config.posicao_do_botao is PosicaoDoBotao.ESQUERDA
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_configuracao_do_agente.py --tb=short -q`
Expected: FAIL na importação (`cannot import name 'COR_PRIMARIA_PADRAO'`).

- [ ] **Step 3: Implementar**

Em `vigente.py`, acrescente `import re` aos imports e, logo depois de `class Tom`:

```python
class PosicaoDoBotao(StrEnum):
    """Em que canto do site o botao do chat fica (TEC-344, D1)."""

    DIREITA = "DIREITA"
    ESQUERDA = "ESQUERDA"


# TEC-344, D1. Neutra e com contraste para o icone branco. Nao preserva
# comportamento nenhum -- antes desta card nao havia botao --, e por isso nao
# vem de constante antiga como o resto de `padrao()`.
COR_PRIMARIA_PADRAO = "#1D4ED8"
```

Em `ConfiguracaoDoAgente`, depois de `orcamento_mensal_usd`:

```python
    # TEC-344, D1. A aparencia do botao do chat web no site da imobiliaria.
    cor_primaria: str = COR_PRIMARIA_PADRAO
    posicao_do_botao: PosicaoDoBotao = PosicaoDoBotao.DIREITA
```

Junto dos limites (depois de `ORCAMENTO_MAXIMO`):

```python
# TEC-344, D1. Seis digitos e nada mais: sem alfa, sem forma curta, sem nome de
# cor. E o formato que o loader confere de novo antes de desenhar, e o `CHECK`
# da `0064` repete no banco.
_COR_PRIMARIA = re.compile(r"#[0-9A-Fa-f]{6}")
```

Em `validar()`, antes de `if erros:`:

```python
    if not _COR_PRIMARIA.fullmatch(config.cor_primaria):
        erros.append(f"cor primaria {config.cor_primaria!r} nao e #RRGGBB")
    if config.posicao_do_botao not in tuple(PosicaoDoBotao):
        erros.append(f"posicao do botao {config.posicao_do_botao!r} desconhecida")
```

Atenção: `{config.posicao_do_botao!r}` de uma string crua `"CIMA"` sai `'CIMA'`, que é o que o teste casa.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_configuracao_do_agente.py --tb=short -q`
Expected: PASS.

- [ ] **Step 5: Gates e commit**

Rode os três gates Python. Depois:

```bash
git add src/mobia/domain/configuracao/vigente.py tests/unit/test_configuracao_do_agente.py
git commit -m "feat(TEC-344): a configuracao do agente tem cor primaria e posicao do botao"
```

---

### Task 2: Os campos novos na tabela de versões e na API do admin

**Files:**
- Create: `alembic/versions/0064_aparencia_do_chat_web.py`
- Modify: `src/mobia/domain/configuracao/models.py`, `src/mobia/domain/configuracao/repositorio.py`, `src/mobia/api/routes/configuracao.py`
- Test: `tests/features/test_configurar_o_agente.py`

**Interfaces:**
- Consumes: `PosicaoDoBotao`, `COR_PRIMARIA_PADRAO` (Task 1).
- Produces: colunas `cor_primaria`/`posicao_do_botao`; `como_plano()` devolve `"cor_primaria": str` e `"posicao_do_botao": "DIREITA" | "ESQUERDA"`; `GET`/`PATCH /api/v1/configuracao/agente` com `corPrimaria` e `posicaoDoBotao`.

- [ ] **Step 1: Confirmar a cabeça atual das migrations**

Run: `grep -n "^revision\|^down_revision" alembic/versions/0063_solicitacoes_de_titular.py`
Expected: `revision = "0063"`. Se houver `0064` na `main`, renumere esta para a seguinte e ajuste `down_revision`.

- [ ] **Step 2: Escrever os testes que falham**

Em `tests/features/test_configurar_o_agente.py`, no fim do arquivo:

```python
# --- TEC-344: a aparencia do chat web ------------------------------------------


async def test_cor_e_posicao_do_botao_se_gravam_e_se_leem(
    client: AsyncClient, banco_limpo: None
) -> None:
    antes = (await client.get(ROTA, headers=_bearer())).json()
    assert antes["configuracao"]["corPrimaria"] == "#1D4ED8"
    assert antes["configuracao"]["posicaoDoBotao"] == "DIREITA"
    assert antes["limites"]["posicaoDoBotao"] == {"valores": ["DIREITA", "ESQUERDA"]}

    resposta = await client.patch(
        ROTA, json={"corPrimaria": "#0A7F5A", "posicaoDoBotao": "ESQUERDA"}, headers=_bearer()
    )

    assert resposta.status_code == 200, resposta.text
    assert sorted(resposta.json()["alterados"]) == ["corPrimaria", "posicaoDoBotao"]
    depois = (await client.get(ROTA, headers=_bearer())).json()["configuracao"]
    assert (depois["corPrimaria"], depois["posicaoDoBotao"]) == ("#0A7F5A", "ESQUERDA")


@pytest.mark.parametrize(
    "pedido",
    [
        {"corPrimaria": "#0A7F5AFF"},
        {"corPrimaria": None},
        {"posicaoDoBotao": None},
    ],
)
async def test_aparencia_invalida_e_recusada_e_nada_se_grava(
    client: AsyncClient, banco_limpo: None, pedido: dict[str, object]
) -> None:
    resposta = await client.patch(ROTA, json=pedido, headers=_bearer())

    assert resposta.status_code == 422, resposta.text
    historico = (await client.get(f"{ROTA}/historico", headers=_bearer())).json()
    assert historico["itens"] == []


async def test_posicao_fora_do_vocabulario_e_recusada_na_borda(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.patch(ROTA, json={"posicaoDoBotao": "CIMA"}, headers=_bearer())

    assert resposta.status_code == 422, resposta.text
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_configurar_o_agente.py --tb=short -q -k "aparencia or cor_e_posicao or posicao_fora"`
Expected: FAIL com `KeyError: 'corPrimaria'` (e o `PATCH` com campo extra levando 422 pelo `extra="forbid"`). Exige `docker compose up -d`.

- [ ] **Step 4: Migration**

`alembic/versions/0064_aparencia_do_chat_web.py`:

```python
"""a aparencia do chat web entra na configuracao do agente

TEC-344, D1 do desenho. Duas colunas em `configuracoes_do_agente`: a cor
primaria do botao e o canto do site em que ele fica. **Nao nulas, com o
padrao da aplicacao nas linhas que ja existem**: ao contrario do orcamento da
`0060`, aqui "nenhum" nao e valor legitimo -- o botao sempre tem uma cor e um
lado --, e o padrao e exatamente o que essas versoes passam a valer.

Os CHECKs repetem `vigente.validar` para quem grava por fora da rota.

Revision ID: 0064
Revises: 0063
"""

import sqlalchemy as sa

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracoes_do_agente",
        sa.Column("cor_primaria", sa.String(7), nullable=False, server_default="#1D4ED8"),
    )
    op.add_column(
        "configuracoes_do_agente",
        sa.Column("posicao_do_botao", sa.String(8), nullable=False, server_default="DIREITA"),
    )
    op.create_check_constraint(
        "ck_configuracoes_do_agente_cor",
        "configuracoes_do_agente",
        "cor_primaria ~ '^#[0-9A-Fa-f]{6}$'",
    )
    op.create_check_constraint(
        "ck_configuracoes_do_agente_posicao",
        "configuracoes_do_agente",
        "posicao_do_botao IN ('DIREITA', 'ESQUERDA')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_configuracoes_do_agente_posicao", "configuracoes_do_agente", type_="check")
    op.drop_constraint("ck_configuracoes_do_agente_cor", "configuracoes_do_agente", type_="check")
    op.drop_column("configuracoes_do_agente", "posicao_do_botao")
    op.drop_column("configuracoes_do_agente", "cor_primaria")
```

- [ ] **Step 5: Modelo e repositório**

Em `models.py`, depois de `orcamento_mensal_usd`:

```python
    # TEC-344, D1. A aparencia do botao do chat web. Nao nulas: o botao sempre
    # tem cor e lado, e a `0064` preencheu as linhas antigas com o padrao.
    cor_primaria: Mapped[str] = mapped_column(String(7), nullable=False)
    posicao_do_botao: Mapped[str] = mapped_column(String(8), nullable=False)
```

Em `repositorio.py`, importe `PosicaoDoBotao` junto de `Pesos, Tom, padrao`; em `_da_linha`, depois de `orcamento_mensal_usd=...`:

```python
        cor_primaria=linha.cor_primaria,
        posicao_do_botao=PosicaoDoBotao(linha.posicao_do_botao),
```

Em `como_plano`, depois de `"orcamento_mensal_usd": ...`:

```python
        "cor_primaria": config.cor_primaria,
        # `PosicaoDoBotao(...)` e nao `.value` direto: `aplicar` aceita a
        # string crua, e `validar` a deixa passar se for um dos dois valores.
        "posicao_do_botao": PosicaoDoBotao(config.posicao_do_botao).value,
```

- [ ] **Step 6: A rota do admin**

Em `api/routes/configuracao.py`: importe `PosicaoDoBotao` junto de `ConfiguracaoInvalida, Tom`. Em `_CAMPOS`, depois de `orcamentoMensalUsd`:

```python
    "corPrimaria": "cor_primaria",
    "posicaoDoBotao": "posicao_do_botao",
```

Em `_LIMITES`, no fim:

```python
    # TEC-344, D1. O formato e conferido em `vigente.validar`.
    "corPrimaria": {"formato": "#RRGGBB"},
    "posicaoDoBotao": {"valores": [p.value for p in PosicaoDoBotao]},
```

Em `PedidoDeAlteracao`, no fim:

```python
    corPrimaria: str | None = None  # noqa: N815
    posicaoDoBotao: PosicaoDoBotao | None = None  # noqa: N815
```

Em `_mudancas`, no laço, depois do ramo de `tom`:

```python
        elif coluna == "posicao_do_botao" and valor is not None:
            valor = PosicaoDoBotao(valor)
```

E depois do `if "cadencia" in mudancas ...`:

```python
    # TEC-344, D1. Ao contrario do nome e do orcamento, "nenhum" nao e valor
    # legitimo aqui: o botao sempre tem cor e lado.
    if mudancas.get("cor_primaria", "") is None or mudancas.get("posicao_do_botao", "") is None:
        raise ConfiguracaoInvalida("cor primaria e posicao do botao nao podem ser nulas")
```

- [ ] **Step 7: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_configurar_o_agente.py tests/unit/test_configuracao_do_agente.py tests/unit/test_uma_cabeca_de_migration.py tests/features/test_painel_de_custo.py --tb=short -q`
Expected: PASS. Se `relation`/`column ... does not exist` aparecer em massa, é o banco de teste com carimbo adiantado — ver "`relation ... does not exist`" no CLAUDE.md antes de mexer em código.

- [ ] **Step 8: Gates e commit**

```bash
git add alembic/versions/0064_aparencia_do_chat_web.py src/mobia/domain/configuracao/models.py src/mobia/domain/configuracao/repositorio.py src/mobia/api/routes/configuracao.py tests/features/test_configurar_o_agente.py
git commit -m "feat(TEC-344): o admin grava e le a cor e a posicao do botao do chat"
```

---

### Task 3: O endpoint público de aparência, conferido contra `TENANT_SLUG`

**Files:**
- Create: `src/mobia/api/routes/aparencia_do_widget.py`
- Modify: `src/mobia/app/config.py`, `src/mobia/app/main.py`, `src/mobia/api/autorizacao.py`, `.env.example`
- Test: `tests/features/test_aparencia_do_widget.py`

**Interfaces:**
- Consumes: `configuracao_vigente`, `PosicaoDoBotao` (Tasks 1–2).
- Produces: `Settings.tenant_slug: str | None` (env `TENANT_SLUG`); `GET /widget/aparencia/{slug}` → `200 {"nomeDoAssistente", "corPrimaria", "posicaoDoBotao"}` ou `404 {"detail": "nao encontrado"}`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/features/test_aparencia_do_widget.py`:

```python
"""A aparencia do chat web, lida sem autenticacao. TEC-344, D2 e D3 do desenho.

O loader do site a pede antes de desenhar o botao. O slug do snippet tem de
bater com `TENANT_SLUG`; sem ele configurado, nenhum slug bate.
"""

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from mobia.app.config import get_settings
from mobia.domain.usuarios import tokens

SLUG = "imobiliaria-x"


def _bearer_admin() -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), "ADMIN", mfa=True, corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def com_slug(monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None) -> Iterator[None]:
    monkeypatch.setenv("TENANT_SLUG", SLUG)
    get_settings.cache_clear()
    yield


async def test_devolve_a_aparencia_padrao_sem_credencial(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    resposta = await client.get(f"/widget/aparencia/{SLUG}")

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "nomeDoAssistente": None,
        "corPrimaria": "#1D4ED8",
        "posicaoDoBotao": "DIREITA",
    }


async def test_devolve_o_que_o_admin_configurou(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """Cenario 3 do Gherkin, do lado do backend."""
    await client.patch(
        "/api/v1/configuracao/agente",
        json={"nomeDoAssistente": "Lia", "corPrimaria": "#0A7F5A", "posicaoDoBotao": "ESQUERDA"},
        headers=_bearer_admin(),
    )

    resposta = await client.get(f"/widget/aparencia/{SLUG}")

    assert resposta.json() == {
        "nomeDoAssistente": "Lia",
        "corPrimaria": "#0A7F5A",
        "posicaoDoBotao": "ESQUERDA",
    }


async def test_so_devolve_os_tres_campos_da_aparencia(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """D3: tom, pesos, cadencia e orcamento sao do admin e nao saem daqui."""
    corpo = (await client.get(f"/widget/aparencia/{SLUG}")).json()

    assert set(corpo) == {"nomeDoAssistente", "corPrimaria", "posicaoDoBotao"}


async def test_slug_errado_e_slug_nao_configurado_dao_o_mesmo_404(
    client: AsyncClient,
    banco_limpo: None,
    monkeypatch: pytest.MonkeyPatch,
    caches_de_cliente_limpos: None,
) -> None:
    """D3: responder diferente diria a quem sonda se existe algum tenant."""
    # Vazio, e nao `delenv`: fora de producao o `Settings` le o `.env`, e um
    # `TENANT_SLUG` la dentro voltaria pela porta dos fundos.
    monkeypatch.setenv("TENANT_SLUG", "")
    get_settings.cache_clear()
    sem_slug = await client.get(f"/widget/aparencia/{SLUG}")

    monkeypatch.setenv("TENANT_SLUG", SLUG)
    get_settings.cache_clear()
    errado = await client.get("/widget/aparencia/outra-imobiliaria")

    assert sem_slug.status_code == errado.status_code == 404
    assert sem_slug.json() == errado.json()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_aparencia_do_widget.py --tb=short -q`
Expected: FAIL com 404 no primeiro teste (a rota não existe) — o de 404 pode passar por acaso, e está certo.

- [ ] **Step 3: O setting**

Em `src/mobia/app/config.py`, depois de `tamanho_maximo_do_texto_do_widget`:

```python
    # TEC-344, D2. O slug que o `data-tenant` do snippet do site tem de trazer
    # para `GET /widget/aparencia/{slug}` responder. **Nulo por padrao, e nulo
    # quer dizer que nenhum slug casa**: um ambiente que esqueceu a variavel
    # fica sem botao, e nao com um botao que aceita qualquer valor. Tenant unico
    # na POC (PR-03); o multi-tenant troca a comparacao por uma busca.
    tenant_slug: str | None = None
```

Em `.env.example`, acrescente no fim (com o comentário no estilo do arquivo):

```
# TEC-344: o data-tenant do snippet do chat web. Vazio, nenhum site mostra o botao.
TENANT_SLUG=
```

Atenção: `TENANT_SLUG=` vazio chega como `""`, não `None`. A comparação da Step 4 trata `""` como não configurado.

- [ ] **Step 4: A rota**

`src/mobia/api/routes/aparencia_do_widget.py`:

```python
"""A aparencia do chat web, para o loader do site. TEC-344, D3 do desenho.

**Publica, e so com o que o botao precisa**: nome do assistente, cor primaria
e posicao. O resto da configuracao do agente e do administrador e nao sai por
uma rota anonima.

**Slug errado e slug nao configurado dao o mesmo 404**, com o mesmo corpo.
Distinguir os dois diria a quem sonda se existe algum tenant.

Em modulo proprio, e nao em `widget.py`: aquele arquivo e o ciclo do
WebSocket, e esta e uma leitura HTTP sem nada em comum com ele.

Quem chama e o servidor do Next (`/embed/aparencia`), e nao o navegador: o
`RateLimitPorIP` ve o IP dele, e e o cache de 60 s de la que impede todos os
visitantes de caberem num balde so (D4).
"""

from fastapi import APIRouter, HTTPException, status

from mobia.app.config import get_settings
from mobia.domain.configuracao.repositorio import configuracao_vigente
from mobia.domain.configuracao.vigente import PosicaoDoBotao
from mobia.infra.db import get_sessionmaker

router = APIRouter(tags=["widget"])


@router.get("/widget/aparencia/{slug}")
async def aparencia(slug: str) -> dict[str, object]:
    configurado = get_settings().tenant_slug
    # `not configurado` e nao `is None`: `TENANT_SLUG=` vazio no `.env` chega
    # como "", e "" nao e um slug.
    if not configurado or slug != configurado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nao encontrado")
    async with get_sessionmaker()() as session:
        config = await configuracao_vigente(session)
    return {
        "nomeDoAssistente": config.nome_do_assistente,
        "corPrimaria": config.cor_primaria,
        "posicaoDoBotao": PosicaoDoBotao(config.posicao_do_botao).value,
    }
```

Em `src/mobia/app/main.py`, junto dos imports de rota do topo:

```python
from mobia.api.routes.aparencia_do_widget import router as aparencia_do_widget_router
```

E logo depois de `app.include_router(widget_router)`:

```python
    # TEC-344. Publica pelo mesmo motivo: e o que o loader do site le antes de
    # desenhar o botao.
    app.include_router(aparencia_do_widget_router)
```

Em `src/mobia/api/autorizacao.py`, em `ROTAS_PUBLICAS`, depois de `"/widget/chat"`:

```python
    "/widget/aparencia/{slug}": "cor, lado e nome do botao do chat do site; quem pede e o loader, antes de qualquer visitante se identificar (TEC-344)",
```

(Se passar de 100 colunas, quebre a string em duas literais adjacentes — o `ruff format` não quebra string.)

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_aparencia_do_widget.py tests/unit/test_autorizacao_em_toda_rota.py tests/unit/test_config.py --tb=short -q`
Expected: PASS.

- [ ] **Step 6: Gates e commit**

```bash
git add src/mobia/api/routes/aparencia_do_widget.py src/mobia/app/config.py src/mobia/app/main.py src/mobia/api/autorizacao.py .env.example tests/features/test_aparencia_do_widget.py
git commit -m "feat(TEC-344): o loader do site le a aparencia do chat sem credencial"
```

---

### Task 4: CSP embutível em `/embed/*` e `/widget.js` fora do proxy

**Files:**
- Modify: `frontend/src/proxy.ts`
- Test: `frontend/src/proxy.test.ts`

**Interfaces:**
- Produces: `politicaDeSeguranca(nonce: string, isDev: boolean, opcoes?: { embutivel?: boolean }): string` — `embutivel: true` troca `frame-ancestors 'none'` por `frame-ancestors *`; o padrão continua `'none'`. O matcher exclui `widget.js`.

- [ ] **Step 1: Escrever os testes que falham**

Em `frontend/src/proxy.test.ts`, importe `config` junto de `COOKIE_DA_SESSAO, politicaDeSeguranca, proxy`. No `describe('politicaDeSeguranca')`, acrescente:

```ts
  it('so a rota do embed aceita ser enquadrada, e por qualquer site ate a TEC-345', () => {
    expect(politicaDeSeguranca('abc', false, { embutivel: true })).toContain('frame-ancestors *')
    expect(politicaDeSeguranca('abc', false, { embutivel: true })).not.toContain(
      "frame-ancestors 'none'",
    )
  })
```

Substitua o `it.each([... '/embed/chat', ...])` de "abre sem sessao, e continua recebendo a CSP" por dois:

```ts
  it.each(['/login', '/login/entrar', '/login/mfa', '/sair', '/sessao/atividade'])(
    '%s abre sem sessao, e continua recebendo a CSP que nega iframe',
    (caminho) => {
      const resposta = proxy(requisicao(caminho, { comSessao: false }))

      expect(resposta.headers.get('location')).toBeNull()
      expect(resposta.headers.get('content-security-policy')).toContain("frame-ancestors 'none'")
    },
  )

  it.each(['/embed/chat', '/embed/aparencia'])(
    '%s abre sem sessao e aceita ser enquadrada (TEC-344, D8)',
    (caminho) => {
      const resposta = proxy(requisicao(caminho, { comSessao: false }))

      expect(resposta.headers.get('location')).toBeNull()
      expect(resposta.headers.get('content-security-policy')).toContain('frame-ancestors *')
    },
  )

  it.each(['/', '/leads', '/embedx'])(
    '%s continua negando iframe: afrouxar a rota errada e o que este teste pega',
    (caminho) => {
      expect(cspDe(caminho)).toContain("frame-ancestors 'none'")
    },
  )

  it('`/widget.js` nao passa pelo proxy: sem isso o visitante sem cookie levaria 307 (D9)', () => {
    // O `source` do matcher e expressao do path-to-regexp; para estes caminhos
    // ela coincide com uma RegExp ancorada.
    const fonte = config.matcher[0].source
    const casa = (caminho: string) => new RegExp(`^${fonte}$`).test(caminho)

    expect(casa('/widget.js')).toBe(false)
    expect(casa('/embed/chat')).toBe(true)
    expect(casa('/leads')).toBe(true)
  })
```

- [ ] **Step 2: Rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/proxy.test.ts`
Expected: FAIL — `frame-ancestors *` não aparece, e `casa('/widget.js')` é `true`.

- [ ] **Step 3: Implementar**

Em `proxy.ts`, mude a assinatura e a diretiva:

```ts
export function politicaDeSeguranca(
  nonce: string,
  isDev: boolean,
  { embutivel = false }: { embutivel?: boolean } = {},
): string {
```

e troque a linha `"frame-ancestors 'none'",` (mantendo o comentário que está acima dela) por:

```ts
    // `/embed/*` e o chat que o site da imobiliaria enquadra (TEC-344, D8), e
    // aceita qualquer ancestral ate a TEC-345 restringir aos dominios
    // cadastrados. O padrao do parametro e o fechado: esquecer de passa-lo
    // nega o iframe, e nao o abre.
    embutivel ? 'frame-ancestors *' : "frame-ancestors 'none'",
```

Extraia o teste de rota do embed, antes de `rotaPublica`:

```ts
/** O chat embutido no site da imobiliaria (TEC-344). Casamento por segmento. */
function rotaDoEmbed(caminho: string): boolean {
  return caminho === '/embed' || caminho.startsWith('/embed/')
}
```

e em `rotaPublica` troque as duas linhas de `/embed` por `rotaDoEmbed(caminho) ||`. Em `proxy()`:

```ts
  const politica = politicaDeSeguranca(nonce, process.env.NODE_ENV === 'development', {
    embutivel: rotaDoEmbed(request.nextUrl.pathname),
  })
```

No matcher, troque o `source` por `'/((?!_next/static|_next/image|favicon.ico|widget.js|bff).*)'` e acrescente à lista do comentário:

```ts
       * - `widget.js` -- o loader do chat que o site da imobiliaria carrega
       *   (TEC-344, D9). Sem esta exclusao, o visitante sem cookie levaria
       *   `307` para `/login` em vez do script, e o botao nunca apareceria --
       *   com os testes do loader verdes, porque eles leem o arquivo do disco.
       *   E asset: o `nosniff` vem do `next.config.ts`.
```

- [ ] **Step 4: Rodar e ver passar**

Run (em `frontend/`): `npx vitest run src/proxy.test.ts src/cabecalhos.test.ts`
Expected: PASS.

- [ ] **Step 5: Lint e commit**

```bash
cd frontend && npm run lint && cd ..
git add frontend/src/proxy.ts frontend/src/proxy.test.ts
git commit -m "feat(TEC-344): o embed do chat aceita iframe e o loader nao passa pelo login"
```

---

### Task 5: A aparência do lado do Next — leitura pura, chamada à API e `/embed/aparencia`

**Files:**
- Create: `frontend/src/lib/aparencia.ts`, `frontend/src/lib/servidor/aparencia.ts`, `frontend/src/app/embed/aparencia/route.ts`
- Test: `frontend/src/lib/aparencia.test.ts`, `frontend/src/app/embed/aparencia/route.test.ts`

**Interfaces:**
- Consumes: `GET /widget/aparencia/{slug}` (Task 3); `chamarApi` de `@/lib/servidor/api`.
- Produces:
  - `type Aparencia = { nomeDoAssistente: string | null; corPrimaria: string; posicaoDoBotao: 'DIREITA' | 'ESQUERDA' }`
  - `lerAparencia(corpo: unknown): Aparencia | null`
  - `nomeExibido(aparencia: Aparencia): string` — `'Assistente virtual'` quando nulo
  - `buscarAparencia(tenant: string): Promise<Aparencia | null>` — `null` para slug malformado ou 404; lança para outro status ou corpo malformado
  - `GET /embed/aparencia?tenant=` → 200 com a `Aparencia` e `Cache-Control: public, max-age=60`; 404; 503. Sempre com `Access-Control-Allow-Origin: *`.

- [ ] **Step 1: Testes da leitura pura**

`frontend/src/lib/aparencia.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { type Aparencia, lerAparencia, nomeExibido } from './aparencia'

const VALIDA: Aparencia = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }

describe('lerAparencia', () => {
  it('aceita a forma que a API devolve', () => {
    expect(lerAparencia(VALIDA)).toEqual(VALIDA)
    expect(lerAparencia({ ...VALIDA, nomeDoAssistente: null })?.nomeDoAssistente).toBeNull()
  })

  it.each([
    ['nulo', null],
    ['texto', 'x'],
    ['cor com alfa', { ...VALIDA, corPrimaria: '#0A7F5AFF' }],
    ['cor sem #', { ...VALIDA, corPrimaria: '0A7F5A' }],
    ['posicao desconhecida', { ...VALIDA, posicaoDoBotao: 'CIMA' }],
    ['posicao herdada', { ...VALIDA, posicaoDoBotao: 'constructor' }],
    ['nome que nao e texto', { ...VALIDA, nomeDoAssistente: 7 }],
  ])('recusa %s', (_, corpo) => {
    expect(lerAparencia(corpo)).toBeNull()
  })
})

describe('nomeExibido', () => {
  it('usa o nome configurado, ou "Assistente virtual" sem nome', () => {
    expect(nomeExibido(VALIDA)).toBe('Lia')
    expect(nomeExibido({ ...VALIDA, nomeDoAssistente: null })).toBe('Assistente virtual')
  })
})
```

- [ ] **Step 2: Testes do route handler**

`frontend/src/app/embed/aparencia/route.test.ts`:

```ts
import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { GET } from './route'

const PAINEL = 'https://painel.exemplo.com'
const APARENCIA = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }

function pedido(tenant?: string) {
  const url = new URL('/embed/aparencia', PAINEL)
  if (tenant !== undefined) url.searchParams.set('tenant', tenant)
  return new NextRequest(url)
}

function apiRespondendo(status: number, corpo: unknown = APARENCIA) {
  const api = vi.fn(async () => new Response(JSON.stringify(corpo), { status }))
  vi.stubGlobal('fetch', api)
  return api
}

describe('GET /embed/aparencia', () => {
  beforeEach(() => {
    process.env.MOBIA_API_BASE = 'http://backend:8000'
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('repassa a aparencia com CORS aberto e cache de um minuto', async () => {
    const api = apiRespondendo(200)

    const resposta = await GET(pedido('imobiliaria-x'))

    expect(String(api.mock.calls[0][0])).toBe('http://backend:8000/widget/aparencia/imobiliaria-x')
    expect(resposta.status).toBe(200)
    expect(await resposta.json()).toEqual(APARENCIA)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
    expect(resposta.headers.get('cache-control')).toBe('public, max-age=60')
  })

  it('pede a API com revalidate de 60 s (D4)', async () => {
    const api = apiRespondendo(200)

    await GET(pedido('imobiliaria-x'))

    expect(api.mock.calls[0][1]).toMatchObject({ next: { revalidate: 60 } })
  })

  it('repassa o 404 do FastAPI, com CORS', async () => {
    apiRespondendo(404, { detail: 'nao encontrado' })

    const resposta = await GET(pedido('outra'))

    expect(resposta.status).toBe(404)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
  })

  it.each([undefined, '', '../../health', 'A', 'a/b', 'x'.repeat(65)])(
    'tenant malformado (%s) e 404 sem chamar a API',
    async (tenant) => {
      const api = apiRespondendo(200)

      const resposta = await GET(pedido(tenant))

      expect(resposta.status).toBe(404)
      expect(api).not.toHaveBeenCalled()
    },
  )

  it('API fora do ar vira 503, com CORS, e nao excecao', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed') }))

    const resposta = await GET(pedido('imobiliaria-x'))

    expect(resposta.status).toBe(503)
    expect(resposta.headers.get('access-control-allow-origin')).toBe('*')
  })

  it('corpo malformado da API vira 503: e defeito nosso, nao tenant ausente', async () => {
    apiRespondendo(200, { corPrimaria: 'azul' })

    expect((await GET(pedido('imobiliaria-x'))).status).toBe(503)
  })
})
```

- [ ] **Step 3: Rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/lib/aparencia.test.ts src/app/embed/aparencia/route.test.ts`
Expected: FAIL (módulos inexistentes).

- [ ] **Step 4: Implementar**

`frontend/src/lib/aparencia.ts`:

```ts
/**
 * A aparencia do chat web (TEC-344, D1 e D3): o que o botao e o cabecalho do
 * chat precisam, no formato que `GET /widget/aparencia/{slug}` devolve.
 *
 * Sem `server-only`: a pagina do chat e o teste leem isto, e nao ha segredo
 * aqui. O loader (`public/widget.js`) repete a mesma conferencia porque nao
 * importa nada -- e JavaScript puro, sem build (D5).
 */

export type PosicaoDoBotao = 'DIREITA' | 'ESQUERDA'

export type Aparencia = {
  nomeDoAssistente: string | null
  corPrimaria: string
  posicaoDoBotao: PosicaoDoBotao
}

const COR = /^#[0-9A-Fa-f]{6}$/
// Lista, e nao objeto: `'constructor' in {}` e verdadeiro, e uma posicao com
// nome de propriedade herdada passaria.
const POSICOES: readonly string[] = ['DIREITA', 'ESQUERDA']

export function lerAparencia(corpo: unknown): Aparencia | null {
  if (typeof corpo !== 'object' || corpo === null) {
    return null
  }
  const { nomeDoAssistente, corPrimaria, posicaoDoBotao } = corpo as Record<string, unknown>
  if (typeof corPrimaria !== 'string' || !COR.test(corPrimaria)) {
    return null
  }
  if (typeof posicaoDoBotao !== 'string' || !POSICOES.includes(posicaoDoBotao)) {
    return null
  }
  if (nomeDoAssistente !== null && typeof nomeDoAssistente !== 'string') {
    return null
  }
  return { nomeDoAssistente, corPrimaria, posicaoDoBotao: posicaoDoBotao as PosicaoDoBotao }
}

/** O nome com que o chat se apresenta. Texto de tela: com acento se tiver. */
export function nomeExibido(aparencia: Aparencia): string {
  return aparencia.nomeDoAssistente ?? 'Assistente virtual'
}
```

`frontend/src/lib/servidor/aparencia.ts`:

```ts
import 'server-only'

import { type Aparencia, lerAparencia } from '@/lib/aparencia'

import { chamarApi } from './api'

/**
 * O formato do slug antes de ele virar pedaco de caminho da API. Minusculas,
 * digitos e hifen: o que cabe num `data-tenant` sem escape. Barra e ponto
 * ficam de fora, e com eles `../../health` nunca vira outra rota do FastAPI.
 */
const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/

/**
 * A aparencia do tenant, ou `null` se o slug nao existe.
 *
 * **Com cache de 60 s, e esse cache e requisito, nao otimizacao** (D4): quem
 * chama o FastAPI e este servidor, e o `RateLimitPorIP` de la ve o IP dele.
 * Sem cache, todos os visitantes de todos os sites dividiriam um balde so.
 *
 * Lanca quando o FastAPI responde outra coisa que 200 ou 404, ou devolve um
 * corpo que nao e aparencia: e defeito, e nao "tenant ausente".
 */
export async function buscarAparencia(tenant: string): Promise<Aparencia | null> {
  if (!SLUG.test(tenant)) {
    return null
  }
  const resposta = await chamarApi(`/widget/aparencia/${tenant}`, { revalidarEmSegundos: 60 })
  if (resposta.status === 404) {
    return null
  }
  if (!resposta.ok) {
    throw new Error(`aparencia do widget: o FastAPI respondeu ${resposta.status}`)
  }
  const aparencia = lerAparencia(await resposta.json())
  if (!aparencia) {
    throw new Error('aparencia do widget: o FastAPI devolveu um corpo fora do formato')
  }
  return aparencia
}
```

`frontend/src/app/embed/aparencia/route.ts`:

```ts
import { type NextRequest, NextResponse } from 'next/server'

import { buscarAparencia } from '@/lib/servidor/aparencia'

/**
 * O que o loader do site pede antes de desenhar o botao (TEC-344, D5).
 *
 * **CORS aberto a qualquer origem**: quem pede e o site da imobiliaria, que
 * nao e esta origem, e a resposta nao tem nada que nao esteja no proprio botao.
 * A TEC-345 e quem restringe aos dominios cadastrados.
 *
 * Toda resposta leva o CORS, inclusive 404 e 503: sem ele o navegador
 * esconderia o status do loader, que so saberia que "falhou" -- o que da no
 * mesmo para ele, mas nao para quem depura pela aba de rede.
 */
const CORS = { 'Access-Control-Allow-Origin': '*' }

export async function GET(requisicao: NextRequest) {
  const tenant = requisicao.nextUrl.searchParams.get('tenant') ?? ''
  let aparencia: Awaited<ReturnType<typeof buscarAparencia>>
  try {
    aparencia = await buscarAparencia(tenant)
  } catch {
    return NextResponse.json({ erro: 'indisponivel' }, { status: 503, headers: CORS })
  }
  if (!aparencia) {
    return NextResponse.json({ erro: 'nao_encontrado' }, { status: 404, headers: CORS })
  }
  return NextResponse.json(aparencia, {
    headers: { ...CORS, 'Cache-Control': 'public, max-age=60' },
  })
}
```

- [ ] **Step 5: Rodar e ver passar**

Run (em `frontend/`): `npx vitest run src/lib/aparencia.test.ts src/app/embed/aparencia/route.test.ts`
Expected: PASS.

- [ ] **Step 6: Lint e commit**

```bash
cd frontend && npm run lint && cd ..
git add frontend/src/lib/aparencia.ts frontend/src/lib/aparencia.test.ts frontend/src/lib/servidor/aparencia.ts frontend/src/app/embed/aparencia
git commit -m "feat(TEC-344): o Next serve a aparencia do chat ao site, com cache de um minuto"
```

---

### Task 6: A página `/embed/chat`

**Files:**
- Create: `frontend/src/app/embed/chat/page.tsx`, `frontend/src/components/CabecalhoDoChat.tsx`, `frontend/src/components/AvisoDePronto.tsx`
- Modify: `frontend/src/app/globals.css`
- Test: `frontend/src/components/CabecalhoDoChat.test.tsx`, `frontend/src/components/AvisoDePronto.test.tsx`

**Interfaces:**
- Consumes: `buscarAparencia`, `nomeExibido` (Task 5); cabeçalho `x-nonce` que o proxy põe na requisição.
- Produces: `/embed/chat?tenant=` renderiza o cabeçalho com o nome e manda `postMessage({ tipo: 'mobia:pronto' }, '*')` ao pai quando monta; 404 para tenant inexistente.

- [ ] **Step 1: Testes dos componentes**

`frontend/src/components/CabecalhoDoChat.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CabecalhoDoChat } from './CabecalhoDoChat'

describe('CabecalhoDoChat', () => {
  it('se apresenta com o nome do assistente (cenario 3)', () => {
    render(<CabecalhoDoChat nome="Lia" />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Lia')
  })
})
```

`frontend/src/components/AvisoDePronto.test.tsx`:

```tsx
import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AvisoDePronto } from './AvisoDePronto'

describe('AvisoDePronto', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('avisa o loader do site que o chat carregou (D7)', () => {
    // No jsdom a pagina nao esta num iframe, e `window.parent` e a propria janela.
    const aviso = vi.spyOn(window.parent, 'postMessage')

    render(<AvisoDePronto />)

    expect(aviso).toHaveBeenCalledTimes(1)
    expect(aviso).toHaveBeenCalledWith({ tipo: 'mobia:pronto' }, '*')
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/components/CabecalhoDoChat.test.tsx src/components/AvisoDePronto.test.tsx`
Expected: FAIL (módulos inexistentes).

- [ ] **Step 3: Implementar os componentes**

`frontend/src/components/CabecalhoDoChat.tsx`:

```tsx
/**
 * O topo do chat embutido: o nome com que o assistente se apresenta
 * (TEC-344, cenario 3). A conversa em si e da TEC-346.
 */
export function CabecalhoDoChat({ nome }: { nome: string }) {
  return (
    <header className="chat-embutido__cabecalho">
      <h1>{nome}</h1>
    </header>
  )
}
```

`frontend/src/components/AvisoDePronto.tsx`:

```tsx
'use client'

import { useEffect } from 'react'

/**
 * Diz ao loader do site que o chat carregou (TEC-344, D7).
 *
 * Um iframe de outra origem nao dispara `onerror` quando a pagina dele falha,
 * entao o loader espera esta mensagem e, sem ela em 10 s, some com o botao.
 *
 * `'*'` como destino, e nao a origem do site: esta pagina nao sabe em que site
 * esta, e a mensagem nao carrega nada alem do proprio aviso. Quem confere
 * origem e o loader, ao receber.
 */
export function AvisoDePronto() {
  useEffect(() => {
    window.parent.postMessage({ tipo: 'mobia:pronto' }, '*')
  }, [])
  return null
}
```

- [ ] **Step 4: A página**

`frontend/src/app/embed/chat/page.tsx`:

```tsx
import type { Metadata } from 'next'
import { headers } from 'next/headers'
import { notFound } from 'next/navigation'

import { AvisoDePronto } from '@/components/AvisoDePronto'
import { CabecalhoDoChat } from '@/components/CabecalhoDoChat'
import { nomeExibido } from '@/lib/aparencia'
import { buscarAparencia } from '@/lib/servidor/aparencia'

export const metadata: Metadata = {
  title: 'Chat',
  robots: { index: false, follow: false },
}

/**
 * O chat que o site da imobiliaria enquadra (TEC-344, D6). Nesta card, so o
 * cabecalho; a conversa e da TEC-346 (L3).
 *
 * **A cor entra por `<style nonce>`, e nao pelo atributo `style`.** A CSP do
 * proxy nao tem `'unsafe-inline'` em `style-src` fora de desenvolvimento, e
 * atributo `style` e estilo inline -- em producao a cor sumiria sem erro. A
 * interpolacao e segura porque `buscarAparencia` so devolve cor que casa com
 * `#RRGGBB`.
 *
 * Tenant inexistente e 404, e a pagina nao manda `mobia:pronto`: o loader so
 * chega aqui depois de a aparencia responder 200, entao isto e a configuracao
 * mudando entre um pedido e outro, e o botao sumir e o desfecho certo.
 */
export default async function ChatEmbutido({ searchParams }: PageProps<'/embed/chat'>) {
  const { tenant } = await searchParams
  const aparencia = typeof tenant === 'string' ? await buscarAparencia(tenant) : null
  if (!aparencia) {
    notFound()
  }
  const nonce = (await headers()).get('x-nonce') ?? undefined

  return (
    <main className="chat-embutido">
      <style nonce={nonce}>{`.chat-embutido { --cor-primaria: ${aparencia.corPrimaria}; }`}</style>
      <CabecalhoDoChat nome={nomeExibido(aparencia)} />
      <AvisoDePronto />
    </main>
  )
}
```

Se `PageProps<'/embed/chat'>` não resolver no `tsc` (o tipo global é gerado pelo `next build`/`next dev` em `.next/types`), rode `npx next typegen` antes de concluir que está errado.

- [ ] **Step 5: O estilo**

No fim de `frontend/src/app/globals.css`:

```css
/* O chat embutido no site da imobiliaria (TEC-344). `--cor-primaria` vem da
   configuracao do tenant, por `<style nonce>` na pagina. */
.chat-embutido {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.chat-embutido__cabecalho {
  background: var(--cor-primaria, #1d4ed8);
  color: #fff;
  padding: 16px;
}

.chat-embutido__cabecalho h1 {
  margin: 0;
  font-size: 1.125rem;
}
```

- [ ] **Step 6: Rodar e ver passar, e o build**

Run (em `frontend/`): `npx vitest run src/components/CabecalhoDoChat.test.tsx src/components/AvisoDePronto.test.tsx && npm run build`
Expected: PASS nos testes; build termina listando `/embed/chat` e `/embed/aparencia` como rotas dinâmicas (`ƒ`).

- [ ] **Step 7: Lint e commit**

```bash
cd frontend && npm run lint && cd ..
git add frontend/src/app/embed/chat frontend/src/components/CabecalhoDoChat.tsx frontend/src/components/CabecalhoDoChat.test.tsx frontend/src/components/AvisoDePronto.tsx frontend/src/components/AvisoDePronto.test.tsx frontend/src/app/globals.css
git commit -m "feat(TEC-344): o chat embutido se apresenta com o nome e avisa que carregou"
```

---

### Task 7: O loader `widget.js`, o gate de 5 KB e o CI

**Files:**
- Create: `frontend/public/widget.js`, `frontend/scripts/verificar-widget.mjs`, `frontend/src/widget/widget.test.ts`
- Modify: `frontend/package.json`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `GET <origem>/embed/aparencia?tenant=` (Task 5); `postMessage({ tipo: 'mobia:pronto' })` de `/embed/chat` (Task 6).
- Produces: `window.__mobiaWidget = true` depois de iniciar; um host `<div>` com shadow root fechado contendo o `<button>`; no clique, `<iframe src="<origem>/embed/chat?tenant=<slug>">`. Script `npm run verificar:widget`.

- [ ] **Step 1: Os testes que falham**

`frontend/src/widget/widget.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * O loader de verdade, lido do disco e executado no jsdom (TEC-344, D5).
 *
 * O shadow root e FECHADO em producao, e o teste o alcanca interceptando
 * `attachShadow` -- sem isso nao haveria como ver o botao sem abrir o root, e
 * abrir so para o teste seria mudar o que se testa.
 *
 * O `fetch` e duble que devolve um objeto com `status` e `json()`, e nao um
 * `Response`: o corpo de um `Response` do Node se le por stream, fora das
 * microtarefas que `assentar()` drena, e o teste ficaria dependente de tempo.
 */

const CODIGO = readFileSync(resolve(__dirname, '../../public/widget.js'), 'utf8')
const PAINEL = 'https://painel.exemplo.com'
const APARENCIA = { nomeDoAssistente: 'Lia', corPrimaria: '#0A7F5A', posicaoDoBotao: 'ESQUERDA' }

let raizes: ShadowRoot[] = []
let erros: unknown[] = []
const registrarErro = (evento: Event) => erros.push(evento)

function apiRespondendo(status: number, corpo: unknown = APARENCIA) {
  const api = vi.fn(async (_url: string, _init?: RequestInit) => ({
    status,
    json: async () => corpo,
  }))
  vi.stubGlobal('fetch', api)
  return api
}

function instalar({ tenant = 'imobiliaria-x' as string | null, comoAtual = true } = {}) {
  const script = document.createElement('script')
  script.src = `${PAINEL}/widget.js`
  if (tenant !== null) script.setAttribute('data-tenant', tenant)
  document.head.appendChild(script)
  if (comoAtual) {
    Object.defineProperty(document, 'currentScript', { value: script, configurable: true })
  }
  try {
    new Function(CODIGO)()
  } finally {
    Object.defineProperty(document, 'currentScript', { value: null, configurable: true })
  }
}

async function assentar() {
  for (let i = 0; i < 20; i++) await Promise.resolve()
}

const botao = () => raizes[0]?.querySelector('button') ?? null
const quadro = () => raizes[0]?.querySelector('iframe') ?? null

beforeEach(() => {
  raizes = []
  erros = []
  const original = Element.prototype.attachShadow
  vi.spyOn(Element.prototype, 'attachShadow').mockImplementation(function (
    this: Element,
    init: ShadowRootInit,
  ) {
    const raiz = original.call(this, init)
    raizes.push(raiz)
    return raiz
  })
  window.addEventListener('error', registrarErro)
  window.addEventListener('unhandledrejection', registrarErro)
})

afterEach(() => {
  window.removeEventListener('error', registrarErro)
  window.removeEventListener('unhandledrejection', registrarErro)
  document.head.innerHTML = ''
  document.body.innerHTML = ''
  delete (window as unknown as Record<string, unknown>).__mobiaWidget
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('o botao', () => {
  it('pede a aparencia a origem do proprio script, sem cookie', async () => {
    const api = apiRespondendo(200)

    instalar()
    await assentar()

    expect(api.mock.calls[0][0]).toBe(`${PAINEL}/embed/aparencia?tenant=imobiliaria-x`)
    expect(api.mock.calls[0][1]).toMatchObject({ credentials: 'omit' })
  })

  it('cenario 3: canto inferior esquerdo, na cor do tenant, com o nome no rotulo', async () => {
    apiRespondendo(200)

    instalar()
    await assentar()

    const b = botao()!
    expect(b.style.left).toBe('20px')
    expect(b.style.right).toBe('')
    expect(b.style.bottom).toBe('20px')
    expect(b.style.backgroundColor).toBe('rgb(10, 127, 90)')
    expect(b.getAttribute('aria-label')).toBe('Abrir o chat com Lia')
  })

  it('a direita, e sem nome o rotulo nao inventa um', async () => {
    apiRespondendo(200, { ...APARENCIA, nomeDoAssistente: null, posicaoDoBotao: 'DIREITA' })

    instalar()
    await assentar()

    expect(botao()!.style.right).toBe('20px')
    expect(botao()!.getAttribute('aria-label')).toBe('Abrir o chat')
  })

  it('acha o proprio script mesmo sem `currentScript`', async () => {
    apiRespondendo(200)

    instalar({ comoAtual: false })
    await assentar()

    expect(botao()).not.toBeNull()
  })

  it('snippet colado duas vezes desenha um botao so', async () => {
    const api = apiRespondendo(200)

    instalar()
    instalar()
    await assentar()

    expect(api).toHaveBeenCalledTimes(1)
    expect(raizes).toHaveLength(1)
  })

  it('sem `data-tenant` nao pede nada e nao desenha nada', async () => {
    const api = apiRespondendo(200)

    instalar({ tenant: null })
    await assentar()

    expect(api).not.toHaveBeenCalled()
    expect(raizes).toHaveLength(0)
  })
})

describe('cenario 4: o servidor do chat fora do ar nao quebra o site', () => {
  it.each([
    ['404', () => apiRespondendo(404, { erro: 'nao_encontrado' })],
    ['503', () => apiRespondendo(503, { erro: 'indisponivel' })],
    ['rede fora', () => vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed') }))],
    ['JSON torto', () => vi.stubGlobal('fetch', vi.fn(async () => ({ status: 200, json: async () => { throw new SyntaxError('x') } })))],
    ['corpo nulo', () => apiRespondendo(200, null)],
    ['cor invalida', () => apiRespondendo(200, { ...APARENCIA, corPrimaria: 'red' })],
    ['cor com alfa', () => apiRespondendo(200, { ...APARENCIA, corPrimaria: '#0A7F5AFF' })],
    ['posicao desconhecida', () => apiRespondendo(200, { ...APARENCIA, posicaoDoBotao: 'CIMA' })],
    ['posicao herdada', () => apiRespondendo(200, { ...APARENCIA, posicaoDoBotao: 'constructor' })],
  ])('%s: sem botao e sem erro', async (_, preparar) => {
    preparar()

    instalar()
    await assentar()

    expect(raizes).toHaveLength(0)
    expect(erros).toEqual([])
  })

  it('aparencia que nao responde em 5 s: sem botao e sem erro', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_, rejeitar) =>
            init.signal!.addEventListener('abort', () =>
              rejeitar(new DOMException('abortado', 'AbortError')),
            ),
          ),
      ),
    )

    instalar()
    await vi.advanceTimersByTimeAsync(5000)
    await assentar()

    expect(raizes).toHaveLength(0)
    expect(erros).toEqual([])
  })
})

describe('o painel', () => {
  it('cenario 1: nenhum iframe antes do clique', async () => {
    apiRespondendo(200)

    instalar()
    await assentar()

    expect(quadro()).toBeNull()
  })

  it('o primeiro clique cria o iframe do chat; os seguintes so abrem e fecham', async () => {
    apiRespondendo(200)
    instalar()
    await assentar()

    botao()!.click()
    const primeiro = quadro()!
    expect(primeiro.src).toBe(`${PAINEL}/embed/chat?tenant=imobiliaria-x`)
    expect(botao()!.getAttribute('aria-expanded')).toBe('true')

    botao()!.click()
    expect(botao()!.getAttribute('aria-expanded')).toBe('false')
    expect((primeiro.parentElement as HTMLElement).style.display).toBe('none')

    botao()!.click()
    expect(quadro()).toBe(primeiro)
    expect(raizes[0].querySelectorAll('iframe')).toHaveLength(1)
  })

  it('sem `mobia:pronto` em 10 s, painel e botao somem', async () => {
    vi.useFakeTimers()
    apiRespondendo(200)
    instalar()
    await assentar()
    botao()!.click()

    await vi.advanceTimersByTimeAsync(10_000)

    expect(document.body.contains(raizes[0].host)).toBe(false)
    expect(erros).toEqual([])
  })

  it('com `mobia:pronto` do proprio iframe, o painel fica', async () => {
    vi.useFakeTimers()
    apiRespondendo(200)
    instalar()
    await assentar()
    botao()!.click()

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { tipo: 'mobia:pronto' },
        origin: PAINEL,
        source: quadro()!.contentWindow,
      }),
    )
    await vi.advanceTimersByTimeAsync(10_000)

    expect(document.body.contains(raizes[0].host)).toBe(true)
  })

  it.each([
    ['de outra origem', () => ({ origin: 'https://intruso.exemplo.com', source: quadro()!.contentWindow })],
    ['de outra janela', () => ({ origin: PAINEL, source: window })],
  ])('`mobia:pronto` %s e ignorado', async (_, remetente) => {
    vi.useFakeTimers()
    apiRespondendo(200)
    instalar()
    await assentar()
    botao()!.click()

    window.dispatchEvent(
      new MessageEvent('message', { data: { tipo: 'mobia:pronto' }, ...remetente() }),
    )
    await vi.advanceTimersByTimeAsync(10_000)

    expect(document.body.contains(raizes[0].host)).toBe(false)
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run (em `frontend/`): `npx vitest run src/widget/widget.test.ts`
Expected: FAIL com `ENOENT ... public/widget.js`.

- [ ] **Step 3: O loader**

`frontend/public/widget.js`:

```js
/*
 * O loader do chat web da mobIA (TEC-344). Uma linha no site da imobiliaria:
 *
 *   <script src="https://<painel>/widget.js" data-tenant="<slug>" async></script>
 *
 * Desenha um botao com a cor, o lado e o nome configurados, e no primeiro
 * clique abre o chat num iframe. **Nenhuma falha vira erro de JS no site**
 * (D7 do desenho): tudo roda dentro de try/catch, toda promise tem catch, e o
 * que falha deixa o site sem botao.
 *
 * JavaScript puro, sem build e sem dependencia (D5): o que esta aqui e o que o
 * navegador baixa, e `npm run verificar:widget` reprova acima de 5 KB gzip.
 * Sem conferencia de tipos -- o `tsconfig` nao inclui `.js` de `public/` --, e
 * por isso a rede sao os testes de `src/widget/widget.test.ts`, que executam
 * este arquivo.
 */
;(function () {
  'use strict'

  var TEMPO_DA_APARENCIA_MS = 5000
  var TEMPO_DO_PRONTO_MS = 10000
  var COR = /^#[0-9A-Fa-f]{6}$/
  // O lado do CSS por posicao. Lido so por `hasOwnProperty`: uma posicao
  // chamada "constructor" acharia a funcao herdada e passaria por valida.
  var LADOS = { DIREITA: 'right', ESQUERDA: 'left' }
  var CAMADA = '2147483000'

  try {
    iniciar()
  } catch {
    // D7: nada escapa para o site hospedeiro.
  }

  function iniciar() {
    // `currentScript` so vale durante a execucao sincrona deste arquivo, entao
    // e lido aqui, antes de qualquer `await`.
    var script = acharScript()
    var tenant = script && script.getAttribute('data-tenant')
    if (!tenant || window.__mobiaWidget) {
      return
    }
    window.__mobiaWidget = true
    var origem = new URL(script.src, location.href).origin
    buscarAparencia(origem, tenant)
      .then(function (aparencia) {
        if (aparencia) {
          desenhar(origem, tenant, aparencia)
        }
      })
      .catch(function () {})
  }

  function acharScript() {
    var atual = document.currentScript
    if (atual && atual.getAttribute('data-tenant')) {
      return atual
    }
    return document.querySelector('script[data-tenant][src*="widget.js"]')
  }

  function buscarAparencia(origem, tenant) {
    var controle = new AbortController()
    var prazo = setTimeout(function () {
      controle.abort()
    }, TEMPO_DA_APARENCIA_MS)
    var url = origem + '/embed/aparencia?tenant=' + encodeURIComponent(tenant)
    return fetch(url, { credentials: 'omit', signal: controle.signal })
      .then(function (resposta) {
        return resposta.status === 200 ? resposta.json() : null
      })
      .then(lerAparencia)
      .catch(function () {
        return null
      })
      .then(function (aparencia) {
        clearTimeout(prazo)
        return aparencia
      })
  }

  function lerAparencia(corpo) {
    if (!corpo || typeof corpo !== 'object') {
      return null
    }
    var cor = corpo.corPrimaria
    var posicao = corpo.posicaoDoBotao
    if (typeof cor !== 'string' || !COR.test(cor)) {
      return null
    }
    if (typeof posicao !== 'string' || !Object.prototype.hasOwnProperty.call(LADOS, posicao)) {
      return null
    }
    var nome = typeof corpo.nomeDoAssistente === 'string' ? corpo.nomeDoAssistente : null
    return { cor: cor, lado: LADOS[posicao], nome: nome }
  }

  function desenhar(origem, tenant, aparencia) {
    var hospede = document.createElement('div')
    // Fechado: o CSS do site nao entra, e o script do site nao alcanca o
    // botao por `shadowRoot`.
    var raiz = hospede.attachShadow({ mode: 'closed' })
    var botao = document.createElement('button')
    botao.type = 'button'
    botao.setAttribute(
      'aria-label',
      aparencia.nome ? 'Abrir o chat com ' + aparencia.nome : 'Abrir o chat',
    )
    botao.setAttribute('aria-expanded', 'false')
    // CSSOM, e nao `<style>`: a CSP do proprio site pode bloquear `<style>`
    // injetado, e nao bloqueia `el.style`.
    var estilo = {
      position: 'fixed',
      bottom: '20px',
      width: '56px',
      height: '56px',
      borderRadius: '50%',
      border: '0',
      padding: '0',
      cursor: 'pointer',
      backgroundColor: aparencia.cor,
      color: '#fff',
      boxShadow: '0 4px 12px rgba(0,0,0,.25)',
      zIndex: CAMADA,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    }
    estilo[aparencia.lado] = '20px'
    Object.assign(botao.style, estilo)
    botao.appendChild(icone())
    raiz.appendChild(botao)

    var painel = null
    botao.addEventListener('click', function () {
      try {
        if (!painel) {
          painel = abrirPainel(origem, tenant, aparencia.lado, raiz, hospede)
        } else {
          painel.style.display = painel.style.display === 'none' ? 'block' : 'none'
        }
        botao.setAttribute('aria-expanded', painel.style.display === 'none' ? 'false' : 'true')
      } catch {
        // D7.
      }
    })
    ;(document.body || document.documentElement).appendChild(hospede)
  }

  function abrirPainel(origem, tenant, lado, raiz, hospede) {
    var painel = document.createElement('div')
    var estilo = {
      position: 'fixed',
      bottom: '88px',
      width: 'min(380px, calc(100vw - 40px))',
      height: 'min(600px, calc(100vh - 120px))',
      borderRadius: '12px',
      overflow: 'hidden',
      boxShadow: '0 8px 24px rgba(0,0,0,.25)',
      background: '#fff',
      zIndex: CAMADA,
      display: 'block',
    }
    estilo[lado] = '20px'
    Object.assign(painel.style, estilo)

    var quadro = document.createElement('iframe')
    quadro.title = 'Chat'
    quadro.src = origem + '/embed/chat?tenant=' + encodeURIComponent(tenant)
    Object.assign(quadro.style, { width: '100%', height: '100%', border: '0' })
    painel.appendChild(quadro)
    raiz.appendChild(painel)

    // D7: iframe de outra origem nao dispara `onerror`. A pagina do chat manda
    // `mobia:pronto`; sem ele no prazo, o chat nao carregou, e botao e painel
    // saem do site. So vale a mensagem da nossa origem E da janela deste
    // iframe -- qualquer outra aba ou frame poderia mandar o mesmo texto.
    var prazo = setTimeout(function () {
      window.removeEventListener('message', aoMensagem)
      hospede.remove()
    }, TEMPO_DO_PRONTO_MS)

    function aoMensagem(evento) {
      try {
        if (evento.origin !== origem || evento.source !== quadro.contentWindow) {
          return
        }
        if (evento.data && evento.data.tipo === 'mobia:pronto') {
          clearTimeout(prazo)
          window.removeEventListener('message', aoMensagem)
        }
      } catch {
        // D7.
      }
    }
    window.addEventListener('message', aoMensagem)
    return painel
  }

  function icone() {
    var ns = 'http://www.w3.org/2000/svg'
    var svg = document.createElementNS(ns, 'svg')
    svg.setAttribute('width', '28')
    svg.setAttribute('height', '28')
    svg.setAttribute('viewBox', '0 0 24 24')
    svg.setAttribute('fill', 'currentColor')
    svg.setAttribute('aria-hidden', 'true')
    var balao = document.createElementNS(ns, 'path')
    balao.setAttribute('d', 'M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z')
    svg.appendChild(balao)
    return svg
  }
})()
```

- [ ] **Step 4: Rodar e ver passar**

Run (em `frontend/`): `npx vitest run src/widget/widget.test.ts`
Expected: PASS. Se `style.backgroundColor` vier `#0A7F5A` em vez de `rgb(...)` na versão do jsdom instalada, ajuste a expectativa do teste para o que o jsdom normaliza — o que importa é a cor, não o formato.

- [ ] **Step 5: O gate de tamanho**

`frontend/scripts/verificar-widget.mjs`:

```js
#!/usr/bin/env node
/**
 * O loader do chat cabe em 5 KB gzip (TEC-344, segunda regra da card).
 *
 * Comprime `public/widget.js` com o nivel padrao do zlib -- o que um servidor
 * comum aplica --, e nao com o maximo: medir com `level: 9` aprovaria um
 * arquivo que chega maior ao visitante.
 *
 * O arquivo e o que o navegador baixa, byte a byte, porque nao ha build (D5):
 * medir a fonte e medir a entrega.
 */
import { readFile } from 'node:fs/promises'
import { gzipSync } from 'node:zlib'

const LIMITE = 5 * 1024
const bytes = gzipSync(await readFile(new URL('../public/widget.js', import.meta.url))).length

if (bytes > LIMITE) {
  console.error(`\nverificar-widget: widget.js tem ${bytes} bytes gzip; o teto e ${LIMITE}.\n`)
  process.exit(1)
}
console.log(`verificar-widget: widget.js tem ${bytes} bytes gzip (teto ${LIMITE}).`)
```

Em `frontend/package.json`, em `scripts`, depois de `verificar:bundle`:

```json
    "verificar:widget": "node scripts/verificar-widget.mjs"
```

Em `.github/workflows/ci.yml`, no job `frontend`, depois do passo `Testes` e antes de `Build`:

```yaml
      # A segunda regra da TEC-344: o loader do chat cabe em 5 KB gzip. Nao
      # depende do build -- `public/widget.js` e servido como esta (D5) --, e
      # por isso vem antes dele: reprova em segundos, sem esperar o `next build`.
      - name: Tamanho do loader do chat
        run: npm run verificar:widget
```

Run (em `frontend/`): `npm run verificar:widget`
Expected: `verificar-widget: widget.js tem NNNN bytes gzip (teto 5120).` com NNNN bem abaixo do teto.

- [ ] **Step 6: Lint e commit**

```bash
cd frontend && npm run lint && npm test && cd ..
git add frontend/public/widget.js frontend/scripts/verificar-widget.mjs frontend/src/widget/widget.test.ts frontend/package.json .github/workflows/ci.yml
git commit -m "feat(TEC-344): uma linha de script desenha o botao e abre o chat no site"
```

---

### Task 8: Documentação, verificação ponta a ponta e entrega

**Files:**
- Modify: `frontend/README.md`, `docs/superpowers/specs/2026-09-27-tec-344-embed-do-chat-design.md` (status)

- [ ] **Step 1: README do frontend**

Em `frontend/README.md`, antes de `## Comandos`, uma seção:

```markdown
## O chat no site da imobiliária (TEC-344)

A imobiliária cola uma linha no site:

    <script src="https://<painel>/widget.js" data-tenant="<slug>" async></script>

O `<slug>` tem de ser igual ao `TENANT_SLUG` do backend. Sem `TENANT_SLUG`, nenhum site mostra o botão — é o padrão, de propósito. Cor, lado e nome do assistente vêm da configuração do agente (`PATCH /api/v1/configuracao/agente`), e uma mudança leva até um minuto para chegar ao site, por causa do cache de `/embed/aparencia`.

`public/widget.js` não passa por build: o que está no arquivo é o que o visitante baixa, e `npm run verificar:widget` reprova acima de 5 KB gzip. Até a TEC-346, quem abre o chat vê só o cabeçalho; até a TEC-345, qualquer site pode embutir o chat.
```

- [ ] **Step 2: Verificação manual no navegador**

Com `docker compose up -d`, a API (`uvicorn`) com `TENANT_SLUG=imobiliaria-x` e o frontend em `npm run dev`:

1. Salve em `C:\Users\eduar\AppData\Local\Temp\claude\...\scratchpad\site.html` uma página qualquer com o snippet apontando para `http://localhost:3000/widget.js` e `data-tenant="imobiliaria-x"`, e sirva-a de outra porta (`python -m http.server 8080`).
2. Abra `http://localhost:8080/site.html`: o botão aparece; a aba de rede mostra `widget.js` e `/embed/aparencia`, e **nenhum** pedido a `/embed/chat` antes do clique.
3. Clique: o iframe carrega o cabeçalho com o nome; o console do site não tem erro.
4. Troque `data-tenant` para `errado` e recarregue: sem botão, sem erro no console.
5. Pare o `npm run dev` e recarregue: sem botão, e o único registro no console é a falha de rede do `<script>`.

Registre o resultado de cada item para o comentário da card. Se algum não puder ser feito, diga qual e por quê.

- [ ] **Step 3: Gates e suíte**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
cd frontend && npm run lint && npm test && npm run verificar:widget && npm run build && cd ..
```

Se o `-n 8` voltar com centenas de `ERROR` de setup ou `CannotConnectNowError`, é o banco — rode por blocos (CLAUDE.md, "Quando o `-n 8` derruba o Postgres"). Guarde o hash do commit junto do resultado.

- [ ] **Step 4: Comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
```

Releia cada `ALTERADO`/`VIZINHO`. Atenção especial à docstring de módulo de `vigente.py` ("O padrao e o comportamento de antes desta card") — ela continua verdadeira para os campos antigos, e a exceção dos campos novos está no comentário de `COR_PRIMARIA_PADRAO`; confira que as duas frases não se contradizem.

- [ ] **Step 5: Status da spec e commit**

Em `docs/superpowers/specs/2026-09-27-tec-344-embed-do-chat-design.md`, troque `**Status:** desenho aprovado, implementação pendente` por `**Status:** implementado`. Registre ali, como nota na decisão afetada, toda divergência que a implementação produziu.

```bash
git add frontend/README.md docs/superpowers/specs/2026-09-27-tec-344-embed-do-chat-design.md
git commit -m "docs(TEC-344): o README do frontend ensina a instalar o chat no site"
```

- [ ] **Step 6: Push, PR e card**

```bash
git push -u origin feat/tec-344-embed-do-chat
gh pr create --base main --title "feat(TEC-344): instalar o chat no site da imobiliaria com uma linha de script" --body "<resumo, decisoes D1-D9, lacunas L1-L5, resultado da suite e da verificacao manual>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Depois, comentário na TEC-344 (divergências em relação à card, critério não exercitado — o 1,5 s em 4G (L2) —, as lacunas de produto L3 e L5, e o que a card não entrega) e transição para **Em análise**.

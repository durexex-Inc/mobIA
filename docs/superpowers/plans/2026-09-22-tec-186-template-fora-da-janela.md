# TEC-186 — Template aprovado fora da janela de 24 horas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o `sweep_followups` decidir a janela a partir da âncora, ANTES de enviar; dentro da janela mantém o texto livre da TEC-184; fora da janela escolhe um template aprovado por contexto e o envia, e sem template aplicável grava uma tarefa para o corretor.

**Architecture:** A decisão da janela e a escolha do template moram num módulo puro (`domain/followup/template.py`), testável sem banco. A aprovação pela Meta é configuração (`whatsapp_templates_aprovados`), não código — default vazio, que é a mitigação do RT-03. O envio por template é uma forma nova de payload no `_deliver` do WhatsApp (`tipo=template`), ao lado da imagem que a TEC-162 já criou. A tarefa para o corretor é uma tabela append-only própria (`tarefas_de_corretor`), no molde de `followups`. A varredura orquestra: dentro da janela, texto livre; fora, template ou tarefa.

**Tech Stack:** Python 3.13, SQLAlchemy async, ARQ, pytest. Sem dependência nova. Uma migration (`0039`).

**Spec:** `docs/superpowers/specs/2026-09-22-tec-186-template-fora-da-janela-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, nenhum linter verifica. Valor citado entre delimitadores segue o valor (ver CLAUDE.md, "Acentos").
- **Texto que chega ao lead: português COM acento** (TEC-267). Os parâmetros de template que preenchem o texto aprovado chegam ao lead; reuse `reais_de`/`legenda_de` de `apresentacao.py`, que já seguem a convenção viva.
- **Prosa em `docs/` e no SRS: com acento.**
- **Os três gates, com o escopo exato do CI**, antes de qualquer commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter.
- **Loop rápido:** `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short` (~4s, sem Docker, sem `-n`).
- **Suíte inteira, uma vez, no fim:** `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short` — e se cair em recovery, por blocos (ver CLAUDE.md).
- **`ConnectionResetError [WinError 64]` em fixture é flake conhecido desta máquina.** Espere e rode de novo antes de diagnosticar. **`relation ... does not exist`** são os bancos dos workers com o carimbo do Alembic adiantado — reporte, não conserte.
- **Mensagem de commit:** assunto em português sem acento, `tipo(TEC-186): o que passou a ser verdade`, terminando com:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015j6C5C2Xrry2KLRm1y5Hvq
  ```

---

### Task 1: A janela, o catálogo de templates e a escolha (módulo puro)

**Files:**
- Create: `src/mobia/domain/followup/template.py`
- Test: `tests/unit/test_template_do_followup.py`

**Interfaces:**
- Consumes: `Ficha`, `reais_de` (`mobia.domain.agente.apresentacao`); `QuedaDePreco` (`mobia.domain.followup.mensagem`).
- Produces:
  ```python
  JANELA_DE_SERVICO: timedelta                      # 24h
  def dentro_da_janela(*, ancora_em: datetime, agora: datetime) -> bool
  @dataclass(frozen=True, slots=True)
  class TemplateAprovado:
      nome: str
      categoria: str
      idioma: str
  TEMPLATES: tuple[TemplateAprovado, ...]           # >= 3, uma por categoria
  CATEGORIA_QUEDA / CATEGORIA_IMOVEL_NOVO / CATEGORIA_CONVITE: str
  def categoria_da_novidade(*, ficha: Ficha | None, queda: QuedaDePreco | None) -> str
  def escolher_template(*, categoria: str, aprovados: frozenset[str]) -> TemplateAprovado | None
  def parametros_do_template(*, template: TemplateAprovado, ficha: Ficha | None, queda: QuedaDePreco | None) -> list[str]
  ```

**Módulo puro, sem I/O** — como `cadencia.py` e `mensagem.py`. `dentro_da_janela` usa `<` (borda estrita: aos 24h a janela fechou). `categoria_da_novidade` tem a MESMA precedência de `texto_do_followup` (queda > imóvel novo > convite), derivada do mesmo par — não é segunda fonte, e o comentário diz isso.

- [ ] **Step 1: Escrever os testes que falham**

```python
from datetime import UTC, datetime, timedelta

import pytest

from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.followup.mensagem import QuedaDePreco
from mobia.domain.followup.template import (
    CATEGORIA_CONVITE,
    CATEGORIA_IMOVEL_NOVO,
    CATEGORIA_QUEDA,
    JANELA_DE_SERVICO,
    TEMPLATES,
    categoria_da_novidade,
    dentro_da_janela,
    escolher_template,
    parametros_do_template,
)

ANCORA = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

FICHA = Ficha(
    id=__import__("uuid").UUID("11111111-1111-1111-1111-111111111111"),
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=59_000_000,
    quartos=4, vagas=2, area_util_m2=54,
    condominio_centavos=55000, diferencial=None, foto=None,
)
QUEDA = QuedaDePreco(imovel_id=FICHA.id, preco_antes_centavos=62_000_000, preco_agora_centavos=59_000_000)


def test_a_janela_e_de_24h_e_a_borda_e_estrita() -> None:
    assert JANELA_DE_SERVICO == timedelta(hours=24)
    assert dentro_da_janela(ancora_em=ANCORA, agora=ANCORA + timedelta(hours=4)) is True
    assert dentro_da_janela(ancora_em=ANCORA, agora=ANCORA + timedelta(hours=30)) is False
    # Cenario 4: a borda exata ja esta fora -- e a regra da Meta.
    assert dentro_da_janela(ancora_em=ANCORA, agora=ANCORA + timedelta(hours=24)) is False


def test_o_catalogo_mantem_no_minimo_tres_e_uma_por_contexto() -> None:
    """RN-13.6: 'no minimo 3 templates', um por contexto do follow-up."""
    assert len(TEMPLATES) >= 3
    categorias = {t.categoria for t in TEMPLATES}
    assert categorias >= {CATEGORIA_QUEDA, CATEGORIA_IMOVEL_NOVO, CATEGORIA_CONVITE}
    assert len({t.nome for t in TEMPLATES}) == len(TEMPLATES)  # nomes unicos


def test_a_categoria_segue_a_precedencia_de_texto_do_followup() -> None:
    assert categoria_da_novidade(ficha=FICHA, queda=QUEDA) == CATEGORIA_QUEDA
    assert categoria_da_novidade(ficha=FICHA, queda=None) == CATEGORIA_IMOVEL_NOVO
    assert categoria_da_novidade(ficha=None, queda=None) == CATEGORIA_CONVITE


def test_escolhe_o_template_da_categoria_quando_aprovado() -> None:
    aprovado = next(t for t in TEMPLATES if t.categoria == CATEGORIA_CONVITE)
    escolhido = escolher_template(categoria=CATEGORIA_CONVITE, aprovados=frozenset({aprovado.nome}))
    assert escolhido is not None
    assert escolhido.nome == aprovado.nome


def test_sem_o_template_da_categoria_aprovado_devolve_none() -> None:
    """Cenario 3: nenhum template aplicavel ao contexto -> None -> tarefa."""
    outra = next(t for t in TEMPLATES if t.categoria == CATEGORIA_QUEDA)
    # aprovado existe, mas e de OUTRA categoria
    assert escolher_template(categoria=CATEGORIA_CONVITE, aprovados=frozenset({outra.nome})) is None
    assert escolher_template(categoria=CATEGORIA_CONVITE, aprovados=frozenset()) is None


def test_os_parametros_da_queda_trazem_os_dois_precos() -> None:
    template = next(t for t in TEMPLATES if t.categoria == CATEGORIA_QUEDA)
    params = parametros_do_template(template=template, ficha=FICHA, queda=QUEDA)
    assert any("620.000" in p for p in params)
    assert any("590.000" in p for p in params)
    assert all(isinstance(p, str) for p in params)
```

- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/unit/test_template_do_followup.py` → `ModuleNotFoundError`.

- [ ] **Step 3: Implementar** `template.py`. `dentro_da_janela` com `<`. `categoria_da_novidade` reusando a precedencia de `texto_do_followup` (comentario dizendo que e derivada do mesmo par). `escolher_template` linear sobre `TEMPLATES` filtrando por categoria e `nome in aprovados`. `parametros_do_template` por categoria: queda -> `[legenda curta, reais_de(antes), reais_de(agora)]`; imovel novo -> `[titulo, bairro]`; convite -> `[]`. Sem número pelo modelo — `reais_de` produz os valores.

- [ ] **Step 4: Rodar e ver passar** — `pytest tests/unit -q`.

- [ ] **Step 5: Gates e commit**
  ```
  feat(TEC-186): a janela, o catalogo de templates e a escolha por contexto num modulo puro
  ```

---

### Task 2: A configuração dos templates aprovados

**Files:**
- Modify: `src/mobia/app/config.py` (`Settings`)
- Modify: `.env.example`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings.whatsapp_templates_aprovados: str = ""` e a property `templates_aprovados -> frozenset[str]`.

Nomes separados por vírgula, `strip()` por item, vazios descartados. Default vazio: **a mitigação do RT-03 em vigor** — sem operar a config, todo follow-up fora da janela vira tarefa. O comentário do campo diz isso.

- [ ] **Step 1: Teste que falha**

```python
def test_templates_aprovados_default_e_vazio() -> None:
    s = Settings(_env_file=None)
    assert s.templates_aprovados == frozenset()


def test_templates_aprovados_parseia_lista_por_virgula() -> None:
    s = Settings(_env_file=None, whatsapp_templates_aprovados="followup_queda, followup_convite ")
    assert s.templates_aprovados == frozenset({"followup_queda", "followup_convite"})
```

- [ ] **Step 2/3:** Rodar e ver falhar; implementar o campo `str` + a property (molde de `fuso_de_envio` / `templates_aprovados`), e acrescentar a linha comentada em `.env.example`.

- [ ] **Step 4/5:** `pytest tests/unit -k config`; gates; commit:
  ```
  feat(TEC-186): os templates aprovados pela Meta entram por configuracao, default vazio
  ```

---

### Task 3: O envio por template no adaptador do WhatsApp

**Files:**
- Modify: `src/mobia/domain/outbound/whatsapp.py` (`_deliver`)
- Modify: `tests/conftest.py` (`OutboundFake._deliver`)
- Test: `tests/integration/test_outbound_whatsapp.py` (ou o arquivo que já testa `_deliver`; confira o nome antes)

**Interfaces:**
- Consumes payload: `{"tipo": "template", "template": <nome>, "idioma": <code>, "parametros": list[str], "para": ..., "de": ...}`.

No `_deliver`, um ramo novo ao lado de `tipo == "imagem"`:
```python
elif payload.get("tipo") == "template":
    corpo["type"] = "template"
    template = {"name": payload["template"], "language": {"code": payload["idioma"]}}
    parametros = payload.get("parametros") or []
    if parametros:
        template["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in parametros]}
        ]
    corpo["template"] = template
```

**O `OutboundFake` precisa aceitar o payload de template**, senão `payload["texto"]` levanta `KeyError` (ver o fix wave da TEC-162 que ja trata `tipo=="imagem"`): acrescente um ramo que, para `tipo=="template"`, guarda `payload["template"]` em `entregues` (`payloads` ja captura o dicionario cru, que e onde os testes conferem `tipo`/`parametros`).

- [ ] **Step 1: Testes que falham** — um teste de que o corpo montado tem `type=template`, `template.name`, `template.language.code` e `components.body.parameters`; e um teste de que sem `parametros` não sai `components`. Confira como os testes de `_deliver` existentes injetam o `httpx.AsyncClient` dublê e copie o molde.

- [ ] **Step 2/3/4/5:** falhar; implementar o ramo + o `OutboundFake`; passar; gates; commit:
  ```
  feat(TEC-186): o adaptador do WhatsApp entrega por template aprovado fora da janela
  ```

---

### Task 4: A tarefa para o corretor (tabela, modelo, repositório, migration)

**Files:**
- Modify: `src/mobia/domain/followup/models.py` (`TarefaDeCorretor`)
- Modify: `src/mobia/domain/followup/repositorio.py` (`registrar_tarefa_de_corretor`, `listar_tarefas_de_corretor`)
- Create: `alembic/versions/0039_tarefas_de_corretor.py` (`down_revision = "0038"`)
- Test: `tests/integration/test_tarefas_de_corretor.py`

**Interfaces:**
- Produces:
  ```python
  MOTIVO_SEM_TEMPLATE = "sem_template_aprovado"
  async def registrar_tarefa_de_corretor(
      session, *, candidato: Candidato, tentativa: int, categoria: str, motivo: str
  ) -> TarefaDeCorretor | None    # None quando o ON CONFLICT absorveu
  async def listar_tarefas_de_corretor(session, ...) -> Sequence[TarefaDeCorretor]
  ```

Tabela `tarefas_de_corretor` append-only, molde de `followups`: `id`, `channel`, `conversation_key`, `ancora_em`, `tentativa_numero`, `categoria` (String(24)), `motivo` (String(32)), `created_at` (`clock_timestamp()`), UNIQUE `(channel, conversation_key, ancora_em, tentativa_numero)`, index por lead. Sem FK para `messages` (retenção, molde da 0015). `registrar_tarefa_de_corretor` usa `pg_insert(...).on_conflict_do_nothing(...).returning(...)` e **não** commita (a fronteira é de quem chama), no molde de `registrar_followup`.

**Acrescente `tarefas_de_corretor` a `TABELAS` em `tests/conftest.py`** (o `TRUNCATE ... CASCADE` de `banco_limpo`), senão o estado vaza entre testes.

- [ ] **Step 1: Testes que falham** — grava uma tarefa e a lê de volta; um segundo `registrar_tarefa_de_corretor` com a mesma tupla devolve `None` (idempotência); `listar_tarefas_de_corretor` devolve a linha.

- [ ] **Step 2: Falhar** (`ImportError`/tabela ausente — rode `alembic upgrade head` depois de escrever a migration).

- [ ] **Step 3: Implementar** modelo, migration, repositório, e o `TABELAS` do conftest.

- [ ] **Step 4/5:** passar; gates; commit:
  ```
  feat(TEC-186): a tarefa para o corretor nasce como tabela append-only, sem rota nem painel
  ```

---

### Task 5: A varredura decide o canal — texto livre, template ou tarefa

**Files:**
- Modify: `src/mobia/workers/jobs/sweep_followups.py`
- Test: `tests/integration/test_sweep_followups.py` (use `_lead`, `_ctx`, `DENTRO_DA_JANELA`, `CANAL`, `CONVERSA`, `OutboundFake`; o `_ctx` já monta `Settings` — passe `whatsapp_templates_aprovados` por lá quando o teste precisar de template aprovado).

**No bloco pós-commit**, depois de `de` estar resolvido e ANTES do `outbound.send` de hoje, ramifique por `dentro_da_janela(ancora_em=candidato.ancora_em, agora=agora)`:

- **Dentro da janela:** o caminho de hoje intacto — `redigir_abertura` + `texto_do_followup` + `outbound.send({"para","de","texto"})`. Emitir `followup.entregue` com `canal="livre"`.
- **Fora da janela:** `categoria = categoria_da_novidade(...)`; `template = escolher_template(categoria=categoria, aprovados=settings.templates_aprovados)`.
  - `template is None`: `registrar_tarefa_de_corretor(...)` + `session.commit()` + `log.warning("followup.tarefa_de_corretor", ...)`. **Nenhum `outbound.send`.**
  - senão: `parametros = parametros_do_template(...)`; `outbound.send({"para","de","tipo":"template","template":template.nome,"idioma":template.idioma,"parametros":parametros})` + `log.info("followup.entregue", canal="template", template=template.nome, ...)`.

`redigir_abertura` **não** roda no caminho fora da janela (D5). Todo o bloco continua dentro do mesmo `try` com os três `except` de hoje — `EnvioForaDaJanela` agora é o resíduo da D7 (posição dentro da janela recusada por skew), e o comentário do `except` deve deixar de dizer "quando a TEC-186 entrar" e passar a dizer o que a TEC-186 fez.

- [ ] **Step 1: Testes que falham** (os quatro cenários do Gherkin)

```python
async def test_dentro_da_janela_envia_texto_livre(session) -> None:
    """Cenario 2."""
    # lead QUENTE calado ha ~2h -> tentativa 1 -> dentro da janela
    ...
    assert outbound.entregues  # texto livre saiu
    assert outbound.payloads[-1].get("tipo") is None


async def test_fora_da_janela_com_template_aprovado_usa_template(session) -> None:
    """Cenario 1: 30h -> template; nenhuma mensagem livre tentada."""
    # lead QUENTE calado ha ~30h; aprova o template do contexto por _ctx
    ...
    assert outbound.payloads[-1]["tipo"] == "template"
    assert all("texto" not in p for p in outbound.payloads)  # nenhuma livre


async def test_fora_da_janela_sem_template_vira_tarefa(session) -> None:
    """Cenario 3: sem template aplicavel -> tarefa, nenhuma mensagem."""
    # aprovados vazio
    ...
    assert outbound.entregues == []
    assert await _linhas_de_tarefa(session) == 1


async def test_a_janela_conta_da_fala_do_lead_e_nao_da_conversa(session) -> None:
    """Cenario 4: fala do lead ha 30h + saida do agente ha 2h -> fora da janela."""
    ...
    assert outbound.payloads[-1]["tipo"] == "template"  # ou tarefa, se aprovados vazio
```

Complete a semeadura com `_lead` (a âncora é a última fala INBOUND) e uma mensagem OUTBOUND recente para o cenário 4. Para o cenário 1/4 com template, passe `whatsapp_templates_aprovados` no `Settings` do `_ctx` (acrescente um parâmetro ao helper, mantendo o default vazio).

- [ ] **Step 2/3/4:** falhar; implementar a ramificação; passar `pytest tests/integration -k followup`.

- [ ] **Step 5: Gates e commit**
  ```
  feat(TEC-186): a varredura decide o canal do followup pela janela -- livre, template ou tarefa
  ```

---

### Task 6: A emenda ao SRS e o fecho

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1: A emenda E-01 da RN-13.6** — item aninhado abaixo da RN-13.6 (linha ~401), no padrão das vizinhas, **sem** reescrever o texto de 22/08/2026. O texto está pronto na seção "Emendas ao SRS" do desenho. Acrescente a linha na tabela-índice de emendas no topo do SRS: `| E-01 | RN-13.6 | TEC-186 | 22/09/2026 |`.

- [ ] **Step 2: A listagem de comentários tocados**
  ```
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
  ```
  Releia cada `ALTERADO` e `VIZINHO`. Em especial: o docstring de `sweep_followups` (que fala do envio da TEC-184 e do `EnvioForaDaJanela` "quando a TEC-186 entrar"), o comentário do `except EnvioForaDaJanela`/`EnvioRecusado` no corpo, e a docstring de `FollowUp` (`models.py`). Relate o que decidiu sobre cada um.

- [ ] **Step 3: Os três gates e a suíte inteira, uma vez**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
  ```
  Uma execução verde basta; guarde o hash. Se **falhar**, repita sobre a mesma árvore antes de culpar a mudança.

- [ ] **Step 4: Commit**
  ```
  docs(TEC-186): a emenda E-01 da RN-13.6 fixa a janela pela ancora, o template por config e a tarefa do corretor
  ```

---

## Cobertura dos critérios de aceite

| Cenário do Gherkin | Onde é exercitado |
|---|---|
| 1 — 30h usa template, nenhuma livre | Task 1 (`dentro_da_janela`, `escolher_template`); Task 5 (`test_fora_da_janela_com_template_aprovado_usa_template`) |
| 2 — dentro da janela, mensagem livre | Task 5 (`test_dentro_da_janela_envia_texto_livre`) |
| 3 — sem template, vira tarefa | Task 1 (`test_sem_o_template_da_categoria_aprovado_devolve_none`); Task 4 (idempotência); Task 5 (`test_fora_da_janela_sem_template_vira_tarefa`) |
| 4 — a janela conta da fala do lead | Task 1 (`dentro_da_janela` sobre `ancora_em`); Task 5 (`test_a_janela_conta_da_fala_do_lead_e_nao_da_conversa`) |

**RN-13.6 "no mínimo 3 templates":** Task 1 (`test_o_catalogo_mantem_no_minimo_tres_e_uma_por_contexto`).

**Sem exercício, e declarado:** rota HTTP e painel de `tarefas_de_corretor` (E8); submissão/aprovação junto à Meta (externo ao código, RT-03).

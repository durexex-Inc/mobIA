# TEC-199 — Versionar prompts com rollback

**Desenho:** `docs/superpowers/specs/2026-09-26-tec-199-versionar-prompts-design.md`
**Branch:** `feat/tec-199-versionar-prompts`

---

### Task 1: O modelo e a renderização, sem I/O

**Files:** `src/mobia/domain/prompts/modelo.py`, `src/mobia/domain/agente/classificador.py`, `tests/unit/test_modelo_de_prompt.py`

- [ ] **Step 1: `AgenteDoPrompt`** (`AGENTE`, `INVESTIDOR`) e os marcadores `{assistente}` e `{tom}`.
- [ ] **Step 2: `MODELO_DO_AGENTE` e `MODELO_DO_INVESTIDOR`** em `classificador.py`, sem a cláusula; `renderizar(modelo, nome=, tom=)` anexa `CLAUSULA_DO_AGENTE`. `sistema_do_agente` passa a ser `renderizar(MODELO_DO_AGENTE, ...)`, e as duas constantes continuam iguais byte a byte.
- [ ] **Step 3: `validar_modelo(agente, texto)`** — marcadores obrigatórios, desconhecidos, vazio, teto de caracteres pelo pior caso do padrão (D3). Todas as violações juntas.
- [ ] **Step 4: `diff_entre(anterior, novo)`.**

---

### Task 2: As tabelas e a migration

**Files:** `alembic/versions/0059_versoes_de_prompt.py`, `src/mobia/domain/prompts/models.py`, `src/mobia/domain/auditoria/vocabulario.py`, `tests/conftest.py`

- [ ] **Step 1: `versoes_de_prompt` e `ativacoes_de_prompt`** (D4), com os CHECKs.
- [ ] **Step 2: `PROMPT_REVERTIDO`** no enum e no CHECK recriado de `acao`.
- [ ] **Step 3: as duas tabelas em `TABELAS`.**

---

### Task 3: O repositório

**Files:** `src/mobia/domain/prompts/repositorio.py`

- [ ] **Step 1: `modelos_vigentes(session)`** — um dict agente → texto, com o padrão onde não há ativação.
- [ ] **Step 2: `publicar`**, `reverter`, `listar_versoes`, `versao`, `historico`, `ativa`.

---

### Task 4: O turno usa os modelos vigentes

**Files:** `src/mobia/domain/context/montagem.py`, `src/mobia/domain/agente/classificador.py`

- [ ] **Step 1: `ContextoMontado.prompts`**, lido junto com a configuração, com queda para o padrão.
- [ ] **Step 2: `classificar` e `classificar_investidor`** renderizam o modelo do contexto.

---

### Task 5: As rotas e a trilha

**Files:** `src/mobia/api/routes/prompts.py`, `src/mobia/app/main.py`, `tests/unit/test_autorizacao_em_toda_rota.py`

---

### Task 6: Os cenários e as emendas

**Files:** `tests/features/test_versionar_prompts.py`, `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

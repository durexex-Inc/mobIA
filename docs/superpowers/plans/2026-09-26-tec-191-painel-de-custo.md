# TEC-191 — Exibir o painel de custo de IA

**Desenho:** `docs/superpowers/specs/2026-09-26-tec-191-painel-de-custo-design.md`
**Branch:** `feat/tec-191-painel-de-custo`

---

### Task 1: O orçamento mensal na configuração do agente

**Files:** `alembic/versions/0060_orcamento_de_ia.py`, `src/mobia/domain/configuracao/{models,vigente,repositorio}.py`, `src/mobia/api/routes/configuracao.py`, `tests/unit/test_configuracao_do_agente.py`

- [ ] **Step 1: a coluna `orcamento_mensal_usd`**, nula, com CHECK de positivo.
- [ ] **Step 2: o campo em `ConfiguracaoDoAgente`**, nulo no padrão, validado de 0,01 a 100.000.
- [ ] **Step 3: `orcamentoMensalUsd` na rota**, com `null` limpando.

---

### Task 2: A agregação

**Files:** `src/mobia/domain/metricas/custo.py`, `tests/unit/test_custo_de_ia.py`

- [ ] **Step 1: as contas puras** — orçamento proporcional, alerta em 80%, média nula com denominador zero.
- [ ] **Step 2: as consultas** — total, sem preço, conversas, tokens por modelo, qualificados, e o total sem filtros para o orçamento.

---

### Task 3: A rota e os cenários

**Files:** `src/mobia/api/routes/metricas.py`, `tests/unit/test_autorizacao_em_toda_rota.py`, `tests/features/test_painel_de_custo.py`, `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

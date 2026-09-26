# TEC-209 — Degradar com elegância sem perder mensagem

**Desenho:** `docs/superpowers/specs/2026-09-26-tec-209-degradar-com-elegancia-design.md`
**Branch:** `feat/tec-209-degradar-com-elegancia`

---

### Task 1: A cadeia da chamada principal

**Files:** `src/mobia/infra/anthropic.py`, `src/mobia/app/config.py`, `src/mobia/domain/context/montagem.py`, `src/mobia/domain/agente/classificador.py`, `tests/unit/test_cadeia_da_chamada_principal.py`, `tests/unit/test_orcamento_do_turno.py`

- [ ] **Step 1: tetos de 15 s, `PRAZO_DA_RESPOSTA_SEGUNDOS = 110`, as esperas e a lista do que retenta.**
- [ ] **Step 2: `PrazoDaResposta` no `ContextoMontado`.**
- [ ] **Step 3: `_chamar_principal`** — primário ×3, secundário ×1, sob o prazo; `ProvedorIndisponivel` ao esgotar.
- [ ] **Step 4: `_pior_turno()` com o prazo no lugar das duas fatias.**

---

### Task 2: O turno degrada na mesma passada

**Files:** `src/mobia/domain/agente/turno.py`, `tests/integration/test_provedor_indisponivel.py`

---

### Task 3: ESGOTADA e o worker morto

**Files:** `alembic/versions/0061_mensagem_esgotada.py`, `src/mobia/domain/messages/status.py`, `src/mobia/workers/jobs/process_message.py`

---

### Task 4: A DLQ na API

**Files:** `src/mobia/domain/usuarios/permissoes.py`, `src/mobia/api/routes/mensagens.py`, `src/mobia/app/main.py`

---

### Task 5: Os testes de caos e as emendas

**Files:** `tests/features/test_degradacao_graciosa.py`, `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

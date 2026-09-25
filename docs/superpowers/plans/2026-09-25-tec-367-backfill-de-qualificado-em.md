# TEC-367 — Backfill de `qualificado_em` e funil monótono

**Desenho:** `docs/superpowers/specs/2026-09-25-tec-367-backfill-de-qualificado-em-design.md`
**Branch:** `feat/tec-367-backfill-de-qualificado-em`

---

### Task 1: A migration do backfill

**Files:** `alembic/versions/0055_backfill_de_qualificado_em.py` (novo), `alembic/versions/0040_carimbo_de_qualificacao.py`

- [ ] **Step 1: `down_revision` conferido contra `alembic heads`**, e não presumido — é o que produziu a TEC-377.
- [ ] **Step 2: o UPDATE**, em SQL puro, sem importar `mobia.*` (D3). `MIN(created_at)` de `lead_score_audit` com `completude = 20`, por `(channel, conversation_key)`, e `WHERE qualificado_em IS NULL`.
- [ ] **Step 3: `downgrade` que NÃO desfaz.** Apagar os carimbos no downgrade destruiria também os que a aplicação escreveu depois — a coluna não distingue quem a preencheu. Um `pass` com a razão escrita é mais honesto que um `UPDATE` que perde dado.
- [ ] **Step 4: a docstring da `0040` deixa de dizer que não há de onde o backfill sair** (D1). Ela é a razão de a lacuna ter parecido irrecuperável, e corrigi-la é parte do conserto.

---

### Task 2: A guarda do número copiado

**Files:** `tests/unit/test_backfill_de_qualificacao.py` (novo)

- [ ] **Step 1:** ler a migration com `ast` — molde de `tests/unit/test_auditoria_vocabulario.py` — e conferir o literal contra `len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO`.
- [ ] **Step 2:** afirmar também a equivalência que o critério pressupõe: um estado com os quatro campos tem `esta_qualificado` verdadeiro **e** `completude` igual ao limiar; com três, os dois são falsos. É o que impede a regra de mudar de um lado só.

---

### Task 3: O funil monótono

**Files:** `src/mobia/domain/metricas/repositorio.py`

- [ ] **Step 1: `contar_etapas` passa a acumular** — cada etapa conta quem a alcançou ou alcançou posterior (D4). `AGENDADO` fica fora, por não ter fonte.
- [ ] **Step 2:** a docstring do módulo perde as duas causas de "acima de 100%", que deixam de existir, e ganha o que passou a ser verdade. **Não apagar o histórico** — dizer o que era e o que mudou.
- [ ] **Step 3: o comentário de `_coorte` sobre `handoffs.corretor_id`** (D5): a recusa com 422 continua, a justificativa muda.

---

### Task 4: Os testes do funil

**Files:** `tests/integration/test_funil_monotono.py` (novo), `tests/integration/test_migrations.py`

- [ ] **Step 1:** o cenário do Gherkin — nenhuma conversão entre consecutivas passa de 100%, montando as duas situações que produziam o defeito.
- [ ] **Step 2:** o lead que qualifica em UMA mensagem entra em `Em conversa`.
- [ ] **Step 3:** o backfill exercitado sobre a migration: linha antiga com trilha ganha a data; sem trilha continua nula; e o que a aplicação já carimbou não é tocado.

---

### Task 5: A emenda ao SRS

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1:** emenda à RN-17.2, aninhada, sem reescrever o texto de 22/08/2026: monotonia por construção, o resíduo da L1 e o prazo que a retenção de 12 meses impõe ao backfill.

---

### Verificação final

- [ ] Os três gates com o escopo do CI.
- [ ] `pytest -n 8 --dist loadfile`, uma vez, com o hash. **Esperada 1 falha conhecida**: `test_dois_leads_no_mesmo_slot` (TEC-378), que reprova por hora do dia e não por esta branch.
- [ ] `scripts/comentarios_tocados.py` e `--checar`.

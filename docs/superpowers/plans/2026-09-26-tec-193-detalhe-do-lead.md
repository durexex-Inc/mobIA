# TEC-193 — Abrir o detalhe do lead com transcrição completa

**Desenho:** `docs/superpowers/specs/2026-09-26-tec-193-detalhe-do-lead-design.md`
**Branch:** `feat/tec-193-detalhe-do-lead`

---

### Task 1: Permissão e vocabulário

**Files:** `src/mobia/domain/usuarios/permissoes.py`, `src/mobia/domain/auditoria/vocabulario.py`, testes unitários da matriz

- [ ] **Step 1: `VER_DETALHE_DO_LEAD`** para GERENTE e CORRETOR (ADMIN por construção), fora de `DE_ESCRITA`, sem LEITURA (D2).
- [ ] **Step 2: `CAMPO_DETALHE = "detalhe"` e `CAMPO_TRANSCRICAO = "transcricao"`** (D3). Fora de `CAMPOS_REVELAVEIS` — não se revelam, se leem.
- [ ] **Step 3: os testes da matriz** afirmam os papéis e a ausência em `DE_ESCRITA`.

---

### Task 2: O cursor da transcrição, sem I/O

**Files:** `src/mobia/domain/leads/transcricao.py` (a parte pura), `tests/unit/test_cursor_da_transcricao.py`

- [ ] **Step 1: `CursorDaTranscricao(em, message_id)`**, base64 de JSON, e `decodificar_cursor_da_transcricao` que levanta `FiltroInvalido`.
- [ ] **Step 2: `limite` 1..200, padrão 100** (D5).

---

### Task 3: A leitura da transcrição

**Files:** `src/mobia/domain/leads/transcricao.py`

- [ ] **Step 1: a consulta** por `(created_at DESC, id DESC)` com `LIMIT n+1`, depois do cursor por `row(created_at, id) <`, revertida antes de sair.
- [ ] **Step 2: a moderação** no `WHERE`: sem `bloqueada_em` para quem não é ADMIN; para ADMIN a fala retida sai com `retida=True` e sem conteúdo.
- [ ] **Step 3: cursor de mensagem de outro lead é `FiltroInvalido`.**

---

### Task 4: O detalhe

**Files:** `src/mobia/domain/leads/detalhe.py`

- [ ] **Step 1: um `DetalheDoLead` com os seis blocos e o resumo** (D4), uma consulta por bloco.
- [ ] **Step 2: o resumo do handoff mais recente**, decifrado com `aad_do_resumo_de_handoff`.
- [ ] **Step 3: listas vazias são `[]`.**

---

### Task 5: As rotas

**Files:** `src/mobia/api/routes/leads.py`, `tests/unit/test_autorizacao_em_toda_rota.py`

- [ ] **Step 1: 404 → recorte → registro comitado → leitura** (D2, D3), com `exigir_dono` para o CORRETOR.
- [ ] **Step 2: o mapa de rotas** ganha as duas linhas.

---

### Task 6: A trava de 60 s

**Files:** `src/mobia/api/routes/handoffs.py`

- [ ] **Step 1: 429 com `Retry-After` antes de `gerar_resumo`**, pelo `resumo_gerado_em` (D6).

---

### Task 7: Testes contra banco

**Files:** `tests/integration/test_detalhe_do_lead.py`, `tests/integration/test_transcricao_do_lead.py`, o teste de regeneração

- [ ] Os quatro cenários do Gherkin, a paginação sobre 300 falas, o lote com `created_at` igual, a moderação por papel, o recorte, a trilha e a trava.

---

### Task 8: SRS, gates e PR

- [ ] As quatro emendas, e as linhas do índice do SRS.
- [ ] Os três gates, `comentarios_tocados.py --checar`, a suíte.

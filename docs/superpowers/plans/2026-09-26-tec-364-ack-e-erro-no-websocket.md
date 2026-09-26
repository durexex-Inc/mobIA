# TEC-364 — Os eventos `ack` e `erro` e o formato dos imóveis no WebSocket do chat web

**Desenho:** `docs/superpowers/specs/2026-09-26-tec-364-ack-e-erro-no-websocket-design.md`
**Branch:** `feat/tec-364-ack-e-erro-no-websocket`

---

### Task 1: `ack` e `erro`

**Files:** `src/mobia/api/routes/widget.py`, os testes do widget, `tests/unit/literais_ao_lead.py`

- [ ] **Step 1: `ack {messageId}`** no lugar de `recebido {id}`.
- [ ] **Step 2: `erro {codigo, mensagem, messageId?}`**, com `MENSAGEM_DO_ERRO` e o `id` lido antes das recusas de texto.
- [ ] **Step 3: as frases na lista das guardas de acento e de promessa.**

---

### Task 2: O frame `imovel`

**Files:** `src/mobia/domain/agente/apresentacao.py`, `src/mobia/domain/agente/turno.py`, `src/mobia/domain/outbound/web.py`

- [ ] **Step 1: `card_de(ficha)`.**
- [ ] **Step 2: o payload da ficha leva `imovel` e `prosa`.**
- [ ] **Step 3: `WebOutbound` emite `imovel`, com ou sem foto.**

---

### Task 3: O contrato na spec da TEC-124

# TEC-374 — Marcar o desfecho da visita pelo dashboard

**Desenho:** `docs/superpowers/specs/2026-09-25-tec-374-desfecho-da-visita-pelo-dashboard-design.md`
**Branch:** `feat/tec-374-desfecho-da-visita-pelo-dashboard`

---

### Task 1: `Recusado` passa a dizer de qual estado se recusou

**Files:** `src/mobia/domain/agendamento/ciclo.py`

- [ ] **Step 1: `Recusado` ganha `status_atual: str | None = None`** (D3). Opcional, para os chamadores de `agendamento/conversa.py` não mudarem.
- [ ] **Step 2: `_transicionar` o preenche** no ramo de recusa — o `session.get` já acontece ali e a linha é descartada depois de um teste de `None`.
- [ ] **Step 3: a docstring de `Recusado` registra que o campo existe para a BORDA montar a frase**, e que o texto não mora aqui.

---

### Task 2: A guarda do horário, no domínio

**Files:** `src/mobia/domain/agendamento/ciclo.py`

- [ ] **Step 1: `MOTIVO_ANTES_DA_HORA`**, ao lado dos dois que já existem.
- [ ] **Step 2: a guarda entra em `marcar_realizado` e `marcar_nao_comparecimento`**, e **não** em `cancelar` nem em `remarcar` (D2) — desistir ou remarcar antes da hora é o caso comum dos dois.
- [ ] **Step 3: antes do UPDATE**, e não depois: a transição não pode acontecer e ser desfeita.
- [ ] **Step 4: o comentário de `_ORIGENS_DE` ganha a nota de que a origem legal deixou de ser a condição inteira** para duas das quatro. Sem isso, a tabela passa a mentir por omissão — é o defeito da TEC-146.

---

### Task 3: O relógio dos testes da TEC-172 deixa de afirmar o impossível

**Files:** `tests/integration/test_ciclo_do_agendamento.py`

- [ ] **Step 1: `DEPOIS = FIM + timedelta(hours=1)`**, com o comentário dizendo por que ele existe.
- [ ] **Step 2: só as chamadas de `marcar_realizado` e `marcar_nao_comparecimento` trocam para `agora=DEPOIS`.** As de `cancelar` e `remarcar` ficam em `AGORA`, que para elas é o relógio certo.
- [ ] **Step 3: um teste NOVO afirma a guarda** — `marcar_realizado` com `agora` antes de `inicio` recusa com `MOTIVO_ANTES_DA_HORA`, e o agendamento continua `CONFIRMADO`.
- [ ] **Step 4:** o mesmo para `marcar_nao_comparecimento`, e com a asserta que importa: **a penalidade NÃO foi somada**. Uma guarda que recusasse depois de penalizar seria pior que guarda nenhuma.

---

### Task 4: A rota

**Files:** `src/mobia/api/routes/agendamentos.py` (novo), `src/mobia/app/main.py`

- [ ] **Step 1: o módulo nasce com a docstring do molde de `handoffs.py`** — o dashboard não existe, estas rotas são o mecanismo que ele vai chamar, e até lá é por elas que os critérios de aceite são exercitados (D1).
- [ ] **Step 2: `_exigir_dono_do_agendamento`**, no molde de `handoffs.py::_exigir_dono_do`: só morde `CORRETOR`, e agendamento inexistente passa sem erro para o corpo responder 404 (D5).
- [ ] **Step 3: `POST /{agendamento_id}/realizado`** e **`POST /{agendamento_id}/nao-comparecimento`** (D4).
- [ ] **Step 4: o mapa de recusa → HTTP**, uma função só para as duas rotas: `INEXISTENTE` → 404, `ORIGEM_ILEGAL` e `ANTES_DA_HORA` → 409 (D6).
- [ ] **Step 5: as frases, COM acento** (fronteira do CLAUDE.md — é texto que uma pessoa lê). `ORIGEM_ILEGAL` nomeia o status atual: "este agendamento já foi cancelado". Um mapa status → frase, para `EXPIRADO`, `CANCELADO`, `REAGENDADO`, `REALIZADO`, `NO_SHOW` e `RESERVADO`.
- [ ] **Step 6: a resposta do no-show carrega o custo** (D7): `penalidade`, `penalidadeTotal` e `scoreNovo`. `PONTOS_POR_NAO_COMPARECIMENTO` sai do domínio, e não de um literal na rota.
- [ ] **Step 7: o router entra no `create_app`.**

---

### Task 5: As duas rotas no mapa de permissão

**Files:** `tests/unit/test_autorizacao_em_toda_rota.py`

- [ ] **Step 1:** duas linhas em `PERMISSAO_ESPERADA`, com `ATENDER_LEAD`. É o teste que pegou a TEC-195 e vai pegar esta se eu esquecer.

---

### Task 6: Os cenários do Gherkin

**Files:** `tests/features/test_desfecho_da_visita.py` (novo)

- [ ] **Step 1: cenário 1** — corretor marca realizada, agendamento fica `REALIZADO`, **e o score do lead não muda** (a asserta que separa as duas ações).
- [ ] **Step 2: cenário 2** — lead com score 68, no-show, score vai a 53, e a trilha registra `PENALIDADE` e `NAO_COMPARECIMENTO`. Os números da card, não outros.
- [ ] **Step 3: cenário 3, na forma de API** — agendamento daqui a duas horas recusa com 409, e o estado não muda (D7).
- [ ] **Step 4: cenário 4** — agendamento `CANCELADO` recusa com 409 e a mensagem **diz "cancelado"**, não um texto genérico.
- [ ] **Step 5: o corretor de outro recebe 403**, e o agendamento não muda.
- [ ] **Step 6: gerente marca o agendamento de qualquer corretor** — o outro lado do recorte.
- [ ] **Step 7: id inexistente é 404**, e não 403 — a guarda não pode virar oráculo ao contrário.
- [ ] **Step 8: `LEITURA` recebe 403** nas duas rotas.

---

### Task 7: A emenda ao SRS

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1:** RN-12.5 — numeração conferida no arquivo, não presumida.
- [ ] **Step 2:** a guarda do horário, a recusa que nomeia o status, e as duas rotas com os três códigos.
- [ ] **Step 3:** a lacuna do autor não registrado (D8), dita como lacuna e não como decisão tomada.
- [ ] **Step 4:** a linha na tabela-índice do topo.

---

### Task 8: Os gates e a suíte

- [ ] **Step 1:** `ruff check src tests alembic evals scripts`
- [ ] **Step 2:** `ruff format --check src tests alembic evals scripts`
- [ ] **Step 3:** `mypy`, sem argumento.
- [ ] **Step 4:** `scripts/comentarios_tocados.py` e `--checar`. O `VIZINHO` aqui é o comentário de `_ORIGENS_DE` e a docstring do módulo `ciclo.py`, que diz quais transições têm chamador — e passa a estar errada.
- [ ] **Step 5:** a suíte inteira, **uma vez**, com `--tb=short`.

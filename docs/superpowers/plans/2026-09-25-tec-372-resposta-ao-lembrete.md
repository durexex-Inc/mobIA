# TEC-372 — Ler a resposta do lead ao lembrete: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O lead responde "sim", "remarcar" ou "cancelar" ao lembrete de 24 horas e isso muda o agendamento de verdade — presença registrada, slot liberado com o corretor avisado, ou janelas novas oferecidas.

**Architecture:** Nenhum bloco novo no turno. `conversa.py::atender` ganha uma etapa **antes** das três da TEC-371, guardada por um predicado sobre o banco (`CONFIRMADO` + `lembrete_24h_em` preenchido + `inicio > agora`). A remarcação reusa a oferta de janelas da TEC-371, marcada por uma coluna nova em `janelas_propostas`. O e-mail de cancelamento vira job, e a porta de avisos ganha um segundo método.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (à mão), ARQ, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-tec-372-resposta-ao-lembrete-design.md`

## Global Constraints

- Texto ao lead: português **com acento** (TEC-267), constante `TEXTO_...` de módulo registrada em `tests/unit/literais_ao_lead.py`, mais o teste de tamanho. Nenhum promete o que ninguém faz (TEC-286).
- Comentários e docstrings em `src/`, `tests/` e migrations: português **sem acento**, exceto valor citado. Prosa em `docs/`: com acento. Citação de código em `.md` por âncora, nunca por número de linha.
- `agora` por parâmetro em tudo que decide tempo. Nenhum `datetime` ingênuo.
- **A faixa de `CANCELAR` é estrita, e o silêncio é o default** (D2). `"nao"` sozinho **não** cancela. Um teste afirma isso explicitamente — se ele for afrouxado, a assimetria foi reaberta sem ninguém decidir.
- O enfileiramento de qualquer aviso acontece **depois do commit** da transição.
- Os três gates antes de todo commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- Commit: `tipo(TEC-372): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Review Focus

- **Que "cancelar" fora da janela do lembrete não derrube nada** (D1, D2). É o quarto cenário do Gherkin e a única proteção contra o erro que não tem desfazer.
- **Que o original só vire `REAGENDADO` na escolha** (D4), e não ao pedir remarcação.
- **Que `IntegrityError` de `remarcar` vire oferta nova com o original intacto** (D5). A docstring de `remarcar` avisa que engoli-la deixa o original `REAGENDADO` sem sucessor.
- **Que a presença confirmada seja coluna e não status** (D3).

---

### Task 1: A coluna da presença e a da remarcação (migration 0052)

**Files:** `alembic/versions/0052_resposta_ao_lembrete.py` (novo), `src/mobia/domain/agendamento/models.py`, `src/mobia/domain/agendamento/propostas.py`, `tests/integration/test_janelas_propostas.py`

- [ ] **Step 1: Os testes que falham** — `remarcando_id` sobrevive à ida e volta em `propostas.py::gravar`/`ler`; `presenca_confirmada_em` nasce nula.

- [ ] **Step 2: A migration** — `0052`, à mão, `down_revision = "0051"` conferido contra `alembic heads`. `agendamentos.presenca_confirmada_em` e `janelas_propostas.remarcando_id` (FK nomeada para `agendamentos.id`), as duas nulas. A docstring carrega a D3: nulo é "não respondeu", não "não vai".

- [ ] **Step 3: Modelo e repositório** — o campo em `Proposta`, e `gravar` passando `remarcando_id`.

- [ ] **Step 4: Gates e commit** — `feat(TEC-372): a presenca confirmada e a remarcacao em curso tem onde morar`

---

### Task 2: O detector da resposta

**Files:** `src/mobia/domain/agendamento/deteccao.py`, `tests/unit/test_deteccao_de_agendamento.py`

- [ ] **Step 1: Os testes que falham**

  - `CONFIRMA`: "sim", "confirmado", "estarei lá", "pode contar comigo".
  - `REMARCAR`: "remarcar", "podemos mudar o horário?", "dá pra adiar?".
  - `CANCELAR`: "cancelar", "desmarcar", "não vou poder ir", "não vou conseguir ir".
  - **`None`**: `"nao"` sozinho, "não sei", "quanto custa?", vazio, pontuação.
  - Casando cancelar **e** remarcar → `REMARCAR` (D2: o caminho reversível vence).

- [ ] **Step 2: Implementar** — `respondeu_ao_lembrete`, reusando `_dispara` e a guarda de negação que já existem no módulo. A docstring carrega a D2 inteira: por que a faixa aqui é estrita enquanto a de `quer_agendar` é larga, e por que `"nao"` sozinho não basta.

- [ ] **Step 3: Gates e commit** — `feat(TEC-372): a resposta ao lembrete e reconhecida, com a faixa estrita`

---

### Task 3: A porta de avisos ganha o cancelamento

**Files:** `src/mobia/domain/agendamento/agendador.py`, `src/mobia/workers/jobs/avisar_cancelamento.py` (novo), `src/mobia/workers/main.py`, `src/mobia/domain/agente/turno.py`, mais os sítios de teste que constroem o Noop

- [ ] **Step 1: Os testes** — o job chama `avisar_cancelamento` com o canal de e-mail do `ctx`; o registro no worker; o `_job_id` fixo por agendamento, como no da confirmação.

- [ ] **Step 2: Renomear e acrescentar** — `AgendadorDeConfirmacaoPort` vira `AgendadorDeAvisosPort`, com `confirmacao(id)` e `cancelamento(id)`; `Noop` e `Arq` acompanham. O parâmetro de `executar_turno` vira `agendador_de_avisos`. `grep -rn "AgendadorDeConfirmacao" src tests` fecha a conta.

- [ ] **Step 3: O job fino** — molde de `workers/jobs/avisar_confirmacao.py`, que não faz nada além de chamar o domínio.

- [ ] **Step 4: Gates e commit** — `feat(TEC-372): o aviso de cancelamento ao corretor vira job`

---

### Task 4: A etapa do lembrete em `atender`

**Files:** `src/mobia/domain/agendamento/conversa.py`, `src/mobia/domain/agendamento/mensagens.py`, `tests/unit/literais_ao_lead.py`, `tests/integration/test_conversa_de_agendamento.py`

- [ ] **Step 1: Os testes que falham**

  - O predicado da D1: sem agendamento, com agendamento sem lembrete enviado, e depois de `inicio` — os três caem fora.
  - `CONFIRMA` carimba `presenca_confirmada_em` e **não** muda `status`.
  - `CANCELAR` chama `ciclo.py::cancelar`, e o desfecho carrega o id para quem chama enfileirar o e-mail.
  - `REMARCAR` oferece janelas com `remarcando_id` preenchido, e o original continua `CONFIRMADO`.
  - A escolha com `remarcando_id` chama `remarcar`; o original vira `REAGENDADO` e o sucessor aponta para ele.
  - `IntegrityError` na remarcação → oferta nova, original intacto (D5).

- [ ] **Step 2: Implementar** — a etapa 1 da D7, antes das três que já existem. Resultados novos (`PresencaConfirmada`, `Cancelou`) ao lado dos quatro atuais. Três textos ao lead: presença registrada, cancelamento feito, e o convite de remarcação que abre a oferta.

- [ ] **Step 3: Gates e commit** — `feat(TEC-372): a resposta ao lembrete confirma, cancela ou remarca`

---

### Task 5: O turno enfileira o aviso de cancelamento

**Files:** `src/mobia/domain/agente/turno.py`, `tests/integration/test_turno_agenda_visita.py`

- [ ] **Step 1: Os testes** — o enfileiramento do cancelamento acontece depois do commit (o espião que consulta o banco na hora da chamada, como na TEC-371); `ResultadoDoTurno` ganha os valores próprios.

- [ ] **Step 2: Implementar** — mais um ramo no bloco que já existe, no mesmo molde do `AgendamentoConfirmado`.

- [ ] **Step 3: Gates e commit** — `feat(TEC-372): o turno avisa o corretor depois de cancelar`

---

### Task 6: Os quatro cenários do Gherkin

**Files:** `tests/features/test_resposta_ao_lembrete.py` (novo)

- [ ] **Step 1: Um teste por cenário**, com o nome na docstring. O cenário 2 afirma o slot liberado com uma reserva nova no mesmo horário, contra a constraint real. O cenário 4 tem três casos (sem agendamento, sem lembrete, depois do início).

- [ ] **Step 2: Gates e commit** — `test(TEC-372): os quatro cenarios da resposta ao lembrete`

---

### Task 7: SRS e comentários tocados

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, mais o que a listagem apontar

- [ ] **Step 1: As emendas** — RN-12.2 (E-03), RN-12.3 (E-02) e CA-12.2 (E-01), como item aninhado, sem reescrever o texto de 22/08/2026. Mais as linhas no índice.

- [ ] **Step 2: Os comentários tocados**

  ```
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
  ```

  **O que esta card torna falso, e onde procurar:** "nada lê a resposta" em `agendamento/lembretes.py` e em `agendamento/remarcacao.py`; "nenhum caminho de produção chama isto" em `agendamento/cancelamento.py` e em `agendamento/ciclo.py`; o veto de `agendamento/deteccao.py`, que continua valendo mas passa a ter exceção nomeada; e a docstring de `workers/jobs/sweep_remarcacoes.py`, que diz que nada cancela.

  ```
  grep -rn "nada le a resposta\|Nada le a resposta\|nenhum caminho de producao" src docs
  ```

- [ ] **Step 3: Gates e commit** — `docs(TEC-372): o SRS e os comentarios dizem que a resposta e lida`

---

### Final: suíte inteira, uma vez

- [ ] **A suíte**

  ```
  ./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
  ```

  Uma execução verde basta; guardar o hash. Falhando, repetir sobre a mesma árvore antes de culpar a mudança; `CannotConnectNowError` em massa é o banco caído, e aí é por blocos.

- [ ] **Push, PR e card**

  PR contra `main`, comentário na TEC-372 e transição para **Em análise**. O comentário carrega: as emendas; a assimetria da D2 e o que ela custa em recall (o lead que escreve só "não" não é ouvido); que remarcar herda a lacuna da TEC-169 — sem janela o lead recebe texto genérico, e a visita antiga **continua de pé** porque o original só cai na escolha; e que `REALIZADO`/`NO_SHOW` seguem sem caminho.

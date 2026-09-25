# TEC-171 — Enviar lembretes de 24 e 2 horas: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um agendamento `CONFIRMADO` faz o lead receber dois lembretes — 24 horas antes e 2 horas antes —, cada um uma única vez, sem que reprocessamento duplique e sem que um agendamento que deixou de valer receba os lembretes antigos.

**Architecture:** Uma varredura `cron` (`sweep_lembretes`) que lê o estado de agora, no molde de `sweep_crm_pendentes`; a régua de "devido" e os textos num módulo puro (`domain/agendamento/lembretes.py`); duas colunas novas em `agendamentos` como marca de resolvido e um `kind` por agendamento e por lembrete como reserva; a janela de 24h da Meta muda de `domain/followup/template.py` para `domain/outbound/janela.py`, que é o lar que a docstring de `domain/outbound/horario.py` já previa.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (à mão), ARQ, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-tec-171-lembretes-de-agendamento-design.md`

## Global Constraints

- Texto que o lead recebe: português **com acento** (TEC-267), como constante `TEXTO_...` de módulo registrada em `tests/unit/literais_ao_lead.py` — é entrar nessa lista que põe o texto sob as guardas de acento e de promessa.
- Nenhum texto ao lead promete ação que ninguém executa (TEC-286): o lembrete de 24h **convida** a responder, e não diz que alguém remarca ou cancela por ele.
- Comentários e docstrings em `src/`, `tests/` e migrations: português **sem acento**, exceto valor citado.
- Prosa em `docs/`: com acento. Citação de código em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha.
- `agora` entra como parâmetro com fuso em tudo que decide tempo; produção não passa o argumento. Nenhum `datetime` ingênuo.
- A varredura **nunca escreve em `agendamentos.status`**. Um lembrete que falha não muda o agendamento.
- Migrations à mão. `ex_agendamentos_sem_sobreposicao` nunca é tocada, e uma proposta de `autogenerate` para derrubá-la é descartada.
- Os três gates antes de todo commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- Commit: `tipo(TEC-171): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. `git add` com caminhos explícitos.

## Review Focus

- **O teto de cada faixa** (D2). É a parte que um leitor apressado corta achando que é redundante. Sem ele, um worker parado três horas manda o lembrete de 24h junto com o de 2h.
- **`confirmado_em < inicio - antecedencia`** (D2). Sem essa condição, um agendamento confirmado em cima da hora recebe um "lembrete de 24 horas" minutos depois da confirmação.
- **A coluna gravada no `False` de `send`** (D3). É a divergência deliberada em relação à TEC-170, e o motivo é o cron: deixar nulo produz uma tentativa barrada a cada cinco minutos por até vinte e duas horas.
- **A exceção deixando a coluna nula** (D3), que é o oposto e também deliberado.
- **Que a mudança de lar de `dentro_da_janela` não altere a função** — nem assinatura, nem corpo, nem docstring.

---

### Task 1: A janela de 24h muda de lar

**Files:** `src/mobia/domain/outbound/janela.py` (novo), `src/mobia/domain/followup/template.py`, `src/mobia/workers/jobs/sweep_followups.py`, `tests/unit/test_followup_template.py`

- [ ] **Step 1: Mover a função**

  Criar `domain/outbound/janela.py` com `JANELA_DE_SERVICO` e `dentro_da_janela`, **idênticas** — copiar corpo e docstring sem editar uma palavra. A docstring do módulo novo diz por que ele existe: o mesmo argumento de `domain/outbound/horario.py`, que a regra é do canal e não do follow-up, e que sob `followup/` a próxima card escreveria a segunda cópia.

- [ ] **Step 2: Apagar de `followup/template.py` e importar**

  Remover as duas definições de lá e importar do lar novo. A docstring do módulo perde o parágrafo que descrevia a janela e ganha uma linha dizendo para onde ela foi.

- [ ] **Step 3: Atualizar os importadores**

  `grep -rn "dentro_da_janela\|JANELA_DE_SERVICO" src tests` e apontar todos para `mobia.domain.outbound.janela`. Os testes de `followup` que exercitam a janela mudam de import; os testes em si não mudam.

- [ ] **Step 4: Gates e commit**

  `refactor(TEC-171): a janela de 24h da Meta mora em outbound, onde o lembrete a acha`

---

### Task 2: A régua do lembrete e os textos

**Files:** `src/mobia/domain/agendamento/lembretes.py` (novo), `tests/unit/test_lembretes_de_agendamento.py` (novo), `tests/unit/literais_ao_lead.py`

- [ ] **Step 1: Escrever os testes que falham**

  Módulo puro, sem banco e sem rede. Cobrir:

  - **A faixa** (`lembrete_devido` ou equivalente, funções puras): devido no piso (`inicio - antecedencia`), devido no meio, **não** devido no teto (`inicio - proximo_marco`), **não** devido quando `confirmado_em >= inicio - antecedencia`.
  - **Os seis textos**: visita com imóvel, visita sem imóvel, reunião remota, nos dois lembretes. Data e hora por `data_e_hora_absolutas`, endereço por `endereco_de` — os dois reaproveitados de `domain/agendamento/mensagens.py`, nunca remontados.
  - **O de 24h oferece as três opções** (confirmar, remarcar, cancelar) e **o de 2h não pergunta nada**.
  - **O `kind`**: 32 caracteres exatos, um por agendamento e por lembrete, estável para o mesmo id, diferente entre os dois lembretes e entre dois agendamentos.
  - **`escolher_template_de_lembrete`**: `None` com `aprovados` vazio (o default do RT-03), o template certo por lembrete quando aprovado.

- [ ] **Step 2: Rodar para ver falhar**

  `./.venv/Scripts/python.exe -m pytest tests/unit/test_lembretes_de_agendamento.py --tb=short`

- [ ] **Step 3: Implementar**

  `domain/agendamento/lembretes.py`, puro. O vocabulário dos dois lembretes num lugar só — antecedência, marco seguinte, prefixo do `kind` e nome do template juntos, para que acrescentar um terceiro lembrete não seja editar quatro listas paralelas.

  Os prefixos são `lembrete_24_` e `lembrete_02_`, doze caracteres cada, mais os vinte primeiros do hex do id — a mesma conta de `kind_da_confirmacao`, e o comentário aponta para lá em vez de repeti-la.

- [ ] **Step 4: Registrar os seis literais**

  Acrescentá-los a `tests/unit/literais_ao_lead.py` e corrigir o teste de tamanho da lista. Sem isso, as guardas de acento e de promessa passam sem checar os textos novos.

- [ ] **Step 5: Rodar e commitar**

  `feat(TEC-171): a regua dos dois lembretes e os seis textos que o lead le`

---

### Task 3: Migration 0048 e as duas colunas

**Files:** `alembic/versions/0048_lembretes_do_agendamento.py` (novo), `src/mobia/domain/agendamento/models.py`, `tests/integration/test_agendamento_schema.py`

- [ ] **Step 1: A migration**

  `agendamentos.lembrete_24h_em` e `agendamentos.lembrete_2h_em`, `timestamptz NULL`, no molde exato da 0047. A docstring diz o que nulo significa — **"ainda não resolvido"**, e não "não entregue" —, porque é a distinção que a D3 do desenho decidiu e é onde esta card diverge da TEC-170.

  `down_revision = "0047"`. Conferir que nenhuma outra branch aberta já usou `0048` (TEC-370).

- [ ] **Step 2: O modelo**

  As duas colunas em `Agendamento`, com o comentário apontando para a migration e para a D3.

- [ ] **Step 3: Subir e conferir**

  `./.venv/Scripts/python.exe -m alembic upgrade head`, e `downgrade -1` / `upgrade head` para provar que a volta funciona.

- [ ] **Step 4: Gates e commit**

  `feat(TEC-171): cada lembrete tem a propria marca de resolvido em agendamentos`

---

### Task 4: A varredura

**Files:** `src/mobia/workers/jobs/sweep_lembretes.py` (novo), `tests/integration/test_sweep_lembretes.py` (novo)

- [ ] **Step 1: Escrever os testes de integração que falham**

  Postgres real, portas falsas (o `outbound` falso no molde dos testes de `sweep_followups`). Um caso por linha da lista de testes do desenho:

  - 26 horas, relógio em `inicio - 24h` → um envio, coluna gravada (CA-12.1).
  - Segunda passagem sobre o mesmo estado → nenhum envio novo.
  - Relógio em `inicio - 2h` → o segundo sai, o primeiro **não** sai de novo.
  - Relógio em `inicio - 90min`, o de 24h ainda nulo → o de 24h **não** sai (o teto da faixa).
  - Confirmado 3 horas antes do início → o de 24h nunca sai.
  - `EXPIRADO` e `RESERVADO` → nada sai.
  - Fora do horário de contato → **a varredura não toca o banco** e nada sai.
  - Fora da janela de 24h, sem template aprovado → nada sai, coluna gravada, `lembrete.sem_template`.
  - Fora da janela de 24h, com template aprovado → sai o template.
  - Lead em opt-out → nada sai, coluna **gravada**, e a passagem seguinte não tenta de novo.
  - Falha de canal → coluna **nula**, e a passagem seguinte tenta de novo.
  - Sem mensagem do lead na conversa → nada sai, coluna gravada.

- [ ] **Step 2: Rodar para ver falhar**

- [ ] **Step 3: Implementar**

  Molde de `sweep_crm_pendentes` para a consulta (`FOR UPDATE SKIP LOCKED`) e de `sweep_followups` para o laço (guarda de horário no topo, `try` por linha com `rollback` antes do `continue`, dois tetos por execução, `agora` por parâmetro).

  A consulta é uma só para os dois lembretes ou uma por lembrete — escolher a que deixa a condição da D2 legível, e escrever no comentário qual foi a razão. As três condições de tempo e o `status = 'CONFIRMADO'` não podem ficar espalhados.

  Os nomes de log, estáveis porque o monitoramento externo casa por nome: `lembrete.enviado`, `lembrete.recusado`, `lembrete.envio_falhou`, `lembrete.sem_template`, `lembrete.sem_ancora`, `sweep.lembretes_fora_do_horario`.

- [ ] **Step 4: Rodar os testes**

- [ ] **Step 5: Gates e commit**

  `feat(TEC-171): a varredura manda os lembretes de 24 e 2 horas uma vez cada`

---

### Task 5: O registro no worker

**Files:** `src/mobia/workers/main.py`, `tests/unit/test_worker_startup.py`

- [ ] **Step 1: Registrar**

  Em `functions` com `func(sweep_lembretes, keep_result=0)` — o resultado é um `int` que não serve a ninguém depois do log, a mesma razão do `sweep_sla`. Em `cron_jobs` de 5 em 5 minutos, `run_at_startup=False`, com o comentário que diz por que 5 e não 30 segundos (a menor janela desta regra é de duas horas).

- [ ] **Step 2: Os testes de startup**

  O arquivo já afirma coisas sobre o conjunto de jobs registrados; acrescentar o novo onde couber.

- [ ] **Step 3: Gates e commit**

  `feat(TEC-171): o relogio dispara a varredura de lembretes de cinco em cinco minutos`

---

### Task 6: Emendas ao SRS, comentários tocados e a card

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, mais o que a listagem apontar

- [ ] **Step 1: As emendas**

  Como item aninhado `Emenda E-nn (TEC-171, 25/09/2026)` abaixo da regra, **nunca** reescrevendo o texto de 22/08/2026:

  - **RN-12.2** — a varredura, a faixa com teto, o lembrete que não existe quando seu momento já passou, e que **nada lê a resposta do lead**. Mais: fora da janela de 24h o lembrete depende de template aprovado, e sem ele não sai.
  - **RN-13.3** — a guarda de horário passa a valer no lembrete, e a consequência: visita antes de `followup_horario_inicio + 2h` não recebe o de 2 horas.
  - **CA-12.1** — exercitado. O quinto cenário do Gherkin da card, não, com a razão.

- [ ] **Step 2: Os comentários que a branch tocou**

  ```
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
  ```

  Atenção aos `VIZINHO` em `followup/template.py` e `sweep_followups.py`, que a Task 1 editou por baixo — e à docstring de `domain/outbound/horario.py`, que nomeia a TEC-171 como um sítio que **deveria** aplicar a guarda. Depois desta card ela aplica: a frase muda.

  Conferir também o que `sweep_followups.py` diz sobre a TEC-171 ("será outro job sobre outra tabela e terá de lembrar de chamar o predicado") — passa a ser fato consumado, não previsão.

- [ ] **Step 3: Gates e commit**

  `docs(TEC-171): o SRS e os comentarios dizem o que a varredura de lembretes faz`

---

### Final: suíte inteira, uma vez

- [ ] **A suíte**

  ```
  ./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
  ```

  Uma execução verde basta. Guardar o hash junto com o resultado. Se ela **falhar**, repetir sobre a mesma árvore antes de culpar a mudança — e, se o Postgres cair (`CannotConnectNowError` em massa), rodar por blocos em vez de repetir o mesmo `-n`.

- [ ] **Push, PR e card**

  `git push -u origin feat/tec-171-lembretes-de-agendamento`, PR contra `main`, comentário na TEC-171 e transição para **Em análise**. O comentário carrega, nomeadamente: as emendas ao SRS; o quinto critério de aceite sem teste e por quê; que **nada lê a resposta do lead ao lembrete**; e que **sem template aprovado o lembrete de 24 horas praticamente não sai**.

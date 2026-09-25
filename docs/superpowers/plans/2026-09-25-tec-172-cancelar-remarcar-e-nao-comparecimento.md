# TEC-172 — Cancelar, remarcar e registrar não comparecimento: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um agendamento que não vai acontecer para de travar a agenda e para de mentir sobre o lead: cancelamento libera o slot e avisa o corretor, remarcação preserva o vínculo com o original, e não comparecimento custa 15 pontos de score com trilha.

**Architecture:** Quatro transições num módulo só (`agendamento/ciclo.py`), cada uma um `UPDATE` com a condição inteira no `WHERE` e a máquina de estados numa tabela única; a liberação do slot sai de graça da constraint de exclusão, que já é allowlist; o `-15` vira o **sexto fator** do score, persistido e acumulado, porque o score é derivado; o convite de remarcação é uma varredura no molde exato da `sweep_lembretes` da TEC-171.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (à mão), ARQ, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-tec-172-cancelar-remarcar-e-nao-comparecimento-design.md`

## Global Constraints

- Texto ao lead: português **com acento** (TEC-267), constante `TEXTO_...` de módulo registrada em `tests/unit/literais_ao_lead.py`. Nenhum promete ação que ninguém executa (TEC-286) — o convite de remarcação **convida**, não diz que alguém remarca.
- Comentários e docstrings em `src/`, `tests/` e migrations: português **sem acento**, exceto valor citado. Prosa em `docs/`: com acento. Citação de código em `.md` por âncora (`arquivo.py::Nome`).
- `agora` por parâmetro em tudo que decide tempo; produção não passa o argumento. Nenhum `datetime` ingênuo.
- **A constraint `ex_agendamentos_sem_sobreposicao` não é tocada.** Ela já é allowlist (`WHERE status IN ('RESERVADO','CONFIRMADO')`), e é isso que faz o slot ser liberado. Uma proposta de `autogenerate` para derrubá-la é descartada.
- As transições **não commitam**: a sessão é emprestada, como `confirmar`.
- Os três gates antes de todo commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- Commit: `tipo(TEC-172): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Review Focus

- **Que a constraint não tenha sido alterada** (D2). Se alguém a "consertou" para incluir os status novos, o slot deixa de ser liberado e a CA-12.2 morre em silêncio.
- **O piso zero do total** (D5), e que ele não seja aplicado dentro de `penalidade` — a coluna acumula de verdade; quem corta é `total`.
- **Que o recálculo SEGUINTE continue 53** (D5). É o teste que separa esta solução da que só grava na trilha.
- **As duas causas** (D5): `PENALIDADE` derivada do diff, `NAO_COMPARECIMENTO` informada pelo chamador. Colapsar as duas apaga metade da resposta da trilha.
- **O teto de 7 dias do convite** (D6): sem ele, o primeiro deploy convida cancelamentos antigos.

---

### Task 1: O vocabulário, as colunas e a migration 0050

**Files:** `alembic/versions/0050_ciclo_do_agendamento.py` (novo), `src/mobia/domain/agendamento/models.py`, `src/mobia/domain/context/models.py`, `tests/integration/test_agendamento_schema.py`

- [ ] **Step 1: A migration**

  As oito colunas da D9 mais o `DROP`/`ADD` do `ck_agendamentos_status`. `down_revision = "0049"`. A docstring diz por que `DEFAULT 0` nas duas de penalidade significa fato (nunca penalizado) e não ausência de fato — a distinção que a 0047 e a 0049 fazem do outro lado.

  **A constraint de exclusão não aparece na migration.** Escrever isso na docstring, porque a ausência dela é o que um revisor procura.

- [ ] **Step 2: Os modelos**

  `StatusDoAgendamento` ganha os quatro valores, com o comentário dos dois desvios da D1 (`PROPOSTO` não entra, `EXPIRADO` fica). As colunas em `Agendamento`, `LeadQualification` e `LeadScoreAudit`.

- [ ] **Step 3: Subir, descer e subir**

  `alembic upgrade head`, `downgrade -1`, `upgrade head`. Um teste em `test_agendamento_schema.py` afirma, com insert cru, que `CANCELADO` **não** dispara a exclusão contra um `CONFIRMADO` no mesmo horário — é a D2 provada contra o banco.

- [ ] **Step 4: Gates e commit**

  `feat(TEC-172): o agendamento tem os status do ciclo inteiro, e a penalidade tem coluna`

---

### Task 2: O sexto fator do score

**Files:** `src/mobia/domain/context/score.py`, `src/mobia/domain/context/auditoria.py`, `src/mobia/domain/context/repositorio.py`, `tests/unit/test_score.py`, `tests/unit/test_auditoria_do_score.py`

- [ ] **Step 1: Escrever os testes que falham**

  - `Score.total` subtrai a penalidade; piso zero (score 8, penalidade 15 → 0, nunca `-7`).
  - `causas_do_recalculo` devolve `CAUSA_PENALIDADE` quando só a penalidade se move.
  - O primeiro cálculo continua devolvendo só `PRIMEIRO_CALCULO`.

- [ ] **Step 2: Implementar**

  `Score.penalidade`, `calcular_score(..., penalidade=...)` lendo `estado.penalidade_pontos`, `CAUSA_PENALIDADE` no vocabulário e o par no `_CAUSA_POR_FATOR`. `registrar_recalculo` grava a coluna nova na trilha.

  **O piso mora em `total`, e não em `penalidade`**: a coluna acumula de verdade, e cortar na acumulação faria o segundo no-show de um lead já zerado não ser registrado.

- [ ] **Step 3: Conferir quem mais lê `Score`**

  `grep -rn "Score(" src tests` — todo construtor passa a precisar do sexto campo. `temperatura_de` não muda (usa `.total`), mas os testes que montam `Score` à mão, sim.

- [ ] **Step 4: Gates e commit**

  `feat(TEC-172): a penalidade e o sexto fator do score, e sobrevive ao recalculo`

---

### Task 3: As quatro transições

**Files:** `src/mobia/domain/agendamento/ciclo.py` (novo), `tests/unit/test_ciclo_do_agendamento.py` (novo), `tests/integration/test_ciclo_do_agendamento.py` (novo)

- [ ] **Step 1: Escrever os testes que falham**

  Unitários sobre a tabela de origens legais (`_ORIGENS_DE`); integração sobre o banco:

  - `cancelar` de `CONFIRMADO` e de `RESERVADO`; recusa de `CANCELADO`.
  - **CA-12.2**: depois de `cancelar`, `reservar` no mesmo horário e corretor **é aceita** — contra a constraint real.
  - `remarcar`: original `REAGENDADO`, novo com `origem_id`, os dois no mesmo commit; rollback deixa os dois como estavam.
  - `marcar_realizado` e `marcar_nao_comparecimento` de `CONFIRMADO`; recusa das origens ilegais.
  - `marcar_nao_comparecimento` soma 15 à penalidade e chama `registrar_recalculo` com `CAUSA_NAO_COMPARECIMENTO`: score 68 → 53, linha na trilha com as duas causas.
  - **O recálculo seguinte continua 53.**
  - Dois no-shows acumulam 30.

- [ ] **Step 2: Implementar**

  A máquina de estados numa tabela só. Resultado tipado, nunca `bool`. Sem commit.

- [ ] **Step 3: Gates e commit**

  `feat(TEC-172): cancelar, remarcar, realizar e nao comparecer sao quatro transicoes com origem legal`

---

### Task 4: O aviso de cancelamento ao corretor

**Files:** `src/mobia/domain/agendamento/mensagens.py`, `src/mobia/domain/agendamento/ciclo.py`, `tests/unit/test_mensagens_do_agendamento.py`, `tests/integration/test_ciclo_do_agendamento.py`

- [ ] **Step 1: Os testes**

  O `Aviso` de cancelamento leva data, hora, imóvel, identificação do lead e link; etiqueta `agendamento-cancelado`; a coluna própria impede o segundo envio; falha de canal deixa nulo e loga `agendamento.aviso_de_cancelamento_falhou`.

- [ ] **Step 2: Implementar**

  `aviso_de_cancelamento` ao lado de `aviso_ao_corretor`, com o comentário da D8 sobre por que a etiqueta **não** sai de `ETIQUETA_DE`.

- [ ] **Step 3: Gates e commit**

  `feat(TEC-172): o corretor recebe e-mail quando o agendamento e cancelado`

---

### Task 5: A varredura do convite de remarcação

**Files:** `src/mobia/domain/agendamento/remarcacao.py` (novo), `src/mobia/workers/jobs/sweep_remarcacoes.py` (novo), `src/mobia/workers/main.py`, `tests/unit/test_remarcacao.py` (novo), `tests/integration/test_sweep_remarcacoes.py` (novo), `tests/unit/literais_ao_lead.py`

- [ ] **Step 1: Os testes**

  A régua (piso 24h, teto 7 dias), o `kind`, o texto, e a varredura ponta a ponta — o mesmo conjunto de casos de `test_sweep_lembretes.py`, que é o molde.

- [ ] **Step 2: Implementar**

  Reusar o que já existe e **não** copiar: `horario_permite_envio`, `dentro_da_janela`, o padrão de `_marcar`. O que for idêntico à `sweep_lembretes` e valer para as duas é candidato a subir para um lugar comum — decidir na hora, e escrever a razão da escolha.

- [ ] **Step 3: Registrar no worker**

  `functions` com `keep_result=0`, `cron` de 5 em 5 minutos, `run_at_startup=False`, com o comentário do porquê do intervalo. Teste de registro, como o da TEC-171.

- [ ] **Step 4: Registrar o literal ao lead** e corrigir o teste de tamanho da lista.

- [ ] **Step 5: Gates e commit**

  `feat(TEC-172): a varredura convida a remarcar 24 horas depois do cancelamento`

---

### Task 6: Emendas ao SRS, comentários tocados e a card

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, mais o que a listagem apontar

- [ ] **Step 1: As emendas** — RN-12.3, RN-12.4, RN-12.5 e CA-12.2, como item aninhado `Emenda E-nn (TEC-172, 25/09/2026)`, sem reescrever o texto de 22/08/2026. Mais a linha no índice do topo.

- [ ] **Step 2: Os comentários tocados**

  ```
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
  ```

  Atenção ao que **previa** esta card e agora é fato: `context/auditoria.py` diz que `CAUSA_NAO_COMPARECIMENTO` está "sem produtor hoje" e nomeia a TEC-172; `handoff/vocabulario.py` fala do enum que nasceu completo; `outbound/horario.py` lista os sítios que aplicam a guarda e ganha o terceiro; `agendamento/models.py` e a docstring de `lembretes.py` falam de um vocabulário de três status.

- [ ] **Step 3: Gates e commit**

  `docs(TEC-172): o SRS e os comentarios dizem o que o ciclo do agendamento faz`

---

### Final: suíte inteira, uma vez

- [ ] **A suíte**

  ```
  ./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
  ```

  Uma execução verde basta; guardar o hash. Se **falhar**, repetir sobre a mesma árvore antes de culpar a mudança; se o Postgres cair (`CannotConnectNowError` em massa), rodar por blocos.

- [ ] **Push, PR e card**

  PR contra `main`, comentário na TEC-172 e transição para **Em análise**. O comentário carrega: as emendas; que **nada chama nenhuma das transições** ainda; que o lembrete da TEC-171 continua sem leitor de resposta; e a tensão da D7 — punir o no-show com score faz o sistema insistir menos com quem faltou.

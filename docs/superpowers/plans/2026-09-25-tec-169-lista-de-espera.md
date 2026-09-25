# TEC-169 — Lista de espera sem disponibilidade em 72 horas

**Desenho:** `docs/superpowers/specs/2026-09-25-tec-169-lista-de-espera-design.md`
**Branch:** `feat/tec-169-lista-de-espera`, a partir de `fix/tec-377-colisao-de-revisao-alembic`

A ordem abaixo é de dependência: a tabela antes de quem escreve nela, o vocabulário antes de quem o usa, a conversa antes da varredura que depende da fila existir.

---

### Task 1: O gatilho do handoff, e o comentário que mente

**Files:** `src/mobia/domain/handoff/vocabulario.py`, `tests/unit/test_handoff_vocabulario.py`

- [ ] **Step 1: `Gatilho.SEM_DISPONIBILIDADE`**, com `ETIQUETA_DE` = `"sem-disponibilidade"` e `PRIORIDADE_DE` = `NORMAL`. As três estruturas são paralelas e um valor sem entrada nas outras duas é `KeyError` em produção.
- [ ] **Step 2: corrigir o docstring do enum.** Ele afirma que acrescentar valor "custa migration"; `handoffs.gatilho` é `String(32)` sem CHECK, e a `0023_handoffs.py` só restringe `prioridade` e `status`. O texto novo diz o que é verdade: o custo é do `status`, e o gatilho é livre. Sem isso a próxima card herda o mesmo receio infundado (D4).
- [ ] **Step 3:** conferir se algum teste prende a cardinalidade do enum ou o conjunto de etiquetas; se prender, ele entra no passo, não depois.

---

### Task 2: A tabela e a migration 0054

**Files:** `alembic/versions/0054_lista_de_espera.py` (novo), `src/mobia/domain/agendamento/models.py`

- [ ] **Step 1: a migration**, à mão, `down_revision = "0053"` conferido contra `alembic heads` — e não presumido, que é exatamente o que produziu a TEC-377.
- [ ] **Step 2: as colunas da D3** — `channel`, `conversation_key`, `imovel_id` (FK nomeada, nulável), `oferecida_em` não nula, `aceita_em` / `recusada_em` / `avisada_em` nulas, `handoff_id` (FK nomeada para `handoffs.id`, nulável).
- [ ] **Step 3: o índice parcial** `uq_lista_de_espera_conversa_viva` sobre `(channel, conversation_key)` com `recusada_em IS NULL AND avisada_em IS NULL`. O `postgresql_where` do `Index` no modelo e o `postgresql_where` da migration têm de casar **exatamente** — a lição que o `ON CONFLICT` de `handoff/repositorio.py` documenta por extenso.
- [ ] **Step 4: o índice de varredura** sobre `aceita_em` com `avisada_em IS NULL`: é a consulta da D7, e ela roda a cada passagem do sweep.
- [ ] **Step 5: o modelo** `ListaDeEspera`, com os comentários carregando a D3 — por que `aceita_em` ordena e `oferecida_em` não.
- [ ] **Step 6: `TABELAS` em `tests/conftest.py`.** Tabela nova sem entrada ali não é truncada entre testes, e o vazamento aparece como flake em outro arquivo.

---

### Task 3: O domínio puro da espera

**Files:** `src/mobia/domain/agendamento/espera.py` (novo), `tests/unit/test_espera.py` (novo)

- [ ] **Step 1: o módulo sem I/O**, no molde de `remarcacao.py` e `lembretes.py` — é o que deixa a regra ser testada sem Postgres de pé.
- [ ] **Step 2: `HORIZONTE_ESTENDIDO = timedelta(days=14)`** com o comentário da D6, incluindo a declaração de que não é número medido.
- [ ] **Step 3: os dois textos ao lead** (`TEXTO_DA_LISTA_DE_ESPERA`, `TEXTO_DA_ESPERA_ACEITA`) e o do aviso de slot liberado. **Acentuados** — texto que o lead recebe (TEC-267).
- [ ] **Step 4: `template_do_aviso` e `kind_do_aviso`**, no molde de `remarcacao.py::template_do_convite`: o nome do template vive no catálogo e o envio depende de ele estar em `templates_aprovados`.
- [ ] **Step 5: registrar os textos em `tests/unit/literais_ao_lead.py`**, que é o que põe os dois sob a guarda de `test_promessa_ao_lead.py` e a de acento. **Este passo é o que faz a D5 valer** — um texto fora da lista não é checado por ninguém.

---

### Task 4: A oferta na conversa

**Files:** `src/mobia/domain/agendamento/conversa.py`, `src/mobia/domain/agendamento/repositorio.py`, `tests/integration/test_lista_de_espera.py` (novo)

- [ ] **Step 1: as funções de repositório** — gravar a oferta, ler a viva da conversa, marcar aceite/recusa/aviso, ler o primeiro da fila. **Não commitam**, como `registrar_handoff`: o commit é de quem chama.
- [ ] **Step 2: `_oferecer` passa a oferecer a lista** no lugar de `NadaAFazer()` quando `not janelas` — e **só quando `remarcando_id is None`** (D2). Um `Resultado` novo, `OfereceuEspera`, no molde dos sete que já existem.
- [ ] **Step 3: a etapa nova em `atender`**, entre `_reserva_pendente` e `ler_propostas` (D8). `confirmou` → aceita, grava `aceita_em`, chama `registrar_handoff` com o gatilho novo **na mesma transação**, devolve `AceitouEspera`. `recusou` → grava `recusada_em` e chama `_oferecer` com `HORIZONTE_ESTENDIDO`.
- [ ] **Step 4:** o comentário da cascata em `atender` ganha o degrau novo. Ele hoje explica por que o lembrete vem antes de tudo; a razão do lugar da espera (D8) entra junto, ou o próximo leitor reordena sem saber.

---

### Task 5: A varredura do slot liberado

**Files:** `src/mobia/workers/jobs/sweep_lista_de_espera.py` (novo), `src/mobia/workers/main.py`, `tests/integration/test_sweep_lista_de_espera.py` (novo)

- [ ] **Step 1: o job**, molde exato de `sweep_remarcacoes.py`: consulta estreita, regra de quando no módulo puro, âncora em sessão própria, guarda de horário e janela da Meta.
- [ ] **Step 2: a consulta** — cancelamento (`CANCELADO` ou `EXPIRADO`) com `inicio` entre agora e `agora + HORIZONTE`, cruzado com o primeiro da fila por `aceita_em` e `avisada_em IS NULL`.
- [ ] **Step 3: um aviso por slot** (D7), e `avisada_em` carimbada **mesmo quando o envio não sai por falta de template** — senão a fila trava atrás de um lead que nunca poderá ser avisado.
- [ ] **Step 4: os dois tetos por execução**, com a mesma conta das varreduras irmãs, e o registro no `main.py` com `job_timeout` igual.
- [ ] **Step 5: o teste dos dois leads na fila**, que é o terceiro cenário do Gherkin literal: o que aceitou antes é avisado primeiro.

---

### Task 6: Os cenários ponta a ponta e as emendas

**Files:** `tests/features/test_lista_de_espera.py` (novo), `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1: os quatro cenários do Gherkin** como testes de feature, com a fala literal da card onde ela existe — foi assim que a CA-11.1 foi exercitada na TEC-371.
- [ ] **Step 2: a Emenda E-02 à RN-11.5**, aninhada abaixo da E-01, **sem reescrever o texto de 22/08/2026**. Ela registra: a regra passa a ter código; a fila ordena por aceite; quem remarca não entra; o aviso é para um lead por slot e não promete o horário; a entrega segue presa à TEC-373.
- [ ] **Step 3: a emenda à RN-16.1** pelo gatilho novo.
- [ ] **Step 4:** conferir se a Emenda E-01 da RN-11.5 passou a mentir — ela afirma que "a regra continua sem código". A E-02 abaixo dela é o que a corrige; o texto da E-01 não se reescreve.

---

### Verificação final

- [ ] Os três gates, com o escopo do CI: `ruff check`, `ruff format --check`, `mypy`.
- [ ] `pytest -n 8 --dist loadfile`, **uma vez**, com o hash guardado.
- [ ] `scripts/comentarios_tocados.py` e `--checar`.
- [ ] `pytest -q -k margem_do_orcamento -s` — nenhum texto desta card entra no prompt de sistema, mas o custo de conferir é um comando.

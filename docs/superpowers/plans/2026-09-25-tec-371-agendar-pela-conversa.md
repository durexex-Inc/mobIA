# TEC-371 — Agendar a visita pela conversa: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O lead marca a visita conversando: pede horário, escolhe entre até 3 janelas absolutas, confirma, e existe um agendamento `CONFIRMADO` com os avisos enfileirados depois do commit.

**Architecture:** Um desvio determinístico em `turno.py::_executar_turno`, acima da chamada ao modelo e abaixo das guardas de silêncio, que delega a um orquestrador (`agendamento/conversa.py::atender`). O estado dos três turnos é lido do banco — propostas gravadas numa tabela nova, reserva na linha `RESERVADO` que a TEC-168 já escreve. Nenhuma peça do motor de agendamento muda: esta card só lhes dá chamador.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (à mão), ARQ, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-tec-371-agendar-pela-conversa-design.md`

## Global Constraints

- Texto ao lead: português **com acento** (TEC-267), constante `TEXTO_...` de módulo registrada em `tests/unit/literais_ao_lead.py`, mais o teste de tamanho da lista. Nenhum promete contato que ninguém faz (TEC-286) — ver a D8: a resposta para "sem janela em 72h" é **cair fora**, não prometer.
- Comentários e docstrings em `src/`, `tests/` e migrations: português **sem acento**, exceto valor citado. Prosa em `docs/`: com acento. Citação de código em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha.
- `agora` por parâmetro em tudo que decide tempo; produção não passa o argumento. Nenhum `datetime` ingênuo — `janelas.py::_exigir_fuso` é o precedente.
- **Nenhuma função de `domain/agendamento/` existente muda de assinatura.** Elas foram desenhadas para este chamador; se alguma parecer precisar de mudança, o desenho errou e a mudança vai ao PR declarada, não em silêncio.
- **`reservar_ou_alternativas`, e não `reservar`** (D7): é ela que devolve as alternativas da CA-11.2.
- O enfileiramento de `AgendadorDeConfirmacaoPort.agendar` acontece **depois do commit** de `confirmar`.
- Os três gates antes de todo commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- Commit: `tipo(TEC-371): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Review Focus

- **Que o desvio caia fora quando não reconhece** (D3, D5, D8). Um caminho de agendamento que responde a tudo sequestra a conversa; o teste que prova isso é o do lead perguntando o condomínio no meio da escolha.
- **Que o detector novo não seja `gatilhos_de`** (D2). As duas assimetrias de erro são inversas, e a `gatilhos.py` declara a dela por escrito. Deduplicá-los é regressão, não limpeza.
- **Que as propostas sejam lidas do banco e não recalculadas** (D4). Recalcular parece equivalente e produz "não encontrei esse horário" sobre um horário que nós oferecemos três minutos antes.
- **Que o turno C não mande texto** (D6). A mensagem de confirmação é do job (RN-12.1); duas mensagens dizendo a mesma coisa é o defeito.
- **Que o enfileiramento seja depois do commit**, provado por asserção de ordem e não por leitura do código.

---

### Task 1: A tabela das propostas

**Files:** `alembic/versions/0051_janelas_propostas.py` (novo), `src/mobia/domain/agendamento/models.py`, `src/mobia/domain/agendamento/propostas.py` (novo), `tests/conftest.py`, `tests/integration/test_janelas_propostas.py` (novo)

- [ ] **Step 1: Escrever os testes que falham**

  - Gravar três propostas e ler de volta na ordem do ordinal.
  - Uma rodada nova **substitui** a anterior: grava 3, grava 2, sobram 2.
  - Duas conversas não se enxergam.
  - `UNIQUE (channel, conversation_key, ordinal)` recusa a duplicata.

- [ ] **Step 2: A migration**

  `0051`, à mão. Conferir `down_revision` contra o head **real** (`alembic heads`) — a TEC-370 existe porque duas migrations nasceram com a mesma revisão e deixaram a `main` vermelha.

  Colunas conforme a D4. FK para `corretores` e FK nula para `imoveis`, nomeadas (`fk_janelas_propostas_corretor`, `fk_janelas_propostas_imovel`), como as de `agendamentos`.

  **Sem coluna de validade**: quem valida é o relógio contra `inicio`. Escrever a razão na docstring da migration.

- [ ] **Step 3: Modelo e repositório**

  `JanelaProposta` em `models.py`, ao lado de `Agendamento`. `propostas.py` com `gravar` (apaga e insere, na sessão emprestada, sem commit) e `ler` (ordenado por ordinal). O molde de "não commita" é `repositorio.py::reservar`.

- [ ] **Step 4: `TABELAS`**

  Acrescentar `janelas_propostas` em `tests/conftest.py`, com o comentário do porquê no estilo das vizinhas: é escrita pelos testes e pelo caminho de produção, e sem o truncate a rodada de um teste vira a oferta do próximo.

- [ ] **Step 5: Gates e commit**

  `feat(TEC-371): as janelas oferecidas ao lead ficam gravadas, e nao recalculadas`

---

### Task 2: Os três detectores

**Files:** `src/mobia/domain/agendamento/deteccao.py` (novo), `tests/unit/test_deteccao_de_agendamento.py` (novo)

- [ ] **Step 1: Escrever os testes que falham**

  `quer_agendar`:
  - Disparam: "quero agendar uma visita", "posso ver o apartamento amanhã?", "dá pra conhecer o imóvel?", "tem horário na quinta?", "quando posso visitar?".
  - **Não** disparam: "quero desmarcar a visita", "preciso remarcar", "vamos cancelar a visita", "não quero marcar visita", "vocês têm plantão de visita no fim de semana?" (fala real do corpus, `evals/corpus/compra.yaml`).

  `confirmou` / `recusou`: as duas faixas, e a negação (`não, pode ser` não é assentimento).

  Texto sem letra nenhuma devolve `False` nos três, sem levantar.

- [ ] **Step 2: Implementar**

  Normalização própria, como `gatilhos.py::_normalizar` e `optout/deteccao.py::_normalizar` — **três cópias deliberadas**, e a docstring diz por quê (a de `gatilhos.py` já escreve o argumento; repetir a razão aqui, não o link). `\b` no início de cada alternativa, `re.escape` nos literais.

  A docstring do módulo carrega a D2 inteira: por que este detector existe ao lado do `MOTIVO_VISITA` da `gatilhos.py`, e qual é a assimetria de cada um. É o comentário que impede a deduplicação futura.

- [ ] **Step 3: Gates e commit**

  `feat(TEC-371): o pedido de visita e reconhecido sem chamada paga`

---

### Task 3: A escolha da janela

**Files:** `src/mobia/domain/agendamento/escolha.py` (novo), `tests/unit/test_escolha_de_janela.py` (novo)

- [ ] **Step 1: Escrever os testes que falham**

  Sobre três propostas conhecidas:
  - Ordinal por extenso ("a primeira", "a segunda", "a terceira", "a última") e por dígito.
  - Hora: "às 11h", "11h", "pode ser as 11".
  - `Dia` com **uma** proposta dentro casa; com **duas**, `NaoEscolheu`.
  - Ordinal vence dia da semana: com três propostas, "segunda" é a segunda janela. O teste **documenta o custo**, não o esconde.
  - Ordinal fora de 1..N é `NaoEscolheu` — a guarda é `1 <= n <= len`, e não `try/except IndexError`, pelo motivo que `recomendacao.py::resolver_ordinais` já escreve (`lista[-1]` devolve o último em vez de levantar).
  - "quanto é o condomínio?" é `NaoEscolheu`.

- [ ] **Step 2: Implementar**

  Pura, sem I/O, no molde de `data_falada.py`. Nunca levanta para texto do lead. Reusa `data_falada::resolver` para a via da hora, e não reimplementa gramática de data.

- [ ] **Step 3: Gates e commit**

  `feat(TEC-371): o lead escolhe a janela por ordinal ou por hora`

---

### Task 4: Os textos ao lead

**Files:** `src/mobia/domain/agendamento/mensagens.py`, `tests/unit/literais_ao_lead.py`, `tests/unit/test_mensagens_do_agendamento.py`

- [ ] **Step 1: Os testes**

  Cada janela aparece por `data_e_hora_absolutas` — dia da semana, dia do mês e hora. Uma, duas e três janelas produzem texto correto (nada de "e" pendurado com uma só). Nenhum texto contém "amanhã", "que vem" ou promessa de contato.

- [ ] **Step 2: Implementar**

  As cinco constantes da D11, ao lado das da TEC-170, com acento. Montagem por função, como `texto_ao_lead`.

- [ ] **Step 3: Registrar** em `tests/unit/literais_ao_lead.py` e corrigir o teste de tamanho da lista — sem o registro, as guardas de acento e de promessa não olham para os textos novos.

- [ ] **Step 4: Gates e commit**

  `feat(TEC-371): o lead le as janelas com data e hora absolutas`

---

### Task 5: O orquestrador dos três turnos

**Files:** `src/mobia/domain/agendamento/conversa.py` (novo), `tests/integration/test_agendamento_pela_conversa.py` (novo)

- [ ] **Step 1: Escrever os testes que falham**

  `atender(session, *, channel, conversation_key, texto, estado, agora, agenda, visitas)` devolve um resultado tipado, nunca `None` ambíguo. Os desfechos:

  - `Ofereceu(texto, propostas)` — turno A, ou rodada nova depois de conflito, recusa ou reserva vencida. **O texto vem pronto**: as quatro variantes só se distinguem dentro de `atender`, e devolver só o tipo obrigaria o turno a refazer a mesma árvore de decisão — o oposto da D9, que quer o turno fino.
  - `Reservou(texto, reserva_id)` — turno B.
  - `Perguntou(texto)` — a data falada é ambígua, e `resolver` já traz a pergunta pronta (RT-10).
  - `Confirmou(agendamento_id)` — turno C, para quem chama enfileirar **depois do commit**.
  - `NadaAFazer()` — o turno segue normal. É o desfecho de: não pediu, não escolheu, não confirmou nem recusou, sem janela em 72h, sem corretor ativo, sem qualificação.

  Casos, com banco:
  - Turno A grava 3 propostas; o horizonte é 72h.
  - Turno B casa a escolha e reserva; a linha nasce `RESERVADO` com `reservado_ate` cinco minutos à frente.
  - Turno B com proposta cujo `inicio` já passou → `Ofereceu` com rodada nova, e não reserva no passado.
  - Turno B em conflito → `Ofereceu` com as alternativas, e as propostas gravadas são as novas.
  - Turno C confirma; `Expirado` → `Ofereceu`.
  - Recusa no turno C → `Ofereceu`.
  - Sem corretor ativo → `NadaAFazer`, e nada é gravado.

- [ ] **Step 2: Implementar**

  A ordem de leitura é a da D3: reserva viva → propostas → `quer_agendar`. Cada ramo é uma função curta; `atender` só decide qual.

  Imóvel: a última linha de `recomendacoes` desta conversa com `reacao_lead = INTERESSE`. Ausente é `None`, e a visita acontece assim mesmo — `TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL` existe desde a TEC-170 exatamente para isso.

  Não commita: a sessão é emprestada, como todo o resto de `domain/agendamento/`.

- [ ] **Step 3: Gates e commit**

  `feat(TEC-371): a conversa oferece, reserva e confirma a visita`

---

### Task 6: O desvio no turno, e a porta

**Files:** `src/mobia/domain/agente/turno.py`, `src/mobia/workers/main.py`, `src/mobia/workers/jobs/process_message.py`, `tests/integration/test_turno_agenda_visita.py` (novo), mais os testes que constroem `executar_turno`

- [ ] **Step 1: Os testes**

  - O desvio roda **abaixo** das guardas: lead silenciado por opt-out que pede visita continua silenciado; conversa assumida por corretor idem; fala recusada pela moderação de entrada não marca visita.
  - O desvio roda **acima** do modelo: no turno de agendamento o classificador **não é chamado** (fake que levanta se chamado).
  - `NadaAFazer` deixa o turno normal acontecer inteiro.
  - O enfileiramento acontece **depois do commit**: o fake de `AgendadorDeConfirmacaoPort` abre sessão própria e encontra a linha `CONFIRMADO`.

- [ ] **Step 2: Implementar**

  O bloco no lugar da D9 — depois do desvio de `_continuar_entrega`, antes de `montar_contexto`. Lê o estado com `ler_estado`, chama `atender`, commita, enfileira, entrega por `_entregar_texto_fixo` com `kind` e `subagent` próprios (o default rotularia a telemetria como "moderacao", que é o defeito que a docstring daquela função já registra).

  `ResultadoDoTurno` ganha `"agendamento_confirmado"` e `"agendamento_oferecido"`, cada um com o comentário que diz por que **não** reusa nenhum dos existentes — é a disciplina que todos os valores daquele `Literal` seguem.

  Comentário no bloco: por que ele está **ali** na ordem, e por que a função não é partida nesta card (D9).

- [ ] **Step 3: A porta na assinatura**

  `agendador_de_confirmacao: AgendadorDeConfirmacaoPort` em `executar_turno` e `_executar_turno`; `AgendadorDeConfirmacaoNoop` nos testes; `AgendadorDeConfirmacaoArq(pool)` no `startup` do worker, ao lado do que já existe para a varredura.

  `grep -rn "executar_turno(" src tests` — todo chamador passa a precisar do argumento.

- [ ] **Step 4: Gates e commit**

  `feat(TEC-371): o turno agenda a visita antes de chamar o modelo`

---

### Task 7: Os quatro cenários do Gherkin

**Files:** `tests/features/test_agendamento_pela_conversa.py` (novo)

- [ ] **Step 1: Um teste por cenário**, com o nome do cenário na docstring:

  1. "pode ser quinta de manhã?" → até 3 janelas **daquela quinta**, cada uma com data e hora absolutas. A asserção é sobre o **texto entregue**, não sobre a lista devolvida: é o que o lead lê que a CA-11.1 governa.
  2. Escolha → confirmação → linha `CONFIRMADO` e enfileiramento depois do commit.
  3. Reserva vencida → `Expirado` → o lead recebe horários de novo.
  4. Dois leads no mesmo slot → um `CONFIRMADO`, o outro com alternativas.

- [ ] **Step 2: Gates e commit**

  `test(TEC-371): os quatro cenarios do agendamento pela conversa`

---

### Task 8: Emendas ao SRS, comentários tocados e o que virou falso

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, mais o que a listagem apontar

- [ ] **Step 1: As emendas** — RN-11.1, RN-11.3, RN-11.4, RN-11.5, CA-11.1, CA-11.2, RN-12.1, RN-12.2 e RN-17.1, como item aninhado `Emenda E-nn (TEC-371, 25/09/2026)`, sem reescrever o texto de 22/08/2026. Mais as linhas no índice do topo.

  Numerar conferindo as emendas que já existem em cada regra — RN-12.1 já tem E-01 a E-03.

- [ ] **Step 2: Os comentários tocados**

  ```
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
  ./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
  ```

  **Esta card torna falsa uma frase que está escrita em pelo menos seis lugares**, e encontrá-los é metade do trabalho desta task. A frase é "nenhum caminho de produção chama isto ainda" / "`turno.py` não importa nada de `agendamento/`", e ela aparece em: `agendamento/data_falada.py` (docstring de módulo), `agendamento/confirmacao.py` (docstring de módulo), `agendamento/agendador.py` (docstring de módulo e da classe `AgendadorDeConfirmacaoArq`), `agendamento/repositorio.py`, `handoff/vocabulario.py` (o `Gatilho.AGENDAMENTO_CONFIRMADO` — que **continua** sem chamador, então essa parte fica, mas a justificativa muda de contexto) e no SRS.

  Varrer com `grep -rn "nenhum caminho de producao\|nao importa nada de" src docs` e reconferir cada um. Docstring de módulo é a categoria que a TEC-283 acrescentou justamente porque ninguém a relê.

- [ ] **Step 3: Gates e commit**

  `docs(TEC-371): o SRS e os comentarios dizem que a conversa agenda`

---

### Final: suíte inteira, uma vez

- [ ] **A suíte**

  ```
  ./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
  ```

  Uma execução verde basta; guardar o hash. Se **falhar**, repetir sobre a mesma árvore antes de culpar a mudança. Dezenas de `CannotConnectNowError` de uma vez é o banco caído — rodar por blocos, não repetir o mesmo `-n`.

- [ ] **Push, PR e card**

  PR contra `main`, comentário na TEC-371 e transição para **Em análise**. O comentário carrega:

  - As emendas ao SRS, nomeadas.
  - **A lacuna da D8**: sem janela nas próximas 72 horas o lead recebe uma resposta genérica e nada registra que ele pediu. É decisão de produto, e é a TEC-169.
  - **Reunião remota continua sem caminho** (D2): todo agendamento nascido da conversa é `VISITA_PRESENCIAL`.
  - **O turno C não manda mensagem** (D6): com o worker parado, o "sim" do lead fica sem resposta visível embora o agendamento já esteja confirmado.
  - **`_executar_turno` não foi partida** (D9), com a razão, e o pedido de uma card própria.
  - Que os indicadores de agendamento do painel continuam `null` embora o motivo declarado tenha deixado de valer (Emenda E-04 da RN-17.1) — mentir por omissão é pior do que era, e quem decide é a E8.

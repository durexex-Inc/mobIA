# TEC-376 — Os quatro indicadores de agendamento no funil

**Desenho:** `docs/superpowers/specs/2026-09-25-tec-376-indicadores-de-agendamento-no-funil-design.md`
**Branch:** `feat/tec-376-indicadores-de-agendamento-no-funil`

---

### Task 1: O vocabulário perde os dois conjuntos de ausência

**Files:** `src/mobia/domain/metricas/vocabulario.py`

- [ ] **Step 1: apagar `SEM_FONTE` e `INDICADORES_SEM_FONTE`** (D8), e não esvaziá-los.
- [ ] **Step 2: acrescentar `INDICADORES_DE_AGENDAMENTO`** — as mesmas quatro chaves, agora como *o que a rota publica*, e não como *o que falta*. A rota precisa da lista para nomear as chaves do corpo.
- [ ] **Step 3: a docstring do módulo perde o parágrafo "Nao existe tabela de agendamento neste repo"**, que passa a ser falso, e ganha no lugar a unidade de contagem da D3 — etapa conta lead, indicador conta compromisso.

---

### Task 2: `montar_funil` deixa de ter etapa cega

**Files:** `src/mobia/domain/metricas/calculo.py`

- [ ] **Step 1:** `quantidade` sai de `quantidades.get(etapa, 0)` para todas as seis; `disponivel` passa a ser `True` fixo, com o porquê de o campo ficar (D8).
- [ ] **Step 2: a docstring de `_conversao` passa a declarar DUAS origens de `None`, e não três.** A segunda — "a anterior não tem número" — deixa de ser alcançável por dado, e o ramo `anterior is None` fica por contrato de tipo. Comentário que descreve caso impossível é o defeito da TEC-146 ao contrário.
- [ ] **Step 3:** a docstring de `montar_funil` perde a frase sobre `SEM_FONTE` sobrepor o que veio do banco.

---

### Task 3: A consulta da etapa `Agendado`

**Files:** `src/mobia/domain/metricas/repositorio.py`

- [ ] **Step 1: o conjunto cru `agendados`** — join de `Agendamento` na coorte por `(channel, conversation_key)`, com `status != EXPIRADO` (D5). Conta leads distintos, e o `UNION` da acumulação já deduplica.
- [ ] **Step 2: `AGENDADO` entra em `cruas`** entre `RECOMENDADO` e `HANDOFF_ACEITO` — a posição é o que faz `Recomendado` crescer e `Agendado ⊆ Recomendado` valer por construção (D9).
- [ ] **Step 3: a docstring de `contar_etapas` perde o parágrafo que explica a ausência de `AGENDADO`** e ganha, no lugar, o `EXPIRADO` fora e a razão. É o `VIZINHO` mais provável desta branch.

---

### Task 4: Os quatro indicadores

**Files:** `src/mobia/domain/metricas/repositorio.py`

- [ ] **Step 1: quatro campos novos em `Indicadores`** — `agendamentos_criados: int`, `agendamentos_confirmados: int`, `agendamentos_realizados: int`, `taxa_no_show: float | None`. A docstring da dataclass perde o "Os quatro de agendamento NAO estao aqui".
- [ ] **Step 2: uma consulta só, com quatro agregações filtradas**, no molde do `func.count().filter(...)` que `sla_handoff_cumprido_pct` já usa — quatro `SELECT` sobre a mesma junção seriam quatro idas ao banco para o mesmo conjunto de linhas.
  - `criados`: `count().filter(origem_id IS NULL, status != EXPIRADO)`
  - `confirmados`: `count().filter(origem_id IS NULL, confirmado_em IS NOT NULL)`
  - `realizados`: `count().filter(realizado_em IS NOT NULL)`
  - `no_show`: `count().filter(nao_compareceu_em IS NOT NULL)`
- [ ] **Step 3: o comentário cita `ciclo.py::_ORIGENS_DE` pelo nome** (D4) — é de lá que sai o direito de não usar CTE recursivo, e uma mudança lá derruba os três números daqui.
- [ ] **Step 4:** `taxa_no_show = no_show / (realizados + no_show)`, `None` no denominador zero, com o paralelo ao SLA escrito (D6).

---

### Task 5: A rota publica os quatro

**Files:** `src/mobia/api/routes/metricas.py`

- [ ] **Step 1:** as quatro chaves entram em `corpo_dos_indicadores` com valor; o `dict.fromkeys(INDICADORES_SEM_FONTE)` sai.
- [ ] **Step 2:** `"indisponiveis": []`, com o comentário dizendo por que a chave fica (D8).
- [ ] **Step 3: o comentário "Os quatro de visita saem SEMPRE, e sempre nulos" some.** Ele é o `ALTERADO` óbvio; a docstring do módulo não fala de agendamento e não precisa mudar.

---

### Task 6: Os testes que afirmavam a ausência

**Files:** `tests/unit/test_calculo_do_funil.py`, `tests/integration/test_repositorio_de_metricas.py`, `tests/integration/test_rota_de_metricas.py`, `tests/integration/test_funil_monotono.py`, `tests/features/test_painel_de_funil.py`

- [ ] **Step 1: `test_calculo_do_funil.py`** — `CHEIO` ganha `AGENDADO`; `test_a_etapa_sem_fonte_sai_nula_e_nunca_zero` e `test_a_etapa_depois_da_indisponivel_nao_tem_conversao` **viram o contrário**: a etapa sai com número, e a conversão de `Handoff aceito` existe.
- [ ] **Step 2: `test_repositorio_de_metricas.py::test_agendado_nao_aparece_nas_contagens`** vira `test_agendado_conta_os_leads_com_visita_marcada`.
- [ ] **Step 3: `test_rota_de_metricas.py`** — `test_a_etapa_agendado_sai_indisponivel` e `test_os_quatro_indicadores_de_visita_saem_nulos_e_listados` viram as afirmações positivas, com `indisponiveis == []`.
- [ ] **Step 4: `test_funil_monotono.py`** — a docstring que diz "`AGENDADO` e pulado" deixa de valer; o teste passa a exercitar um lead com visita marcada, para a propriedade cobrir a etapa nova.
- [ ] **Step 5: `test_painel_de_funil.py::test_o_painel_declara_que_nao_sabe_de_visitas`** é substituído pelo teste da **CA-17.1**, que duas emendas registraram como não exercitável. Ele agora é o critério de aceite de verdade: agendamento criado → o contador reflete.

---

### Task 7: Os cenários do Gherkin da card

**Files:** `tests/integration/test_indicadores_de_agendamento.py` (novo)

- [ ] **Step 1: criados e confirmados** — três agendamentos da coorte, dois confirmados → `3` e `2`.
- [ ] **Step 2: a taxa de no-show** — quatro com horário passado, três `REALIZADO` e um `NO_SHOW` → `0.25` (D6).
- [ ] **Step 3: a remarcação não conta duas vezes** — original `REAGENDADO` e sucessor `REALIZADO` → `criados == 1`, `realizados == 1`. Montado por `ciclo.py::remarcar`, e não por `INSERT` à mão: o teste tem de quebrar se a máquina de estados mudar.
- [ ] **Step 4: a cadeia A→B→C** — não está no Gherkin e é o que a D4 promete; `criados == 1`.
- [ ] **Step 5: `EXPIRADO` fora** (D5), e `RESERVADO` vivo dentro.
- [ ] **Step 6: denominador zero dá `None`** — um `CONFIRMADO` de horário passado, sem desfecho, não vira `0.0`.
- [ ] **Step 7: o recorte é de coorte** (D2) — agendamento de lead nascido fora do período não conta.

---

### Task 8: As três emendas ao SRS

**Files:** `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`

- [ ] **Step 1:** RN-17.1 → **E-05**; RN-17.2 → **E-04**; CA-17.1 → **E-03**. Numeração conferida no arquivo, não presumida.
- [ ] **Step 2:** item aninhado sob a regra, sem tocar no texto de 22/08/2026.
- [ ] **Step 3:** a tabela-índice do topo ganha as três linhas — ela já se declara incompleta, e não a consertar de novo seria escolher aumentar o buraco.

---

### Task 9: Os três gates e a suíte

- [ ] **Step 1:** `ruff check src tests alembic evals scripts`
- [ ] **Step 2:** `ruff format --check src tests alembic evals scripts` — gate separado do linter.
- [ ] **Step 3:** `mypy`, sem argumento.
- [ ] **Step 4:** `scripts/comentarios_tocados.py` e `--checar` — a branch mexe em módulo muito comentado, e a `VIZINHO` aqui é o ponto inteiro.
- [ ] **Step 5:** a suíte inteira, **uma vez**, com `--tb=short`.

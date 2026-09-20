# TEC-270 — O relatório diz qual turno alucinou: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render no relatório do gate os turnos que citaram cifra ou código sem base — dado que já é coletado e descartado antes do `render`.

**Architecture:** `ResumoDaInvencao` + `resumo_da_invencao` em `metricas.py`, no molde de `ResumoDoFormato`; `_secao_de_invencao` em `relatorio.py`, no molde de `_secao_de_formato` mas sem a prosa; uma linha no runner ligando os dois.

**Tech Stack:** Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-270-qual-turno-alucinou-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m mypy`.
  **`evals/` está no escopo do linter e do formatador** — é um dos motivos de aquele escopo não ser `src tests`.
- **Comentários e docstrings em `src/`: português SEM acento**, exceto valor citado. O relatório em si é artefato de diagnóstico interno, não texto ao lead: os literais dele seguem a convenção do código, sem acento, como as seções vizinhas já fazem (`## Formato da resposta (diagnostico)`).
- **Nada de chamada paga.** `evals/test_acuracia_de_intencao.py` só roda contra a API sob demanda; esta branch se verifica inteira por testes unitários em `tests/unit/`, que é onde as outras seções do relatório já são testadas.
- **Não mude `divergencias_de` nem a guarda da TEC-161.** O que conta como alucinação está fora do escopo — aqui só se mostra o que já é contado. Se algo em `domain/agente/citacao.py` precisar mudar, pare.
- **Mensagem de commit:** `tipo(TEC-270): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Loop:** `./.venv/Scripts/python.exe -m pytest tests/unit -q` (~6s, sem Docker).

---

### Task 1: O resumo, no molde do vizinho

**Files:**
- Modify: `src/mobia/evals/metricas.py` (perto de `ResumoDoFormato`/`resumo_do_formato`)
- Test: `tests/unit/test_evals_metricas.py`

**Interfaces:**
- Produces: `ResumoDaInvencao(respostas: int, turnos: list[InvencaoObservada])` e `resumo_da_invencao(invencoes, respostas) -> ResumoDaInvencao`.

- [ ] **Step 1: Testes primeiro**

Dois: o resumo de uma execução com invenção carrega os turnos e o total; o de uma execução limpa carrega zero turnos e o total mesmo assim. O segundo é o que prende a razão de o campo `respostas` existir.

- [ ] **Step 2: Escrever o resumo**

O docstring registra por que `respostas` está aqui: sem o total, a seção não consegue dizer "0 de 147" e desaparece na execução limpa — que é o caso em que o leitor mais precisa saber que a medição rodou.

- [ ] **Step 3: Gates e commit**

`feat(TEC-270): o resumo da invencao carrega os turnos e o total medido`

---

### Task 2: A seção do relatório

**Files:**
- Modify: `src/mobia/evals/relatorio.py` (`_secao_de_invencao` e o parâmetro de `render`)
- Test: `tests/unit/test_evals_artefato.py` (é onde as outras seções são testadas — confira antes de criar arquivo novo)

- [ ] **Step 1: Testes primeiro, os cinco do desenho**

Com dois turnos inventando: a seção existe, lista conversa, índice, tipo e valor. Limpa: existe e diz zero. **A prosa não aparece:** monte o turno com um sentinela e afirme que ele não está no relatório. O valor com separador de milhar aparece, e a corrida de dez dígitos não. Um turno com duas divergências rende duas linhas.

- [ ] **Step 2: Escrever a seção**

Cabeçalho `## Ancoragem: turnos que citaram sem base (diagnostico)`. Contagem sempre; `Onde:` só quando houver turno, como `_secao_de_formato` faz.

**O docstring tem de dizer por que esta seção NÃO imprime a prosa enquanto a vizinha imprime a dela.** Não é redundância: as duas decisões opostas ficam a trinta linhas uma da outra, e sem a razão escrita a mais nova será "consertada" pela mais velha. Cite a TEC-161.

- [ ] **Step 3: `render` ganha o parâmetro**

`invencao: ResumoDaInvencao | None = None`, e a seção entra ao lado das outras de prosa. `None` significa "não houve medição", e não "deu zero" — a diferença é a razão de a D1 existir.

- [ ] **Step 4: Gates e commit**

`feat(TEC-270): o relatorio ganha a secao de ancoragem com os turnos`

---

### Task 3: A linha que faltava no runner

**Files:**
- Modify: `evals/test_acuracia_de_intencao.py` (a chamada de `render`, ~linha 536)

- [ ] **Step 1: Passar o resumo**

`invencao=resumo_da_invencao(invencoes, respostas)`. O comentário ao lado, no estilo dos vizinhos, registra que este é o dado que a TEC-269 coletou e que ficava em `_metricas_de` sem chegar ao relatório.

- [ ] **Step 2: Conferir que o runner ainda importa e coleta**

`ruff check evals` e `mypy` cobrem o import; a execução paga não roda aqui.

- [ ] **Step 3: Gates e commit**

`feat(TEC-270): o runner entrega as invencoes ao relatorio`

---

### Task 4: Fechamento

- [ ] **Step 1: A suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

- [ ] **Step 2: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`**

Esta branch mexe em dois arquivos de `src/mobia/evals/` densos em comentário — é onde `VIZINHO` costuma achar coisa.

- [ ] **Step 3: Push, PR, e a card em Em análise, com comentário registrando:**

- **O terceiro critério de aceite já estava satisfeito na origem:** `Divergencia.citado` já chega formatado por `reais_de`; o critério virou guarda contra regressão em vez de transformação.
- **A seção vizinha imprime a prosa de propósito**, e esta não pode — a diferença ficou escrita no código, porque é o tipo de assimetria que uma "uniformização" futura desfaz.
- **O que a card não entrega:** o relatório diz qual turno e o que foi citado, mas não **por que** — para isso seria preciso a prosa, que é justamente o que a regra proíbe.

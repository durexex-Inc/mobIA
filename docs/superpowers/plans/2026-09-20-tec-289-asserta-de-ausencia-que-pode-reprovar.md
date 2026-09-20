# TEC-289 — Asserção de ausência que pode reprovar: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedir a classe "asserção de ausência sobre log que não pode reprovar", que hoje não tem nenhuma ocorrência e tem ~10 candidatas a um refactor de distância.

**Architecture:** Um helper só em `tests/conftest.py` (`EventoDeLog`, `eventos_de_log`, `log_legivel`) no lugar de seis cópias; o sítio latente ganha `ensure_ascii=False`; uma guarda com `ast` varre `tests/` resolvendo a agulha de cada asserta de ausência sobre log escapado; e um teste executável prende o mecanismo em vez de descrevê-lo.

**Tech Stack:** Python 3.13, pytest, structlog, `ast`.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-289-asserta-de-ausencia-que-pode-reprovar-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m mypy`.
- **Comentários e docstrings em `tests/`: português SEM acento** — exceto valor citado. Este plano cita muito literal acentuado dentro de comentário: a citação leva acento, a prosa em volta não.
- **`src/` não é tocado.** Se algo em `src/` precisar mudar, pare: é a D1, que este desenho recusou com razão medida.
- **Mensagem de commit:** `tipo(TEC-289): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~5s, sem Docker). A Task 1 toca arquivos de integração, que precisam de `docker compose` — deixe a execução deles para a Task 4.
- **A guarda tem de ser vista reprovando** antes de ser considerada pronta: agulha acentuada plantada contra `caplog.text`. Guarda que nunca reprovou é a decoração que esta card existe para eliminar.

---

### Task 1: O helper único, e as seis cópias somem

**Files:**
- Modify: `tests/conftest.py` (acrescenta `EventoDeLog`, `eventos_de_log`, `log_legivel`)
- Modify: `tests/integration/test_apresentacao_no_turno.py`, `test_citacao_no_turno.py`, `test_conversa_encerrada.py`, `test_escalada_de_sla.py`, `test_notificacao_envio.py`
- Modify: `tests/features/test_dedup_por_message_id.py`

**Interfaces:**
- Produces: `eventos_de_log(caplog, evento) -> list[EventoDeLog]`, com `EventoDeLog(nivel: str, corpo: dict[str, Any])`.
- Produces: `log_legivel(caplog) -> str` — o log inteiro com o escape desfeito.

- [ ] **Step 1: Escrever os dois helpers em `tests/conftest.py`**

`EventoDeLog` é `NamedTuple` **de propósito**, e o comentário tem de dizer por quê: os três sítios que hoje fazem `((nivel, corpo),) = _eventos_de_log(...)` continuam funcionando sem edição, porque `NamedTuple` é tupla. Os outros três passam a escrever `.corpo`.

`log_legivel` decodifica cada registro e re-serializa com `ensure_ascii=False`, deixando passar intacto o que não for JSON. O comentário registra o que ele resolve: `caplog.text` vem escapado porque o `JSONRenderer` do app serializa no padrão, e agulha acentuada nunca é achada nele.

- [ ] **Step 2: Migrar os seis arquivos**

Nos três de `(nivel, corpo)`, a chamada muda de nome (`_eventos_de_log` → `eventos_de_log`) e a `def` local some. Nos três de dicionário, os usos ganham `.corpo`.

**Atenção ao import:** `tests/conftest.py` não é importável por `from tests.conftest import ...` na convenção deste repo — os arquivos de integração já fazem `from conftest import _entrada_do_lead` (ver `test_citacao_no_turno.py:136`). Siga a forma que o arquivo vizinho já usa, e confirme rodando.

- [ ] **Step 3: Rodar o que dá sem Docker e commitar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit -q
```

`refactor(TEC-289): um helper de log so, no lugar de seis copias`

---

### Task 2: O sítio latente ganha a guarda que o irmão já tem

**Files:**
- Modify: `tests/integration/test_notificacao_envio.py` (a asserta do teste do resumo ilegível)

- [ ] **Step 1: `ensure_ascii=False`, com comentário**

O comentário diz o que a linha compra: as agulhas de hoje (`"fulano"`, `"outro texto"`) são ASCII e passariam de qualquer jeito; o flag é o que mantém a asserta real quando alguém trocar por um nome com acento. Mesma razão do comentário da asserta da despedida em `test_conversa_encerrada.py` — cite-o, não invente uma segunda explicação. **E confira aquele comentário antes de copiá-lo:** ele descrevia o mecanismo ao contrário (dizia que o escape transformaria `nao` em `não`), e a correção faz parte desta branch.

- [ ] **Step 2: Gates e commit**

`fix(TEC-289): a serializacao do teste de notificacao para de escapar a agulha`

---

### Task 3: A guarda que resolve a agulha, e o teste que prende o mecanismo

**Files:**
- Create: `tests/unit/test_assercao_de_ausencia_sobre_log.py`

- [ ] **Step 1: Escrever o teste executável do mecanismo (D6)**

Com `configure_logging()` aplicado, uma agulha acentuada **não** aparece em `caplog.text` e **aparece** em `log_legivel(caplog)`. São duas assertas, e juntas elas documentam a armadilha de um jeito que não pode envelhecer: desligar o escape no renderer faz este teste reprovar e obriga a rever a card.

- [ ] **Step 2: Escrever a guarda**

Varre `tests/**/*.py` com `ast`. Para cada `assert <agulha> not in <palheiro>` (e a forma `not any(<agulha> in ...)`), decide se o palheiro é **log escapado**:

* `caplog.text`
* `<algo>.getMessage()`
* `json.dumps(...)` sem `ensure_ascii=False` — inclusive por variável intermediária no mesmo escopo, como `corpo_serializado = json.dumps(...)`

Resolve a agulha nesta ordem: literal de string → atribuição de topo do próprio arquivo → import de `mobia.*` (importa o módulo e lê o atributo). Reprova se a agulha resolvida tiver caractere não-ASCII, nomeando arquivo, linha e o substituto.

**Agulha irresolvível não reprova** — entra numa lista que o teste imprime. Hoje ela nasce vazia; um dia em que não nascer, quem ler decide.

- [ ] **Step 3: Ver a guarda reprovar, com um caso plantado**

Acrescente temporariamente, num arquivo de teste qualquer, `assert "imóvel" not in caplog.text`. A guarda tem de reprovar nomeando aquele arquivo e aquela linha. **Remova o plantio depois** — o que fica no repo é a guarda, não o caso.

Faça o mesmo pelo outro lado: com o plantio, o teste da D6 continua verde (ele não depende da guarda), e sem o plantio a guarda passa.

- [ ] **Step 4: Gates e commit**

`feat(TEC-289): a guarda resolve a agulha e reprova asserta de ausencia vazia`

---

### Task 4: A suíte inteira e o fechamento

- [ ] **Step 1: A suíte, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

A Task 1 mudou assinatura em cinco arquivos de integração e um de features — é aqui que isso se verifica. Se vier com centenas de `ERROR` de setup, não repita o mesmo comando: rode por blocos.

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

- [ ] **Step 3: Push, PR, e a card**

A card vai para **Em análise** com comentário registrando, no mínimo:

- **A premissa da card estava parcialmente errada, e para menos:** o mecanismo é do `JSONRenderer` da aplicação, não do `json.dumps` escrito no teste, então a família exposta inclui `caplog.text` — ~70 assertas, e não os 2 sítios que a card mapeou.
- **E, ao mesmo tempo, não há nenhuma asserta vazia hoje:** todas as 70 agulhas são ASCII, e a única acentuada já está protegida. A card é preventiva; o primeiro cenário do Gherkin ("o teste reprova quando o texto vaza") é exercitado pelo caso plantado da Task 3, não por um defeito existente.
- **A resposta sobre o `ruff`:** não existe regra; por isso a guarda é um teste com `ast`.
- **A alternativa medida que foi recusada:** `ensure_ascii=False` no renderer mata a classe inteira, mas o `stdout` desta máquina é `cp1252` e emoji de lead levanta `UnicodeEncodeError`; além de mudar bytes de log em produção, que a card escopou para fora.
- **Lacuna que é decisão de outra pessoa:** as fixtures de fala do lead seguem sem acento. Acentuá-las é o que tornaria as assertas de PII realistas, e a partir desta card isso deixa de ser silencioso.

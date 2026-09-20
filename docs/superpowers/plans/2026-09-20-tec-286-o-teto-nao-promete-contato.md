# TEC-286 — O teto de perguntas para de prometer contato: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tirar a promessa de contato de `TEXTO_DO_LIMITE_DE_PERGUNTAS` e fazer a guarda de teste barrar a promessa, não o vocabulário de três ocorrências passadas.

**Architecture:** `LITERAIS_AO_LEAD` sai de dentro do arquivo do acento e vira `tests/unit/literais_ao_lead.py`, lido por duas guardas. A guarda nova (`test_promessa_ao_lead.py`) barra frases, não palavras. O literal ganha o fecho da irmã já hedgeada, e os dois comentários que o citam acompanham.

**Tech Stack:** Python 3.13, pytest (+ pytest-xdist), FastAPI, ARQ.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-286-o-teto-nao-promete-contato-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m mypy`.
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Texto que o lead recebe: português COM acento.** **Comentários e docstrings em `src/` e `tests/`: português SEM acento** — exceto valor citado, que segue o valor. Esta branch cita muito literal acentuado dentro de comentário: a citação leva acento, a prosa em volta não.
- **Mensagem de commit:** `tipo(TEC-286): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Loop de desenvolvimento:** `./.venv/Scripts/python.exe -m pytest tests/unit` — ~4,4s, sem Docker, sem `-n`. As Tasks 1–3 são inteiramente unitárias.
- **A ordem das tasks é a ordem do vermelho.** A Task 2 escreve uma guarda que REPROVA contra o literal de hoje; a Task 3 é o que a faz passar. Inverter as duas perde a única prova de que a guarda pode reprovar.
- **Nenhum teste de integração precisa mudar.** `test_turno_teto_de_perguntas.py`, `test_turno_investidor.py` e `test_encaminhamento_por_intencao.py` importam a constante em vez de repetir o literal. Se um deles quebrar, é sinal de que alguém repetiu o texto à mão — conserte o teste, não o literal.

---

### Task 1: A lista de literais ao lead vira módulo próprio

**Files:**
- Create: `tests/unit/literais_ao_lead.py`
- Modify: `tests/unit/test_acento_no_texto_ao_lead.py` (imports, tupla e o teste do tamanho saem)

**Interfaces:**
- Produces: `LITERAIS_AO_LEAD: tuple[str, ...]` — as constantes de módulo que o lead recebe.
- Consumes: as constantes de `mobia.domain.*`, como hoje.

- [ ] **Step 1: Criar o módulo com a tupla de hoje mais os três que faltavam**

`tests/unit/literais_ao_lead.py` recebe os imports e a tupla, e ganha os três achados na exploração: `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA`, `TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE` e `TEXTO_DO_PEDIDO_DE_HUMANO` (o de dentro do horário; a variante `_FORA_DO_HORARIO` já estava).

A docstring do módulo diz o que a lista é e o que ela não é — constantes de módulo entregues ao lead, e não os rótulos da ficha de imóvel, que nascem de f-string e são cobertos por `test_apresentacao.py`. Esse parágrafo **muda de arquivo**: hoje ele está na docstring do teste de acento, e ele descreve a lista, não a guarda.

O teste do tamanho acompanha a lista para cá, e o número vai de 17 para 20:

```python
def test_a_lista_de_literais_nao_encolheu_sem_querer() -> None:
    """Guarda da guarda: um literal removido da tupla faria as duas guardas que
    a leem passarem sem checar nada, e ninguem notaria.

    Foi 17 ate a TEC-286, que acrescentou os dois textos de encaminhamento e o
    `TEXTO_DO_PEDIDO_DE_HUMANO` de dentro do horario -- tres constantes ao lead
    que nunca estiveram sob a guarda de acento.
    """
    assert len(LITERAIS_AO_LEAD) == 20
```

- [ ] **Step 2: O arquivo do acento importa em vez de declarar**

Some a tupla, somem os imports das constantes, some o teste do tamanho. Entra `from tests.unit.literais_ao_lead import LITERAIS_AO_LEAD`.

A docstring do arquivo fica, menos o parágrafo que migrou: o que explica `FORMAS_SEM_ACENTO`, a assimetria "erra de menos, nunca de mais" e a sabotagem do "/mês" é raciocínio sobre a guarda de acento e continua sendo dela.

- [ ] **Step 3: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_acento_no_texto_ao_lead.py -v
```

Espera-se **20 parametrizações verdes** no teste de acento. Se algum dos três literais novos reprovar, é achado de verdade — um texto ao lead com forma sem acento que ninguém tinha olhado. Conserte o texto, não a lista.

> **Import entre módulos de teste:** `pythonpath = ["."]` no `pyproject.toml` põe a raiz em `sys.path`, e `tests/` não tem `__init__.py` — `tests.unit.literais_ao_lead` resolve como namespace package. Se o import falhar, NÃO crie `__init__.py` (mudaria como o pytest importa todo o diretório): confirme primeiro com `./.venv/Scripts/python.exe -c "import tests.unit.literais_ao_lead"`.

- [ ] **Step 4: Gates e commit**

`refactor(TEC-286): a lista de literais ao lead vira modulo lido por duas guardas`

---

### Task 2: A guarda que barra a promessa, e que reprova hoje

**Files:**
- Create: `tests/unit/test_promessa_ao_lead.py`

- [ ] **Step 1: Escrever a guarda**

```python
PROMESSAS_BANIDAS = (
    "avisei",
    "avisamos",
    "avisado",
    "entra em contato",
    "entrar em contato",
    "entrará em contato",
    "vai te procurar",
    "vai te ligar",
    "vai te chamar",
)
```

O comentário acima da tupla registra **por que ela erra de menos**: uma frase faltando deixa de pegar um caso, e nenhuma das que estão ali reprova texto correto. E registra o precedente das três ocorrências (TEC-174 escreveu e reescreveu; TEC-143 reintroduziu e a revisão pegou; TEC-149 escapou porque não usou a palavra "avisei"), que é o que justifica barrar frase e não vocabulário.

A comparação é substring em minúsculas — as agulhas aqui são frases de duas ou três palavras, e fronteira de palavra não acrescenta nada. Vale dizer isso no comentário, porque o vizinho de acento usa `\b` e a diferença parece descuido se ninguém a explicar.

Dois testes, no molde do vizinho: a guarda parametrizada sobre `LITERAIS_AO_LEAD`, e o `test_a_lista_de_promessas_nao_encolheu_sem_querer`.

- [ ] **Step 2: Ver reprovar, e é por aqui que a card existe**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_promessa_ao_lead.py -v
```

Espera-se **exatamente uma** reprovação: `TEXTO_DO_LIMITE_DE_PERGUNTAS`, por "entra em contato". Mais de uma é achado — anote qual e trate na mesma branch, porque é texto ao lead prometendo contato hoje.

**Não siga para a Task 3 sem ter visto este vermelho.** É a verificação nos dois sentidos que separa "escrevi um teste" de "escrevi um teste que pode reprovar" — a mesma nota de método que a TEC-289 registra e que a TEC-138 praticou.

- [ ] **Step 3: Gates e commit** (com a guarda ainda vermelha? **não**) — a guarda só entra no repo junto com o conserto, no commit da Task 3. Um commit que deixa a suíte vermelha na branch é um commit que ninguém consegue bissectar depois.

---

### Task 3: O literal novo, e os dois comentários que o citam

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (literal ~185 e comentário ~2510)
- Modify: `tests/unit/test_textos_do_encaminhamento.py` (sai o teste absorvido; docstring acompanha)

- [ ] **Step 1: A frase nova**

```python
TEXTO_DO_LIMITE_DE_PERGUNTAS = (
    "Já perguntei bastante e não quero virar interrogatório. "
    "Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui. "
    "Já coloquei sua conversa na fila deles."
)
```

Idêntica ao fecho de `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA`, de propósito — a card proíbe inventar uma quarta redação para o mesmo fato.

- [ ] **Step 2: O comentário do literal**

O parágrafo "**Nao promete que alguem foi avisado, e isso e deliberado**" para de citar a TEC-280 como razão aberta (ela entregou) e passa a dizer as duas coisas que continuam verdadeiras: aceito por SMTP não é lido por um corretor, e o WhatsApp (TEC-281) só registra. Ganha a **nota de reversão**: quando a TEC-281 entregar, o hedge pode cair, e é ela a condição.

- [ ] **Step 3: O comentário de `turno.py:2510`**

Ele cita a frase antiga por extenso para explicar por que a despedida da TEC-138 vence as substituições acima dela. Passa a citar `"já coloquei sua conversa na fila deles"` — e o argumento **não muda**: uma fila também é um depois que a conversa encerrada não tem.

- [ ] **Step 4: O teste absorvido sai do arquivo da TEC-137**

`test_nenhum_texto_promete_que_alguem_foi_avisado` sai de `test_textos_do_encaminhamento.py` — a guarda nova já cobre os dois textos dele, por `LITERAIS_AO_LEAD`. A docstring do arquivo, que hoje diz testar "em especial" essa promessa, passa a dizer o que sobrou: os dois textos serem distintos, não terminarem em pergunta, e o sufixo formatar as horas e hedgear o prazo. Uma linha aponta para onde a promessa passou a ser guardada.

- [ ] **Step 5: Rodar o verde**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
```

- [ ] **Step 6: Gates e commit**

`fix(TEC-286): o teto de perguntas diz a fila, e nao um contato que ninguem faz`

---

### Task 4: A suíte inteira e a listagem de comentários

- [ ] **Step 1: A suíte, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta; guarde o hash junto com o resultado. Se vier com centenas de `ERROR` de setup, **não repita o mesmo comando** — é o Postgres sob paralelismo, e a cura é rodar por blocos (`tests/unit`, `tests/integration`, `tests/features`), não insistir no `-n 8`.

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Esta branch mexe em prosa de comentário em três arquivos e move uma docstring de lugar — é exatamente a classe de mudança em que `VIZINHO` e `PROSA` acham coisa. Reconfira o que ela listar; em particular, qualquer `.md` versionado que cite `turno.py:<linha>`, porque as linhas do arquivo andaram.

- [ ] **Step 3: Push, PR, e a card**

`git push -u origin feat/tec-286-o-teto-nao-promete-contato` e PR contra `main`. A card vai para **Em análise** com comentário registrando:

- **Divergência em relação ao texto da card:** ela diz que "nada notifica corretor nenhum enquanto a TEC-280 e a TEC-281 estiverem abertas"; a TEC-280 está Feita e o e-mail entrega por SMTP. O hedge continua valendo por outra razão — aceito pelo servidor não é lido por uma pessoa, e a TEC-281 segue aberta —, e a nota de reversão no código depende só da TEC-281.
- **Escopo que a card não previa:** três constantes ao lead entraram na lista de literais (17 → 20); elas estavam fora da guarda de acento também.
- **Lacuna declarada, que é decisão de produto:** `TEXTO_DA_BUSCA_INCONCLUSIVA` diz "já te retorno com as opções" e continua dizendo. É promessa do agente sobre si mesmo, não de contato de corretor, e ampliar a guarda para ela exige decidir quando o agente pode falar do próprio futuro.
- **O que a card não entrega:** enquanto a TEC-281 não entregar, o lead que bate o teto sabe que está numa fila, e ninguém o procura.

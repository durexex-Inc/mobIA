# TEC-240 — Ensinar o prompt a extrair: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dizer ao modelo que ele passou a extrair, e o que a extração significa — dentro de um orçamento de 296 caracteres.

**Architecture:** Duas mudanças de texto em `SISTEMA_DO_AGENTE`: a abertura nomeia a terceira tarefa, e uma regra nova explica `None` e a proibição de inferir. Nenhuma `description` de campo entra no schema — não cabe. Mais um teste que trava a margem que sobra, para a próxima card não a comer sem saber.

**Tech Stack:** Python 3.12+, pytest. Só texto e testes; nenhuma lógica muda.

**Spec:** [docs/superpowers/specs/2026-08-29-tec-240-ensinar-o-prompt-a-extrair-design.md](../specs/2026-08-29-tec-240-ensinar-o-prompt-a-extrair-design.md)

## Global Constraints

- **Comandos:** `.venv/Scripts/python.exe -m pytest tests/unit -q` (leva ~2-8 min nesta máquina — **rode em primeiro plano e aguarde**, background não notifica); `... -m ruff check src tests alembic evals`; `... -m ruff format src tests alembic`; `... -m mypy src`. Os quatro passam antes de cada commit.
- **NUNCA rode `pytest evals`.** É pago — uma chamada a uma API de LLM por turno do corpus. Nada neste plano precisa dele, e o efeito desta card no número **não será medido**.
- **Código e comentários em português sem acentos.** O texto do prompt também: ele já é sem acentos, e não é lugar de começar.
- **O orçamento é a restrição dura.** A subcontagem tem de ficar **abaixo de 590**, não só abaixo de 600. Se o seu texto passar disso, encurte o texto — **não** suba `contexto_headroom_de_tokens`. Subir a reserva foi explicitamente recusado no spec.
- **Nenhuma `description` de campo no schema.** Não cabe, e a aritmética que fecha essa porta está no spec.
- **Meça, não estime.** Toda contagem deste plano foi medida; confirme rodando.

---

### Task 1: O texto, e a margem travada por teste

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py` (`SISTEMA_DO_AGENTE`, linhas ~29-45)
- Test: `tests/unit/test_config.py` (`test_diferenca_entre_o_contado_e_o_enviado`, ~linha 167)
- Test: `tests/unit/test_classificador.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `SISTEMA_DO_AGENTE` com 1015 caracteres (era 771).

- [ ] **Step 1: Escreva os dois testes que falham**

Em `tests/unit/test_classificador.py`, ao lado dos testes que já checam conteúdo de `SISTEMA_DA_DESAMBIGUACAO` (procure `assert "menu" in SISTEMA_DA_DESAMBIGUACAO.lower()`, por volta da linha 543) — é o padrão que este arquivo já usa:

```python
def test_o_prompt_do_agente_nomeia_as_tres_tarefas() -> None:
    """Ate a TEC-240 o prompt dizia "duas coisas" -- a TEC-145 pos um objeto
    `extracao` de nove campos no schema e nao contou ao modelo.

    Guarda contra alguem reverter a abertura ao editar o prompt por outro
    motivo: o schema continuaria pedindo extracao, e o modelo voltaria a nao
    saber que ela existe.
    """
    assert "tres coisas" in SISTEMA_DO_AGENTE
    assert "extrai" in SISTEMA_DO_AGENTE


def test_o_prompt_do_agente_explica_a_semantica_de_null() -> None:
    """`null` significa "o lead nao falou disso NESTE turno", e a metrica pune
    inferencia tanto quanto omissao. As duas coisas chegavam ao modelo como
    nomes de campo crus."""
    assert "DESTE turno" in SISTEMA_DO_AGENTE
    assert "Nao infira" in SISTEMA_DO_AGENTE
```

Garanta que `SISTEMA_DO_AGENTE` está no bloco de import do topo do arquivo — ele já importa `SISTEMA_DA_DESAMBIGUACAO` do mesmo módulo.

Em `tests/unit/test_config.py`, logo depois de `test_diferenca_entre_o_contado_e_o_enviado`:

```python
def test_a_margem_do_orcamento_do_prompt_e_deliberada(settings) -> None:
    """A TEC-240 gastou 61 dos 74 tokens de folga e deixou 13 de propósito.

    Sem este teste, a proxima card gasta os 13 sem saber que eram a margem, e
    a card seguinte descobre o estouro -- que e o que aconteceu com a reserva
    antes da TEC-145. O teto de 590 e mais apertado que o de 600 usado pelo
    teste irmao justamente para tornar a margem visivel: se voce esta lendo
    isto porque ele reprovou, a pergunta e "o que sai do prompt para o novo
    texto entrar?", nao "quanto subo o numero?".
    """
    import json

    from mobia.domain.agente.classificador import _SCHEMA_COMPILADO, SISTEMA_DO_AGENTE
    from mobia.domain.context.montagem import SISTEMA

    def em_tokens(texto: str) -> float:
        return len(texto) / 4

    rotulos = (
        "Resumo da conversa ate aqui:\nMensagens recentes:\nEstado de qualificacao:\n" + "\n\n" * 2
    )
    subcontagem = (
        -em_tokens(SISTEMA)
        + em_tokens(SISTEMA_DO_AGENTE)
        + em_tokens(json.dumps(_SCHEMA_COMPILADO))
        + em_tokens(rotulos)
    )

    assert subcontagem < 590, (
        f"subcontagem {subcontagem}: a margem de 13 tokens sobre o teto de 600 "
        f"foi consumida. Encolha o texto enviado, nao suba a reserva."
    )
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py tests/unit/test_config.py -q -k "tres_tarefas or semantica_de_null or margem"`

Expected: os **dois primeiros** FALHAM (`assert "tres coisas" in ...` — hoje o prompt diz "duas coisas"). O **terceiro passa** de primeira, porque a subcontagem hoje é 526, bem abaixo de 590. Isso é esperado: ele é o guarda da margem que a Task ainda vai criar, e o valor que ele trava só fica apertado depois do Step 3. Se ele **falhar** agora, pare e reporte — significaria que a medição do spec está errada.

- [ ] **Step 3: Mude o texto**

Em `src/mobia/domain/agente/classificador.py`, `SISTEMA_DO_AGENTE`. Duas edições.

**A abertura.** Troque:

```python
    "Voce e o assistente virtual de uma imobiliaria brasileira, atendendo um lead "
    "por mensagem. A cada turno voce faz duas coisas: classifica a intencao do "
    "lead e responde a ele.\n\n"
```

por:

```python
    "Voce e o assistente virtual de uma imobiliaria brasileira, atendendo um lead "
    "por mensagem. A cada turno voce faz tres coisas: classifica a intencao do "
    "lead, extrai o que ele procura, e responde a ele.\n\n"
```

A ordem `classifica, extrai, responde` espelha a ordem dos campos em `SCHEMA_DA_RESPOSTA`. Não é enfeite: o modelo preenche o objeto na ordem declarada, e enunciar a tarefa fora de ordem convida a incoerência entre o que ele diz que fez e o que preencheu.

**A regra nova**, acrescentada ao **fim** da string, depois de `"...Nao invente informacao sobre imoveis que nao esteja no contexto."`:

```python
    "\n\nNa extracao, preencha so o que a fala DESTE turno afirma; o resto e "
    "null. null e \"nao falou disso agora\", nunca \"nao sei\". Nao infira: "
    "extrair o que a fala nao afirma conta erro igual a nao extrair o que ela "
    "afirma."
```

Acrescente um comentário curto acima de `SISTEMA_DO_AGENTE` registrando o orçamento — que o texto cabe em 587 de um teto de 600, que a margem de 13 tokens é deliberada e travada por `test_a_margem_do_orcamento_do_prompt_e_deliberada`, e que nenhum campo do schema ganhou `description` porque descrever só os três enums custaria da ordem de 300 caracteres e estouraria os 296 de folga sozinho.

**Registre também por que a abertura diz "extrai o que ele procura" e não "extrai o que ele disse sobre o que procura".** A forma longa é mais precisa e custa **18 caracteres a mais** (127 contra 109) — foi cortada pelo orçamento, e a precisão que se perde é recuperada pela regra logo abaixo, que diz explicitamente "só o que a fala DESTE turno afirma". Sem esse registro, a primeira pessoa que achar a abertura imprecisa a "melhora" sem olhar a conta, e descobre o estouro no CI.

- [ ] **Step 4: Confira a aritmética por execução**

Run:

```bash
.venv/Scripts/python.exe -c "
import json
from mobia.domain.agente.classificador import _SCHEMA_COMPILADO, SISTEMA_DO_AGENTE
from mobia.domain.context.montagem import SISTEMA
t = lambda s: len(s)/4
rot = 'Resumo da conversa ate aqui:\nMensagens recentes:\nEstado de qualificacao:\n' + '\n\n'*2
sub = -t(SISTEMA) + t(SISTEMA_DO_AGENTE) + t(json.dumps(_SCHEMA_COMPILADO)) + t(rot)
print('chars do prompt', len(SISTEMA_DO_AGENTE))
print('subcontagem', sub, ' teto 600  guarda 590  margem', 600-sub)
"
```

Expected, exatamente:

```
chars do prompt 1015
subcontagem 587.0  teto 600  guarda 590  margem 13.0
```

Se algum número divergir, **pare e reporte** — não ajuste o teste nem o teto para casar.

- [ ] **Step 5: Rode a suíte inteira**

Run: `.venv/Scripts/python.exe -m pytest tests/unit -q`

Expected: PASS. `test_diferenca_entre_o_contado_e_o_enviado` (o teste irmão, com teto de 600) continua passando com 587.

- [ ] **Step 6: Lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/agente/classificador.py tests/unit/test_classificador.py tests/unit/test_config.py
git commit -m "feat(TEC-240): o prompt nomeia a extracao e explica o que null significa"
```

---

### Task 2: A conta escrita, nos dois lugares onde ela vive

**Files:**
- Modify: `src/mobia/app/config.py` (docstring de `teto_de_tokens_efetivo`, ~linhas 160-188)
- Modify: `README.md`

**Interfaces:**
- Consumes: os números finais da Task 1 (prompt 1015 chars, subcontagem 587).
- Produces: nada de código.

- [ ] **Step 1: Conserte a docstring obsoleta de `teto_de_tokens_efetivo`**

Este é um defeito **pré-existente** que a Task 1 agrava, e está no lugar exato que esta card discute. A docstring lista a decomposição em tokens e afirma:

- `+93` para o schema compilado — hoje são **356**
- "Líquido: **~263 tokens** contados a menos do que se envia" — hoje são **587**
- "contra uma reserva de **400**" e "a reserva **fica em 400**" — hoje é **800**, mudada pela TEC-145

O comentário da própria constante (`contexto_headroom_de_tokens`, ~linha 95-100) **foi** atualizado pela TEC-145; esta docstring não. São dois textos sobre a mesma conta, um certo e um errado, e o errado é o mais longo.

Reescreva a lista de parcelas com os números medidos:

```
- `-42`   `montagem.SISTEMA` entra na contagem mas nao e enviado
- `+254`  `classificador.SISTEMA_DO_AGENTE` vai no campo `system=`
- `+356`  o schema compilado em `output_config.format`
- `+19`   os rotulos de secao que `montar_prompt` intercala
```

E troque a conclusão: líquido ~587 contra uma reserva de **800**, e a reserva fica em 800 — com a razão que o comentário da constante já dá (o fator 0,75 existe para haver folga; 702 satisfaria a asserção por meio token e derrotaria o propósito).

Acrescente uma frase dizendo **por que ela ficou obsoleta**: a TEC-145 acrescentou o objeto `extracao` ao schema (de onde vêm os 356) e subiu a reserva, e esta docstring não acompanhou. Uma conta que vive em dois lugares envelhece em um deles; registrar isso é o que evita a terceira vez.

- [ ] **Step 2: README**

Na seção da TEC-145, onde a preparação de contexto e a reserva já são discutidas, acrescente o que esta card faz e o que ela deliberadamente não faz:

- **o prompt passa a nomear a terceira tarefa e a explicar `null`** — até aqui a semântica em que todo o desenho se apoia chegava ao modelo como nomes de campo crus;
- **a reserva não subiu.** Ficou em 800, e o texto coube nos 296 caracteres de folga com 13 tokens de margem, travada por teste próprio. Subir a reserva era saída permitida pelo card e foi recusada: cada 100 tokens de reserva são 100 tokens a menos de literais e resumo por turno;
- **nenhum campo do schema ganhou `description`, e o item 3 do escopo do card não foi entregue** — com a aritmética ao lado: descrever só os três enums de vocabulário arbitrário custa da ordem de 300 caracteres e estoura os 296 sozinho;
- **o efeito não foi medido, e o critério 4 do card não se sustenta como escrito.** A única execução paga de extração é a de 28/08, contra um corpus que mudou **duas vezes** desde então (TEC-239 levou as anotações de 47 para 59; TEC-238 acrescentou 37 turnos negativos). Um "depois" medido hoje difere daquele por mudança de prompt **e** de régua ao mesmo tempo, e a diferença não é atribuível a uma causa só. Medir efeito de prompt exigiria uma execução nova **antes** desta card entrar — duas execuções pagas, não uma.

- [ ] **Step 3: Rode e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/app/config.py README.md
git commit -m "docs(TEC-240): a conta do orcamento, corrigida onde tinha envelhecido"
```

---

## Encerramento

- [ ] **Suíte inteira, lint, tipos** uma última vez.

- [ ] **Critérios de aceitação do card:**

| critério | estado |
|---|---|
| `test_diferenca_entre_o_contado_e_o_enviado` continua passando, ou a reserva sobe com justificativa | ✅ Continua passando com 587/600. A reserva **não** subiu |
| A precisão de extração medida depois é comparada com a de antes, e o número fica no README | ❌ **Não entregue** — exige execução paga, e não há "antes" comparável |
| Se a precisão não melhorar, isso também fica registrado | ❌ Mesma causa. O README registra que **não foi medido**, e por quê |

- [ ] **Não rode `pytest evals`.**

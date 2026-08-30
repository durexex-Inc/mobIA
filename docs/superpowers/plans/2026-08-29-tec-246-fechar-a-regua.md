# TEC-246 — Fechar a régua: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a última mudança de régua antes da execução paga: fechar a cobertura por valor de vocabulário, dar eixo único ao critério de anotação, e tirar a assimetria da normalização de `regiao`.

**Architecture:** Três mudanças independentes que só compartilham a fila. A D9 é a única que toca comportamento (`_PREFIXOS_DE_REFERENCIA`) e fica isolada na Task 1, para poder ser rejeitada sozinha. As Tasks 2 e 3 mexem no corpus e nos guardas; a 4 nos pisos; a 5 na documentação.

**Tech Stack:** Python 3.12+, pytest, YAML. Nenhuma dependência nova.

**Spec:** [docs/superpowers/specs/2026-08-29-tec-246-fechar-a-regua-design.md](../specs/2026-08-29-tec-246-fechar-a-regua-design.md)

## Global Constraints

- **Comandos:** `.venv/Scripts/python.exe -m pytest tests/unit -q` (leva ~2-6 min nesta máquina — **rode em primeiro plano e aguarde**; se o harness mover para segundo plano, **leia o arquivo de saída até o fim**, a notificação não chega); `... -m ruff check src tests alembic evals`; `... -m ruff format src tests alembic`; `... -m mypy src`.
- **NUNCA rode `pytest evals`.** É pago — uma chamada a uma API de LLM por turno do corpus. Nada aqui precisa dele, e o efeito desta card **não será medido** (D8 do spec).
- **`src/mobia/domain/` só pode ser tocado em dois lugares, e nenhum outro:** o docstring de `Extracao` (D4) e a tupla `_PREFIXOS_DE_REFERENCIA` (D9), ambos em `src/mobia/domain/agente/schemas.py`. Qualquer outra mudança ali — `classificador.py`, campo de schema, prompt, limite — está fora e é motivo de parar e reportar.
- Código e comentários em **português sem acentos**; README e specs **com** acentos.
- **`campos` presente é contrato de anotação completa.** Ao anotar um turno, enumere tudo o que a fala afirma — e só o que ela afirma.
- **Convenção de índice de turno: 0-based.** "primeiro turno" é índice 0. Não use "t1"/"t2".
- **As falas novas imitam o corpus:** minúsculas, sem acentos, informais ("pra", "voces", "to"). Um turno que soe como texto de spec destoa e vira ruído na régua.
- **Contagens conferidas por execução, não por leitura.**

---

### Task 1: A simetria dos prefixos de `regiao`

A única task que muda comportamento. Isolada de propósito: um revisor pode rejeitá-la sem derrubar o resto da card.

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py` (tupla `_PREFIXOS_DE_REFERENCIA`)
- Test: `tests/unit/test_extracao.py`

**Interfaces:**
- Consumes: nada.
- Produces: `normalizar_regiao` passa a reduzir `na regiao de|das|dos`, `proximo das|dos` e `perto das|dos`. Nenhuma assinatura muda.

- [ ] **Step 1: Escreva o teste que falha**

Em `tests/unit/test_extracao.py`, junto dos outros testes de `normalizar_regiao`. O arquivo já importa `pytest`, `normalizar_regiao` e `_PREFIXOS_DE_REFERENCIA` — não reimporte nenhum dos três.

```python
@pytest.mark.parametrize(
    ("fala", "esperado"),
    [
        # A familia `na regiao` tinha `da` e `do` e faltavam tres.
        ("na regiao de sao roque", "sao roque"),
        ("na regiao das flores", "flores"),
        ("na regiao dos lagos", "lagos"),
        # `proximo` e `perto` tinham o singular e faltava o plural.
        ("proximo das clinicas", "clinicas"),
        ("proximo dos jardins", "jardins"),
        ("perto das lojas", "lojas"),
        ("perto dos jardins", "jardins"),
    ],
)
def test_normalizar_regiao_trata_as_familias_de_prefixo_simetricamente(
    fala: str, esperado: str
) -> None:
    """A lista tinha `na regiao da/do` e ignorava `de/das/dos`.

    O corpus so exercitava `da` e `do`, entao o furo era latente -- mas "na
    regiao de" e portugues corrente, e forma nao-canonica de `regiao` respondeu
    por 10 das 29 discrepancias de 28/08. Foi o que originou a TEC-241.
    """
    assert normalizar_regiao(fala) == esperado


def test_normalizar_regiao_nao_come_o_de_de_um_toponimo() -> None:
    """`das` so sai depois de `regiao`, `proximo` ou `perto`.

    `compra-04` anota `regiao: jardim das flores`. Se a lista ganhasse `das `
    solto, o toponimo viraria "flores" e a anotacao existente passaria a nao
    casar consigo mesma.
    """
    assert normalizar_regiao("jardim das flores") == "jardim das flores"
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py -q -k simetric`

Expected: FAIL nos **sete** casos parametrizados — cada um devolve a frase inteira em vez do topônimo. `test_normalizar_regiao_nao_come_o_de_de_um_toponimo` já passa; ele é regressão, não alvo.

- [ ] **Step 3: Acrescente as sete entradas**

Em `src/mobia/domain/agente/schemas.py`, cada uma **junto da sua família**, não empilhadas no fim:

```python
_PREFIXOS_DE_REFERENCIA = (
    "na regiao da ",
    "na regiao do ",
    "na regiao de ",
    "na regiao das ",
    "na regiao dos ",
    "regiao das ",
    "regiao dos ",
    "regiao da ",
    "regiao do ",
    "regiao de ",
    "proximo da ",
    "proximo do ",
    "proximo das ",
    "proximo dos ",
    "proximo ao ",
    "proximo a ",
    "perto da ",
    "perto do ",
    "perto de ",
    "perto das ",
    "perto dos ",
    "estacao ",
)
```

E acrescente ao comentário acima da tupla, sem reescrever o que já está lá:

```
# A TEC-246 fechou a assimetria: `na regiao` tinha `da`/`do` e ignorava
# `de`/`das`/`dos`, e `proximo`/`perto` tinham o singular e nao o plural. O
# corpus so exercitava `na regiao da/do`, entao o furo era latente -- e
# latente e o pior estado, porque a fala do lead nao pede licenca. O espaco
# final de cada entrada e o que mantem
# `test_nenhum_prefixo_de_referencia_e_prefixo_de_outro` verde: sem ele,
# `na regiao da ` seria prefixo de `na regiao das `.
```

- [ ] **Step 4: Rode para ver passar, e confira o invariante**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py -q
```

Expected: PASS, incluindo `test_nenhum_prefixo_de_referencia_e_prefixo_de_outro`. **Se esse invariante reprovar, pare e reporte** — significa que uma entrada entrou sem o espaço final.

- [ ] **Step 5: Confirme que o corpus não se mexeu**

A normalização roda nos dois lados da medição, então vale confirmar que nenhuma anotação existente mudou de significado:

```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.domain.agente.schemas import normalizar_regiao
from mobia.evals.corpus import carregar
c = carregar(Path('evals/corpus'))
mudou = [(x.id, i, t.campos['regiao'], normalizar_regiao(t.campos['regiao']))
         for x in c for i, t in enumerate(x.turnos)
         if t.campos and 'regiao' in t.campos
         and normalizar_regiao(t.campos['regiao']) != t.campos['regiao']]
print('anotacoes de regiao que a normalizacao ainda altera:')
for m in mudou: print('  ', m)
"
```

Expected: exatamente as duas anotações antigas com preposição que a TEC-241 deixou de propósito (`aluguel-01` e `aluguel-07`, ambas `perto da ...`). **Qualquer terceira linha é regressão** — pare e reporte.

- [ ] **Step 6: Suíte, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/agente/schemas.py tests/unit/test_extracao.py
git commit -m "feat(TEC-246): a lista de prefixos de regiao fica simetrica"
```

---

### Task 2: A colisão resolvida, e `compra-10` relido

**Files:**
- Modify: `evals/corpus/aluguel.yaml`, `evals/corpus/compra.yaml`
- Modify: `src/mobia/evals/corpus.py` (docstring de `TurnoAnotado`)
- Modify: `tests/unit/test_evals_corpus_real.py` (`_FORA_DA_MEDICAO`)

**Interfaces:**
- Consumes: corpus da Task 1 (inalterado por ela).
- Produces: 138 turnos, 56 positivos, 66 negativos, 16 fora da medição, 84 anotações.

- [ ] **Step 1: Tire `aluguel-09` índice 2 da lista de exclusões**

Em `tests/unit/test_evals_corpus_real.py`, remova a entrada `("aluguel-09", 2)` de `_FORA_DA_MEDICAO`. O dict fica com **16** entradas.

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k motivo_escrito`

Expected: FAIL com `aluguel-09` índice 2 em **"sem motivo escrito"** — ele ainda está sem `campos` no YAML e agora não está mais declarado.

- [ ] **Step 3: Anote `aluguel-09` índice 2 como negativo**

Em `evals/corpus/aluguel.yaml`. O comentário de três linhas que hoje justifica a exclusão **sai** — ele afirma o contrário do que o turno passa a ser — e entra este:

```yaml
    # Negativo, e nao exclusao: a fala nao nomeia campo nenhum. `predio` e
    # conteiner generico, e repetir o tipo do turno 0 aqui conta `extra` de
    # proposito -- mesma decisao que `borda-longa-01` indice 2 e `aluguel-01`
    # indice 1. A TEC-238 excluiu este turno antes de existir a regra de
    # anafora; a TEC-246 deu eixo unico ao criterio e a exclusao cedeu.
    - lead: "e pode ter animal de estimacao no predio?"
      intencao: ALUGUEL
      campos: {}
```

- [ ] **Step 4: Releia `compra-10` índice 0**

Em `evals/corpus/compra.yaml`, o turno passa de `campos: {}` a positivo:

```yaml
    # "primeiro imovel" afirma que nao ha imovel para vender. Como negativo
    # -- que foi como a TEC-245 o deixou -- a regua cobrava invencao de um
    # modelo que lesse a fala com razao. E o unico turno do corpus que anota
    # `tem_imovel_para_vender: false`, o caso que `preenchidos()` existe para
    # preservar.
    - lead: "minha esposa e eu queremos comprar nosso primeiro imovel, pode me ajudar a entender o processo?"
      intencao: COMPRA
      campos:
        tem_imovel_para_vender: false
```

**Atenção:** `false` minúsculo, YAML booleano — não a string `"false"`. `carregar` valida o tipo, então um erro aqui aparece como `CorpusInvalido`, não em silêncio.

- [ ] **Step 5: Dê eixo único ao critério no docstring**

Em `src/mobia/evals/corpus.py`, o docstring de `TurnoAnotado` tem um bloco que começa em **"Esta regra colide com a da TEC-242, e a colisao esta em aberto por decisao."** e termina antes de **"Turno fora da medicao tem entrada em `_FORA_DA_MEDICAO`"**. Substitua o bloco inteiro por:

```
      **Quando as duas leituras cabem, anafora vence (TEC-246).** "pode ter
      animal de estimacao no predio?" (`aluguel-09` indice 2) pressupoe o
      predio E nao nomeia campo nenhum. Ate a TEC-245 isso o tirava da
      medicao; hoje ele e negativo, igual a `aluguel-01` indice 1, que diz
      "aquele mesmo predio". As duas sao a mesma forma de fala e agora tem o
      mesmo balde.

      O criterio de exclusao ficou mais estreito de proposito: exclui-se por
      **sugerir um valor sem nomea-lo**, e nao por pressupor. O que decidiu
      foi o proposito do negativo -- pegar o modelo reemitindo estado
      acumulado --, que e a primeira hipotese a checar se a execucao paga vier
      vermelha. `borda-longa-01` indice 2 ja dizia que repetir campo do turno
      anterior conta `extra` DE PROPOSITO; a exclusao da TEC-238 e anterior a
      essa regra, e foi ela que cedeu.
```

- [ ] **Step 6: Confira as contagens**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.evals.corpus import carregar, total_de_turnos
c = carregar(Path('evals/corpus'))
pos = sum(1 for x in c for t in x.turnos if t.positivo)
neg = sum(1 for x in c for t in x.turnos if t.negativo)
anot = sum(len(t.campos) for x in c for t in x.turnos if t.campos)
print('conversas', len(c), '| turnos', total_de_turnos(c), '| positivos', pos,
      '| negativos', neg, '| fora', total_de_turnos(c)-pos-neg, '| anotacoes', anot)
"
```

Expected, exatamente:

```
conversas 50 | turnos 138 | positivos 56 | negativos 66 | fora 16 | anotacoes 84
```

Se algum número divergir, **pare e reporte**.

- [ ] **Step 7: Suíte, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add evals/corpus src/mobia/evals/corpus.py tests/unit/test_evals_corpus_real.py
git commit -m "feat(TEC-246): anafora vence a pressuposicao, e primeiro imovel volta pra medicao"
```

---

### Task 3: As três conversas novas e o guarda por valor

**Files:**
- Modify: `evals/corpus/compra.yaml`
- Modify: `src/mobia/domain/agente/schemas.py` (docstring de `Extracao`)
- Modify: `src/mobia/evals/corpus.py` (regra de sinônimos no docstring de `TurnoAnotado`)
- Modify: `tests/unit/test_evals_corpus_real.py`

**Interfaces:**
- Consumes: corpus da Task 2 (56 positivos, 84 anotações).
- Produces: 53 conversas, 146 turnos, 62 positivos, 68 negativos, 16 fora, 96 anotações. Todo valor do vocabulário com pelo menos uma anotação.

- [ ] **Step 1: Escreva o guarda por valor, que falha**

Em `tests/unit/test_evals_corpus_real.py`:

```python
def test_todo_valor_do_vocabulario_tem_anotacao(
    conversas: list[ConversaAnotada],
) -> None:
    """A cobertura era por campo; passa a ser por valor.

    `test_todo_campo_de_extracao_tem_anotacao` garante que nenhum dos nove
    campos fica em zero, e nao diz nada sobre os valores dentro deles. Uma
    regressao restrita a `RURAL` ou a `CONSORCIO` passava o gate sem que
    nenhum teste piscasse -- mesmo furo que
    `test_toda_intencao_do_enum_aparece` fecha para `Intencao`.

    A lista sai dos enums e do proprio tipo, e nao de uma lista a mao: valor
    novo no vocabulario quebra este teste em vez de nascer descoberto.
    """
    anotados = {
        f"{campo}={valor}"
        for conversa in conversas
        for turno in conversa.turnos
        if turno.campos
        for campo, valor in turno.campos.items()
        if campo in ("tipo_imovel", "urgencia", "forma_pagamento", "tem_imovel_para_vender")
    }
    esperados = {
        f"{campo}={membro.value}"
        for campo, enum in _VOCABULARIO.items()
        for membro in enum
    } | {"tem_imovel_para_vender=True", "tem_imovel_para_vender=False"}

    assert esperados - anotados == set(), f"valores sem anotacao: {sorted(esperados - anotados)}"
```

`_VOCABULARIO` já existe em `src/mobia/evals/corpus.py` e mapeia os três campos aos seus enums — importe de lá em vez de redeclarar.

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k vocabulario_tem_anotacao`

Expected: FAIL listando **cinco** valores: `forma_pagamento=CONSORCIO`, `forma_pagamento=INDEFINIDA`, `tipo_imovel=RURAL`, `urgencia=ATE_6_MESES`, `urgencia=SEM_PRESSA`.

`tem_imovel_para_vender=False` **não** aparece — a Task 2 já o fechou. Se aparecer, a Task 2 não entrou.

- [ ] **Step 3: Defina `FormaPagamento.INDEFINIDA`**

Em `src/mobia/domain/agente/schemas.py`, no docstring de `Extracao`, logo depois do parágrafo que explica o significado de `None`:

```
    `FormaPagamento.INDEFINIDA` nao e sinonimo de `None`, e a diferenca e o
    que a medicao cobra: `None` e "o lead nao falou de pagamento neste turno",
    `INDEFINIDA` e "o lead afirmou que ainda nao decidiu". A fala de
    `compra-15` indice 0 -- "ainda nao decidi se vou financiar ou pagar a
    vista" -- e o caso: ele falou de pagamento, e o que disse foi que nao
    escolheu.
```

Esta é uma das **duas** mudanças permitidas em `src/mobia/domain/` (ver Global Constraints).

- [ ] **Step 4: Acrescente as três conversas**

No fim de `evals/corpus/compra.yaml`, seguindo a formatação das conversas vizinhas:

```yaml
- id: compra-13
  descricao: chacara de fim de semana, sem pressa nenhuma
  turnos:
    - lead: "queria comprar uma chacara pra passar os fins de semana com a familia, perto de sao roque"
      intencao: COMPRA
      campos:
        tipo_imovel: RURAL
        regiao: sao roque
    # Unico turno do corpus que afirma SEM_PRESSA. A barra da TEC-239 e marco
    # temporal explicito para `urgencia`, e "nao tenho pressa nenhuma" e
    # afirmacao direta de horizonte, nao entusiasmo -- o oposto simetrico de
    # "quero fechar logo", que nao anota.
    - lead: "nao tenho pressa nenhuma, quero achar o lugar certo mesmo que demore"
      intencao: COMPRA
      campos:
        urgencia: SEM_PRESSA
    - lead: "o acesso costuma ser por estrada de terra por ali?"
      intencao: COMPRA
      campos: {}

- id: compra-14
  descricao: contemplado no consorcio, carta vencendo em seis meses
  turnos:
    - lead: "fui contemplado no consorcio e quero usar a carta num apartamento de 2 quartos ate 400 mil"
      intencao: COMPRA
      campos:
        forma_pagamento: CONSORCIO
        tipo_imovel: APARTAMENTO
        quartos: 2
        faixa_preco_max: 400000
    - lead: "a carta vence em seis meses, entao preciso fechar ate la"
      intencao: COMPRA
      campos:
        urgencia: ATE_6_MESES
    # Anota pela regra da TEC-239: quem pergunta se pode usar um meio esta
    # dizendo que pretende usa-lo. Mesma forma de fala de `borda-injecao-01`
    # indice 1 e `compra-02` indice 1.
    - lead: "voces aceitam carta de consorcio de qualquer administradora?"
      intencao: COMPRA
      campos:
        forma_pagamento: CONSORCIO

- id: compra-15
  descricao: comprador que ainda nao decidiu como paga
  turnos:
    # Unico turno que afirma FormaPagamento.INDEFINIDA. Ele falou de
    # pagamento -- por isso nao e `None` -- e o que disse foi que nao
    # escolheu. Ver o docstring de `Extracao`.
    - lead: "quero comprar um apartamento na zona norte, mas ainda nao decidi se vou financiar ou pagar a vista"
      intencao: COMPRA
      campos:
        tipo_imovel: APARTAMENTO
        regiao: zona norte
        forma_pagamento: INDEFINIDA
    - lead: "voces tem plantao de visita no fim de semana?"
      intencao: COMPRA
      campos: {}
```

- [ ] **Step 5: Acrescente `chacara` e `sitio` aos guardas e à regra**

`compra-13` índice 0 diz "chacara", e nenhum dos dois guardas de tipologia a conhece. Em `tests/unit/test_evals_corpus_real.py`, acrescente as duas ao regex de sinônimos:

```python
_SINONIMOS_DE_TIPO_IMOVEL = re.compile(
    r"\b(kitnet|studio|flat|cobertura|sobrado|republica|chacara|chacaras|sitio|sitios)\b"
)
```

E em `src/mobia/evals/corpus.py`, à regra de sinônimos do docstring de `TurnoAnotado`:

```
      `chacara` e `sitio` sao `RURAL` (TEC-246). Entram pelo mesmo motivo dos
      outros: ninguem diz "quero comprar um rural", entao sem a traducao no
      corpus a extracao certa contaria `extra`.
```

**Não** mexa em `_LITERAIS_DE_TIPO_IMOVEL` — ele varre as palavras do enum, e `rural` não aparece em fala nenhuma. Se você se pegar acrescentando `chacara` lá, parou no guarda errado.

- [ ] **Step 6: Atualize o teste da contagem de conversas, e o nome dele**

Em `tests/unit/test_evals_corpus_real.py`:

```python
def test_o_corpus_tem_todas_as_conversas_declaradas(
    conversas: list[ConversaAnotada],
) -> None:
    """Cinquenta vieram do card da TEC-134; a TEC-246 acrescentou tres
    arquetipos que o vocabulario exigia e o corpus nao tinha -- chacara,
    consorcio e pagamento indefinido.

    O nome nao diz mais o numero de proposito: `cinquenta` no identificador
    envelheceu junto com o valor, e este repo ja perdeu tempo com numero
    embutido em prosa.
    """
    assert len(conversas) == 53
```

Grepe por `cinquenta` no repositório: se algum outro texto citar o nome antigo do teste, atualize junto.

- [ ] **Step 7: Confira as contagens e a cobertura**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q
.venv/Scripts/python.exe -c "
from collections import Counter
from pathlib import Path
from mobia.evals.corpus import carregar, total_de_turnos
c = carregar(Path('evals/corpus'))
pos = sum(1 for x in c for t in x.turnos if t.positivo)
neg = sum(1 for x in c for t in x.turnos if t.negativo)
anot = sum(len(t.campos) for x in c for t in x.turnos if t.campos)
print('conversas', len(c), '| turnos', total_de_turnos(c), '| positivos', pos,
      '| negativos', neg, '| fora', total_de_turnos(c)-pos-neg, '| anotacoes', anot)
campos = Counter(k for x in c for t in x.turnos if t.campos for k in t.campos)
for k, v in sorted(campos.items(), key=lambda kv: -kv[1]): print(f'  {v:3d} {k}')
"
```

Expected, exatamente:

```
conversas 53 | turnos 146 | positivos 62 | negativos 68 | fora 16 | anotacoes 96
   36 tipo_imovel
   23 regiao
   11 forma_pagamento
   10 quartos
    7 urgencia
    4 faixa_preco_max
    3 tem_imovel_para_vender
    1 vagas
    1 faixa_preco_min
```

Se algum número divergir, **pare e reporte** — não ajuste as falas para bater o número.

- [ ] **Step 8: Suíte, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add evals/corpus src/mobia tests/unit/test_evals_corpus_real.py
git commit -m "feat(TEC-246): tres arquetipos novos fecham a cobertura por valor"
```

**Testes vizinhos podem reprovar, e não é regressão.** Qualquer teste que conte conversas, turnos ou distribuição por categoria vai ver números maiores. Se algum reprovar, atualize a expectativa e **diga no relatório qual e por quê**.

---

### Task 4: Os pisos que a amostra nova permite

**Files:**
- Modify: `src/mobia/evals/metricas.py`

**Interfaces:**
- Consumes: corpus da Task 3.
- Produces: nada de código novo; dois valores de piso mudam.

- [ ] **Step 1: Meça o pior caso**

```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.evals.corpus import carregar, total_de_turnos
from mobia.evals.metricas import TETO_DE_CONVERSAS_ABANDONADAS as TETO
c = carregar(Path('evals/corpus'))
perfis = [(sum(1 for t in x.turnos if t.positivo),
           sum(1 for t in x.turnos if t.negativo),
           len(x.turnos)) for x in c]
for i, rotulo in ((0, 'positivos'), (1, 'negativos'), (2, 'turnos')):
    total = sum(p[i] for p in perfis)
    pior = total - sum(sorted((p[i] for p in perfis), reverse=True)[:TETO])
    print(f'{rotulo}: {total}, pior caso {pior}')
"
```

Expected: `positivos: 62, pior caso 47 | negativos: 68, pior caso 53 | turnos: 146, pior caso 129`.

Se divergir, **pare e reporte** — os pisos abaixo saem desses números e não do plano.

- [ ] **Step 2: Suba os dois pisos de amostra**

Em `src/mobia/evals/metricas.py`: `PISO_DE_TURNOS_ANOTADOS` de `38` para `45`, e `PISO_DE_TURNOS_NEGATIVOS` de `49` para `51`.

A margem de 2 sobre o pior caso (47 e 53) é a mesma que os pisos carregam desde a TEC-238. Acrescente ao comentário de cada constante a data e o pior caso medido, no formato que os comentários vizinhos já usam, **sem apagar a derivação anterior** — a história de como um piso foi calibrado é o que explica o número.

- [ ] **Step 3: `PISO_DE_TURNOS` fica em 120, e diga por quê**

Ele **não** sobe, e a razão não é preguiça: o comentário dele diz que abaixo de 120 turnos um único turno vale mais de 0,8% e a faixa amarela deixa de absorver ruído entre execuções. É piso **estatístico**, e não de erosão de amostra — a conta do pior caso não o governa. Acrescente uma linha registrando que o pior caso hoje é 129 e que o piso segue em 120 de propósito.

- [ ] **Step 4: O comentário de `TETO_DE_CONVERSAS_ABANDONADAS` envelheceu**

Ele cita "50 conversas e 138 turnos" e a folga de `138 - 120 = 18`. Hoje são 53 e 146, folga 26. Atualize a conta **preservando o registro histórico** — o mesmo tratamento que a TEC-245 deu quando corrigiu `45 - 14 = 31` para `55 - 15 = 40`.

- [ ] **Step 5: Suíte, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/metricas.py
git commit -m "docs(TEC-246): os pisos que a amostra de 53 conversas permite"
```

---

### Task 5: A documentação

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-29-tec-238-invencao-em-turno-negativo-design.md`
- Modify: `docs/superpowers/specs/2026-08-29-tec-242-sinonimos-de-tipo-imovel-design.md`
- Modify: `docs/superpowers/specs/2026-08-29-tec-245-triagem-dos-turnos-fora-da-medicao-design.md`

**Interfaces:**
- Consumes: as contagens da Task 3 e os pisos da Task 4.
- Produces: nada de código.

- [ ] **Step 1: As contagens do README**

Toda contagem que mudou: **53 conversas** (era 50), **146 turnos** (era 138), **62 positivos** (era 55), **68 negativos** (era 66), **16 fora** (era 17), **96 anotações** (era 83). A tabela de nove linhas passa a ser a da Task 3, Step 7.

Recalcule a aritmética da união. Hoje o README diz `83/(83+N)`; passa a `96/(96+N)`, e as faixas ficam:

| faixa | antes (83) | depois (96) |
|---|---|---|
| VERDE | `N` ≤ 9 | `N` ≤ **10** |
| AMARELO | `N` = 10–14 | `N` = **11–16** |
| VERMELHO | `N` ≥ 15 | `N` ≥ **17** |

Conferido por execução em aritmética inteira, e não por regra de três — a borda não fica onde a intuição decimal a coloca. **Confira de novo antes de escrever:** se a Task 3 fechou num número de anotações diferente de 96, estes três valores mudam.

```bash
.venv/Scripts/python.exe -c "
from mobia.evals.metricas import faixa_de, PISO_DE_PRECISAO_DA_EXTRACAO_PCT as P
ant = None
for n in range(0, 30):
    f = faixa_de(96, 96 + n, piso=P).name
    if f != ant: print(f'  primeiro {f} em N={n}'); ant = f
"
```

Expected: `primeiro VERDE em N=0 | primeiro AMARELO em N=11 | primeiro VERMELHO em N=17`.

O que **não** muda é a natureza do problema: a união continua descontando extração correta em turno onde aquele campo não foi anotado. A tolerância cresceu porque o denominador cresceu, e não porque o furo fechou.

- [ ] **Step 2: O bullet da cobertura por valor deixa de ser lacuna**

Hoje ele afirma que `RURAL`, `CONSORCIO`, `FormaPagamento.INDEFINIDA`, `SEM_PRESSA`, `ATE_6_MESES` e `tem_imovel_para_vender: false` não têm anotação, e que fechar isso "exige fala nova para cada valor, algumas bem artificiais, e ficou fora do escopo da TEC-239 de propósito".

Ele sai de "Lacunas conhecidas" e vira **garantia**: a cobertura é por valor, o teste deriva dos enums, e valor novo nasce quebrando o CI. **Diga o preço**: três das falas são sintéticas, escritas para o vocabulário e não colhidas de tráfego. Isso é escolha declarada, não acidente, e quem for ler um número baixo nesses turnos precisa saber.

- [ ] **Step 3: O bullet da colisão do `prédio` sai**

A TEC-245 escreveu um bullet dizendo que a colisão está aberta por decisão, com os sete turnos enumerados. Ela deixou de existir. Substitua por um registro curto de que a TEC-246 deu eixo único ao critério e de qual leitura venceu — **não apague a história**: o argumento da TEC-238 estava certo quando foi feito, e o que mudou foi a regra de anáfora ter passado a existir.

- [ ] **Step 4: `normalizar_regiao` ganha registro**

A seção da TEC-241 descreve a forma canônica de `regiao`. Acrescente que a TEC-246 fechou a assimetria das três famílias, com o motivo: o corpus só exercitava `na regiao da/do`, o furo era latente, e forma não-canônica de `regiao` respondeu por 10 das 29 discrepâncias de 28/08.

- [ ] **Step 5: Emende os três specs**

**Não reescreva o texto original de nenhum.** Bloco de emenda datado em cada:

- **TEC-238** — sua exclusão de `aluguel-09` índice 2 foi derrubada. A emenda diz que a decisão estava certa quando tomada (a regra de anáfora não existia) e que a TEC-246 a substituiu por eixo único.
- **TEC-242** — sua regra citava `aluguel-09` índice 2 como caso canônico de contêiner genérico ficar **fora da medição**. O critério de "nomear a tipologia" continua valendo; o que muda é o balde. E `chacara`/`sitio` entram na tabela de sinônimos.
- **TEC-245** — documentou a colisão sem resolver e listou os sete turnos. A emenda diz que a TEC-246 resolveu, e como.

- [ ] **Step 6: Rode e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff check src tests alembic evals
git add README.md docs/superpowers/
git commit -m "docs(TEC-246): a regua fechada, e as emendas aos tres specs que ela mexe"
```

---

## Encerramento

- [ ] **Suíte inteira, lint, tipos** uma última vez.

- [ ] **Critérios de aceitação do card:**

| critério | estado esperado ao fim |
|---|---|
| Todo valor do vocabulário tem anotação | ✅ `test_todo_valor_do_vocabulario_tem_anotacao`, derivado dos enums |
| Valor novo nasce quebrando o teste | ✅ a lista sai de `_VOCABULARIO` e do tipo, não de lista à mão |
| A mesma forma de fala não recebe dois tratamentos | ✅ `aluguel-09` i2 e `aluguel-01` i1 no mesmo balde |
| `FormaPagamento.INDEFINIDA` tem significado escrito | ✅ docstring de `Extracao` |
| `normalizar_regiao` simétrica nas três famílias | ✅ sete prefixos, invariante verde |
| Contagens e pisos conferidos por execução | ✅ |
| O efeito na precisão de extração | ❌ **não entregue** — exige execução paga (D8) |

- [ ] **Não rode `pytest evals`.**

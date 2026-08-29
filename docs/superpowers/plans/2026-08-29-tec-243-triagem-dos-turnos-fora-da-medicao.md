# TEC-243 — Triagem dos turnos fora da medição: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Levar a cobertura de invenção de 37 para 66 turnos, e fazer com que nenhum turno fique fora da medição sem motivo escrito e vigiado.

**Architecture:** Só anotação, comentário e teste. Nada em `src/mobia/domain/`. As 56 falas fora da medição são triadas em três baldes — 10 positivos, 29 negativos `{}`, 17 exclusões — e dois guardas novos impedem que a decisão se perca: um varre as palavras literais do vocabulário, outro trava o conjunto exato dos turnos fora da medição.

**Tech Stack:** Python 3.12+, pytest, YAML. Nenhuma dependência nova.

**Spec:** [docs/superpowers/specs/2026-08-29-tec-243-triagem-dos-turnos-fora-da-medicao-design.md](../specs/2026-08-29-tec-243-triagem-dos-turnos-fora-da-medicao-design.md)

## Global Constraints

- **Número do card é provisório.** `TEC-243` é o próximo da sequência, não um número confirmado no Jira. Se o real for outro, `sed` nos dois documentos e `git mv` nos nomes antes do commit final.
- **Comandos:** `.venv/Scripts/python.exe -m pytest tests/unit -q` (leva ~4-8 min nesta máquina — **rode em primeiro plano e aguarde**; se o harness mover para segundo plano, **leia o arquivo de saída até o fim**, a notificação não chega); `... -m ruff check src tests alembic evals`; `... -m ruff format src tests alembic`; `... -m mypy src`.
- **NUNCA rode `pytest evals`.** É pago — uma chamada a uma API de LLM por turno do corpus. Nada aqui precisa dele, e o efeito desta card **não será medido** (D5 do spec).
- **Nenhuma mudança em `src/mobia/domain/`.** Prompt e schema não entram. Se você se pegar editando `classificador.py` ou `schemas.py`, pare.
- Código e comentários em **português sem acentos**; README e specs **com** acentos.
- **`campos` presente é contrato de anotação completa.** Ao anotar um turno, enumere tudo o que a fala afirma — e só o que ela afirma.
- **Convenção de índice de turno: 0-based.** "primeiro turno" é índice 0. Não use "t1"/"t2".
- **Contagens conferidas por execução, não por leitura.**
- A branch já carrega uma correção do README não commitada (o bullet da convenção por-turno, `README.md:1515-1534`). Ela entra na Task 4, não antes.


## Emenda de 29/08/2026 — durante a execução, depois da Task 2

A revisão da Task 2 achou que o spec tratava a mesma fala de duas maneiras:
`borda-mista-02` i2 e `compra-02` i2 dizem ambas "perto do metro", e uma estava
excluída enquanto a outra virou negativo. **Ruling: `compra-02` i2 vira exclusão
documentada**, porque `normalizar_regiao("perto do metro")` devolve `"metro"` em
vez de descartar — então o negativo contaria invenção contra um modelo que só
repetiu a fala. O spec tem a emenda completa.

Efeito, já refletido nas Tasks 3 e 4 abaixo: negativos **66** (não 67), fora da
medição **17** (não 16), `PISO_DE_TURNOS_NEGATIVOS` **49** (não 50). Positivos
(55) e anotações de campo (83) não mudam.

**As Tasks 1 e 2 abaixo estão como foram executadas** — os números dentro delas
(30 negativos, 16 exclusões, 34 turnos no RED) descrevem o que aconteceu na
hora, e o commit de correção veio depois. Não os reescreva: a história de
execução é o que torna o plano auditável.

---

### Task 1: O guarda das palavras literais do vocabulário

Fecha o furo que a TEC-242 deixou: o guarda dela varre seis sinônimos e não varre `apartamento`, `casa`, `terreno`.

**Files:**
- Modify: `tests/unit/test_evals_corpus_real.py`
- Modify: `evals/corpus/borda.yaml`, `evals/corpus/follow_up.yaml`

**Interfaces:**
- Consumes: nada.
- Produces: corpus com 51 turnos positivos e 79 anotações de campo.

- [ ] **Step 1: Extraia o laço do guarda da TEC-242 para um helper**

O teste da TEC-242 (`test_todo_turno_com_sinonimo_tem_tipo_imovel_anotado`, hoje no fim de `tests/unit/test_evals_corpus_real.py`) tem um laço que o guarda novo repete inteiro. Extraia antes de duplicar. Acima do teste existente:

```python
def _turnos_sem_tipo_imovel(
    conversas: list[ConversaAnotada],
    padrao: re.Pattern[str],
    excecoes: set[tuple[str, int]],
) -> list[tuple[str, int, str]]:
    """Turnos cuja fala casa `padrao` e que nao anotam `tipo_imovel`.

    Os dois guardas de tipologia diferem so no vocabulario que varrem e nas
    excecoes que aceitam; o laco e o mesmo, e duas copias dele divergiriam.
    """
    faltando = []
    for conversa in conversas:
        for indice, turno in enumerate(conversa.turnos):
            if (conversa.id, indice) in excecoes:
                continue
            if not padrao.search(turno.lead.casefold()):
                continue
            if not (turno.campos and "tipo_imovel" in turno.campos):
                faltando.append((conversa.id, indice, turno.lead[:50]))
    return faltando
```

E troque o corpo do teste da TEC-242 pelas duas linhas equivalentes, preservando o docstring dele **sem alterar uma palavra**:

```python
    faltando = _turnos_sem_tipo_imovel(
        conversas, _SINONIMOS_DE_TIPO_IMOVEL, _SEM_TIPO_APESAR_DO_SINONIMO
    )
    assert faltando == [], f"turnos com sinonimo e sem `tipo_imovel`: {faltando}"
```

- [ ] **Step 2: Rode a suíte de corpus para confirmar que a extração não mudou nada**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q`

Expected: PASS, tudo verde. Se algo reprovar aqui, a extração do helper mudou comportamento — desfaça e refaça.

- [ ] **Step 3: Escreva o guarda novo, que falha**

Logo abaixo do teste da TEC-242:

```python
# As palavras do proprio vocabulario, e nao os sinonimos da TEC-242. O guarda
# dela varre "kitnet" e "sobrado"; um turno que diz "apartamento" com todas as
# letras passava batido, e dois turnos POSITIVOS -- anotacao declarada
# completa -- estavam nesse estado.
#
# `apto` entra porque o corpus ja o usa (`aluguel-05` i0, `borda-injecao-01`
# i1). `sala comercial` entra como locucao, e nao `comercial` sozinho, que
# aparece em "uso comercial de saude" descrevendo alvara e nao tipologia.
_LITERAIS_DE_TIPO_IMOVEL = re.compile(r"\b(apartamento|apto|casa|terreno|sala comercial)\b")

# O imovel que o lead TEM nao e o que ele procura -- a regra da TEC-239, que
# ja esta no docstring de `TurnoAnotado` e ate agora nao tinha teste. Estes
# dois turnos sao o caso literal dela: os dois anotam
# `tem_imovel_para_vender: true` e nenhum anota `tipo_imovel`, e os dois estao
# certos.
_TIPO_E_DO_IMOVEL_QUE_O_LEAD_TEM = {("follow-up-03", 0), ("follow-up-06", 0)}


def test_todo_turno_com_palavra_do_vocabulario_tem_tipo_imovel_anotado(
    conversas: list[ConversaAnotada],
) -> None:
    """A regra do imovel que o lead TEM ganha guarda.

    A TEC-242 fechou isto para sinonimos e deixou aberto para as palavras
    literais: um turno novo que diga "apartamento" e nao anote `tipo_imovel`
    entrava sem tipo em silencio, e a extracao certa contava `extra`.

    As excecoes nao sao valvula de escape: cada uma e um turno em que a
    tipologia descreve o imovel que o lead ja possui. Turno novo tem de
    escolher entre anotar o tipo ou entrar aqui com motivo escrito.
    """
    faltando = _turnos_sem_tipo_imovel(
        conversas, _LITERAIS_DE_TIPO_IMOVEL, _TIPO_E_DO_IMOVEL_QUE_O_LEAD_TEM
    )
    assert faltando == [], f"turnos com palavra do vocabulario e sem `tipo_imovel`: {faltando}"
```

- [ ] **Step 4: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k vocabulario`

Expected: FAIL, listando **exatamente seis** turnos: `borda-mista-01` i1, `borda-mista-02` i1, `borda-longa-01` i0, `follow-up-01` i0, `follow-up-04` i0 e `follow-up-07` i2.

Se a lista vier diferente de seis, **pare e reporte** — a triagem do spec não bate com o corpus.

- [ ] **Step 5: Anote os seis**

Em `evals/corpus/borda.yaml`:

```yaml
# borda-mista-01, indice 1 -- o bloco `campos` e novo
    - lead: "vim pelo anuncio do face, quero saber mais sobre aquele terreno em cotia pra comprar"
      intencao: COMPRA
      campos:
        tipo_imovel: TERRENO
        regiao: cotia
```

```yaml
# borda-mista-02, indice 1
    - lead: "mas aproveitando, voces tem apartamento pra alugar na regiao do ipiranga?"
      intencao: ALUGUEL
      campos:
        tipo_imovel: APARTAMENTO
        regiao: ipiranga
```

```yaml
# borda-longa-01, indice 0
    - lead: "vi um anuncio de vcs no instagram, sobre um apartamento na aclimacao"
      intencao: INDEFINIDA
      campos:
        tipo_imovel: APARTAMENTO
        regiao: aclimacao
```

Em `evals/corpus/follow_up.yaml`:

```yaml
# follow-up-01, indice 0
    - lead: "oi, sou eu de novo, faz um tempo que nao falamos. ainda ta de pe aquele apartamento que vc me mostrou?"
      intencao: COMPRA
      campos:
        tipo_imovel: APARTAMENTO
```

```yaml
# follow-up-04, indice 0
    - lead: "e ai, lembra de mim? tava vendo aquela casa pra comprar mes passado"
      intencao: COMPRA
      campos:
        tipo_imovel: CASA
```

```yaml
# follow-up-07, indice 2 -- SEM `urgencia`, e o comentario explica por que
    # `quero fechar logo` NAO anota `urgencia`: a barra da TEC-239 e marco
    # temporal explicito, e entusiasmo nao e marco. O turno entra na medicao
    # pelos campos que ele nomeia -- tipologia e quartos --, e a anotacao
    # completa e essa. Ficar fora da medicao inteiro por causa de um campo que
    # a fala nao afirma era exclusao larga de mais.
    - lead: "e entao, aquele apartamento de 3 quartos que a gente via, ainda ta disponivel? quero fechar logo"
      intencao: COMPRA
      campos:
        tipo_imovel: APARTAMENTO
        quartos: 3
```

**Atenção ao `borda-longa-01` i0:** o comentário do índice 2 dessa mesma conversa diz que repetir "o apartamento da aclimacao" ali é `extra` de propósito. Ele continua verdadeiro e **não deve ser tocado** — o que muda é que o turno 0 passa a afirmar o que o turno 2 não repete.

- [ ] **Step 6: Rode para ver passar, e confira as contagens**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.evals.corpus import carregar, total_de_turnos
c = carregar(Path('evals/corpus'))
pos = sum(1 for x in c for t in x.turnos if t.positivo)
neg = sum(1 for x in c for t in x.turnos if t.negativo)
anot = sum(len(t.campos) for x in c for t in x.turnos if t.campos)
print('turnos', total_de_turnos(c), '| positivos', pos, '| negativos', neg,
      '| fora', total_de_turnos(c)-pos-neg, '| anotacoes', anot)
"
```

Expected, exatamente:

```
turnos 138 | positivos 51 | negativos 37 | fora 50 | anotacoes 79
```

Se algum número divergir, **pare e reporte** — não ajuste o plano ao corpus.

- [ ] **Step 7: Lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add tests/unit/test_evals_corpus_real.py evals/corpus
git commit -m "feat(TEC-243): o guarda cobre as palavras literais do vocabulario"
```

---

### Task 2: A triagem das cinquenta restantes

**Files:**
- Modify: `tests/unit/test_evals_corpus_real.py`
- Modify: os cinco arquivos de `evals/corpus/`

**Interfaces:**
- Consumes: o corpus da Task 1 (51 positivos, 79 anotações).
- Produces: corpus com 55 positivos, 67 negativos, 16 turnos fora da medição, 83 anotações.

- [ ] **Step 1: Escreva o guarda do conjunto, que falha**

Em `tests/unit/test_evals_corpus_real.py`:

```python
# Os turnos que ficam FORA da medicao de extracao, e o motivo de cada um em
# uma linha. A lista e exaustiva de proposito: turno novo sem `campos` quebra
# este teste, e quem o acrescentar tem de decidir -- anotar ou entrar aqui.
#
# Antes desta card havia 56 turnos fora da medicao e cinco motivos escritos.
# Os outros 51 nao eram decisao tomada, eram silencio, e silencio numa regua
# le como "nao ha o que medir aqui" quando na verdade era "ninguem olhou".
_FORA_DA_MEDICAO = {
    ("aluguel-03", 1): "atributo (terrea) sugere CASA sem nomear a tipologia",
    ("aluguel-09", 2): "pergunta de processo que pressupoe o predio (TEC-238)",
    ("borda-evasivo-02", 1): "omissao nao e asercao de completude (TEC-238)",
    ("borda-evasivo-02", 2): "omissao nao e asercao de completude (TEC-238)",
    ("borda-mista-01", 2): "escritura: pressupoe o terreno do turno anterior",
    ("borda-mista-02", 2): "perto do metro: proximidade sem toponimo",
    ("compra-01", 1): "850 mil acima do que consigo: teto sugerido, nao afirmado",
    ("compra-04", 1): "mais que o dobro do que eu tinha em mente: teto sugerido",
    ("compra-07", 1): "sabado de manha: sem ancora de semana",
    ("compra-08", 2): "parcelamento direto nao e valor de FormaPagamento",
    ("compra-11", 1): "permuta com carro nao e valor de FormaPagamento",
    ("follow-up-01", 1): "juntar entrada sugere financiamento sem nomear",
    ("follow-up-03", 1): "pergunta de processo que pressupoe o imovel (TEC-238)",
    ("follow-up-03", 2): "financiamento que o lead ja tem, nao o pretendido (TEC-238)",
    ("investimento-04", 1): "pressupoe o financiamento, nao pergunta se pode usar",
    ("investimento-05", 0): "grana parada sugere A_VISTA sem afirmar",
}


def test_todo_turno_fora_da_medicao_tem_motivo_escrito(
    conversas: list[ConversaAnotada],
) -> None:
    """Fora da medicao passa a ser decisao, e nao esquecimento.

    Turno sem `campos` nao tem cobertura de invencao nenhuma: nao ha
    `esperado` contra o qual comparar, entao o turno sai da conta inteiro. Que
    isso seja verdade para 16 turnos e escolha; que fosse verdade para 56 sem
    ninguem ter olhado era acidente.

    Comentario de YAML nao sobrevive ao `yaml.safe_load`, entao o conjunto
    declarado aqui e o que guarda -- o comentario no arquivo e para quem le o
    corpus.
    """
    fora = {
        (conversa.id, indice)
        for conversa in conversas
        for indice, turno in enumerate(conversa.turnos)
        if turno.campos is None
    }
    assert fora == set(_FORA_DA_MEDICAO), (
        f"sem motivo escrito: {sorted(fora - set(_FORA_DA_MEDICAO))}; "
        f"declarados e ja anotados: {sorted(set(_FORA_DA_MEDICAO) - fora)}"
    )
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k motivo_escrito`

Expected: FAIL, com **34 turnos** em "sem motivo escrito" e nenhum em "declarados e já anotados".

Se algum turno aparecer no segundo grupo, **pare e reporte** — a Task 1 anotou um turno que o spec classificou como exclusão.

- [ ] **Step 3: Anote os quatro positivos restantes**

Estes quatro não têm palavra do vocabulário na fala, então a Task 1 não os alcançou. Cada um afirma campo e entra na medição:

| arquivo | conversa, turno | `campos` | por quê |
|---|---|---|---|
| `follow_up.yaml` | `follow-up-01` i2, *"da pra remarcar uma visita pra essa semana?"* | `{urgencia: IMEDIATA}` | precedente de `borda-longa-01` i2, já no corpus: marcar visita com marco temporal explícito conta |
| `follow_up.yaml` | `follow-up-08` i0, *"consegui aprovar o financiamento! bora marcar a assinatura do contrato"* | `{forma_pagamento: FINANCIAMENTO}` | o financiamento aqui é o meio que ele **vai** usar, e não o que ele já tem — o oposto de `follow-up-03` i2 |
| `follow_up.yaml` | `follow-up-08` i1, *"pode ser essa sexta a tarde?"* | `{urgencia: IMEDIATA}` | *"essa sexta"* é marco temporal explícito |
| `compra.yaml` | `compra-02` i1, *"voces trabalham com financiamento pela caixa?"* | `{forma_pagamento: FINANCIAMENTO}` | regra da TEC-239 no docstring de `TurnoAnotado`: quem pergunta se pode usar um meio pretende usá-lo — igual a `borda-injecao-01` i1 |

Em `follow-up-08` i0, escreva o comentário junto, porque a fala tenta duas anotações e só uma cola:

```yaml
    # Sem `urgencia`: "bora marcar a assinatura" e entusiasmo, e a barra da
    # TEC-239 e marco temporal explicito. O turno seguinte ("essa sexta a
    # tarde") tem o marco, e e la que `urgencia` entra.
    - lead: "consegui aprovar o financiamento! bora marcar a assinatura do contrato"
      intencao: COMPRA
      campos:
        forma_pagamento: FINANCIAMENTO
```

- [ ] **Step 4: Anote os trinta negativos**

Acrescente `campos: {}` a cada um. São trinta, e nenhum precisa de comentário próprio — o critério fica no docstring (Task 3).

`aluguel.yaml`: `aluguel-01` i1, `aluguel-01` i2, `aluguel-02` i1, `aluguel-05` i2, `aluguel-10` i1.

`borda.yaml`: `borda-longa-01` i1, `borda-generica-01` i0.

`compra.yaml`: `compra-02` i2, `compra-10` i0, `compra-12` i1.

`follow_up.yaml`: `follow-up-02` i0, `follow-up-04` i1, `follow-up-04` i2, `follow-up-05` i0, `follow-up-06` i2.

`investimento.yaml`: `investimento-01` i1, `investimento-01` i2, `investimento-02` i0, `investimento-02` i1, `investimento-03` i0, `investimento-03` i1, `investimento-03` i2, `investimento-04` i2, `investimento-05` i1, `investimento-06` i1, `investimento-06` i2, `investimento-07` i1, `investimento-07` i2, `investimento-08` i0, `investimento-08` i2.

**Três desses merecem comentário, e só três:**

```yaml
# follow_up.yaml, follow-up-04 indice 1
    # Negativo, e a palavra "financiamento" na fala e justamente o motivo: o
    # banco NEGOU. Nao e a forma de pagamento pretendida, e um modelo que
    # extrair FINANCIAMENTO aqui esta inventando. E o negativo mais caro do
    # corpus, porque a isca esta escrita na propria fala.
    - lead: "resolvi nao comprar agora, o banco negou o financiamento. tem opcao de alugar ela por enquanto?"
      intencao: ALUGUEL
      campos: {}
```

```yaml
# aluguel.yaml, aluguel-01 indice 1
    # Negativo por anafora: "aquele mesmo predio" nao nomeia tipologia nem
    # regiao, e repetir os campos do turno 0 aqui conta `extra` -- mesma
    # decisao que os comentarios de `borda-longa-01` i2 e `compra-08` i3.
    - lead: "vcs tb tem opcao de comprar aquele mesmo predio? seria bom parar de pagar aluguel"
      intencao: COMPRA
      campos: {}
```

```yaml
# follow_up.yaml, follow-up-02 indice 0
    # Negativo pela regra do imovel que o lead TEM (TEC-239): ele e inquilino
    # de um imovel que ja alugou, e `Extracao` e sobre a busca. A anotacao
    # completa da busca, aqui, e "nada".
    - lead: "oi, sou inquilino de um imovel que alugamos com voces ano passado, o contrato venceu e ninguem me avisou o que fazer"
      intencao: SUPORTE_CONTRATO
      campos: {}
```

- [ ] **Step 5: Escreva o motivo das onze exclusões novas no YAML**

Cada turno que ficou sem `campos` ganha comentário acima da linha `- lead:`, com o texto da coluna "motivo" da tabela do balde C no spec. As cinco antigas (`follow-up-03` i1 e i2, `borda-evasivo-02` i1 e i2, `aluguel-09` i2) **já têm** e não devem ser reescritas.

O conjunto no teste é o guarda; o comentário é para quem lê o arquivo. Os dois têm de dizer a mesma coisa.

- [ ] **Step 6: Rode e confira as contagens**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q
.venv/Scripts/python.exe -c "
from pathlib import Path
from collections import Counter
from mobia.evals.corpus import carregar, total_de_turnos
c = carregar(Path('evals/corpus'))
pos = sum(1 for x in c for t in x.turnos if t.positivo)
neg = sum(1 for x in c for t in x.turnos if t.negativo)
anot = sum(len(t.campos) for x in c for t in x.turnos if t.campos)
print('turnos', total_de_turnos(c), '| positivos', pos, '| negativos', neg,
      '| fora', total_de_turnos(c)-pos-neg, '| anotacoes', anot)
campos = Counter(k for x in c for t in x.turnos if t.campos for k in t.campos)
for k, v in sorted(campos.items(), key=lambda kv: -kv[1]): print(f'  {v:3d} {k}')
"
```

Expected, exatamente:

```
turnos 138 | positivos 55 | negativos 67 | fora 16 | anotacoes 83
   33 tipo_imovel
   21 regiao
    9 quartos
    8 forma_pagamento
    5 urgencia
    3 faixa_preco_max
    2 tem_imovel_para_vender
    1 faixa_preco_min
    1 vagas
```

Se algum número divergir, **pare e reporte**.

- [ ] **Step 7: Rode a suíte inteira, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add tests/unit/test_evals_corpus_real.py evals/corpus
git commit -m "feat(TEC-243): trinta negativos, quatro positivos e dezesseis exclusoes com motivo"
```

**Testes vizinhos podem reprovar, e não é regressão.** Qualquer teste que conte turnos fora da medição verá 16 em vez de 56, e qualquer um que conte negativos verá 67 em vez de 37. Se algum reprovar, atualize a expectativa e **diga no relatório qual e por quê**.

---

### Task 3: O critério onde o anotador o lê, e os pisos

**Files:**
- Modify: `src/mobia/evals/corpus.py` (docstring de `TurnoAnotado`)
- Modify: `src/mobia/evals/metricas.py` (dois pisos)

**Interfaces:**
- Consumes: o corpus da Task 2.
- Produces: nada de código novo; dois valores de piso mudam.

- [ ] **Step 1: Escreva o critério de triagem no docstring de `TurnoAnotado`**

Em `src/mobia/evals/corpus.py`, acrescente às regras que já estão lá:

```
    - **O que decide entre negativo e fora da medicao (TEC-243).** Pergunta de
      processo NAO e motivo de exclusao por si so: o corpus anota `{}` em
      dezenas delas. O que exclui e a fala **pressupor um campo sem afirma-lo**
      ("pode ter animal no predio?" pressupoe o predio) ou **sugerir um valor
      sem nomea-lo** ("precisa ser terrea" sugere CASA; "850 mil ta acima do
      que consigo" sugere um teto). Nos dois casos um negativo puniria o
      modelo por ler a fala com razao, e um positivo inventaria anotacao --
      por isso o turno sai da medicao, com o motivo escrito.

      Anafora pura ("aquele mesmo predio", "ali mesmo", "nessa faixa") e
      negativo, e nao exclusao: a fala nao nomeia nada, e repetir o campo do
      turno anterior e `extra` de proposito.

      Turno fora da medicao tem entrada em `_FORA_DA_MEDICAO`
      (`tests/unit/test_evals_corpus_real.py`), com o motivo em uma linha. Nao
      ha mais turno sem `campos` por acidente.
```

- [ ] **Step 2: Meça o pior caso dos pisos**

```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.evals.corpus import carregar
from mobia.evals.metricas import TETO_DE_CONVERSAS_ABANDONADAS as TETO
c = carregar(Path('evals/corpus'))
perfis = [(sum(1 for t in x.turnos if t.positivo), sum(1 for t in x.turnos if t.negativo)) for x in c]
tp, tn = sum(p[0] for p in perfis), sum(p[1] for p in perfis)
pior_p = tp - sum(sorted((p[0] for p in perfis), reverse=True)[:TETO])
pior_n = tn - sum(sorted((p[1] for p in perfis), reverse=True)[:TETO])
print(f'positivos {tp}, pior caso {pior_p} | negativos {tn}, pior caso {pior_n}')
"
```

Expected: `positivos 55, pior caso 40 | negativos 66, pior caso 51`.

- [ ] **Step 3: Suba os dois pisos**

Em `src/mobia/evals/metricas.py`: `PISO_DE_TURNOS_ANOTADOS` de `30` para `38`, e `PISO_DE_TURNOS_NEGATIVOS` de `23` para `49`.

A margem de 2 sobre o pior caso (40 e 51) é a mesma que os pisos tinham antes desta card — 31 contra 30 e 25 contra 23 —, e não é folga generosa de propósito: o piso existe para pegar erosão da amostra, e um piso muito abaixo do pior caso real não pega nada. Acrescente ao comentário de cada constante a data e o pior caso medido, no formato que os comentários vizinhos já usam.

- [ ] **Step 4: Rode, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/
git commit -m "docs(TEC-243): o criterio de triagem, e os pisos que a amostra nova permite"
```

---

### Task 4: A documentação que ficou falsa

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-29-tec-238-invencao-em-turno-negativo-design.md`

**Interfaces:**
- Consumes: as contagens finais da Task 2 e os pisos da Task 3.
- Produces: nada de código.

- [ ] **Step 1: Preserve a correção que já está na árvore**

`README.md:1515-1534` já foi reescrito nesta branch, antes do card existir: o bullet que afirmava que *"`SISTEMA_DO_AGENTE` não diz em lugar nenhum que a extração é por turno"* ficou falso quando a TEC-240 pôs a frase no prompt. A reescrita está correta e **não deve ser desfeita**. Ela entra no commit desta task.

Ela pertence aqui porque a convenção por-turno é a régua desta triagem: metade das decisões do balde C sai dela.

- [ ] **Step 2: Reescreva o bullet dos 56 turnos fora da medição**

O bullet longo de "Lacunas conhecidas" que hoje diz *"56 turnos continuam fora da medição"* e enumera as quatro exclusões deliberadas. Ele muda em três pontos:

- **56 vira 17**, e a cobertura de invenção vai de 37 para **66 turnos**;
- a frase *"os outros 51 turnos fora da medição não têm exclusão documentada: são trabalho de anotação que ainda não foi feito, não decisão tomada"* **deixa de ser verdade** e sai;
- entra o que a triagem descobriu: a maioria daqueles 51 não era anotação atrasada, era pergunta de processo que o corpus já sabia anotar `{}` — e o que faltava era o critério escrito, não o trabalho.

Preserve o registro histórico das exclusões antigas: elas continuam sendo exclusões, e o motivo delas não mudou.

- [ ] **Step 3: Atualize a tabela de anotações por campo**

A tabela de nove linhas em "Lacunas conhecidas" (`tipo_imovel` 27, `regiao` 18, …) passa a ser a da Task 2, Step 6, com **83 anotações em 55 turnos positivos**.

Recalcule também a aritmética da união que o texto ao redor faz. Hoje ele diz que um modelo perfeito com `N` extrações corretas em campo não anotado tira `69/(69+N)`, com `N=7` ainda VERDE, `N=12` AMARELO e `N=13` VERMELHO. Com 83 anotações passa a ser `83/(83+N)`, e as faixas ficam:

| faixa | hoje (69) | depois (83) |
|---|---|---|
| VERDE | `N` ≤ 7 | `N` ≤ **9** |
| AMARELO | `N` = 8–12 | `N` = **10–14** |
| VERMELHO | `N` ≥ 13 | `N` ≥ **15** |

Conferido por execução contra `faixa_de(83, 83 + N, piso=PISO_DE_PRECISAO_DA_EXTRACAO_PCT)`, e não por regra de três — a comparação é em aritmética inteira e a borda não é onde a intuição decimal a coloca. Confira de novo antes de escrever: se a Task 2 fechou num número de anotações diferente de 83, estes três valores mudam.

O que **não** muda é a natureza do problema: a união continua descontando extração correta em turno onde aquele campo não foi anotado. A tolerância cresceu porque o denominador cresceu, e não porque o furo fechou.

- [ ] **Step 4: Corrija o bullet da barra de `urgencia`**

Ele afirma que *"`follow-up-07` índice 2 e `follow-up-08` índice 0 ficam fora da medição de extração"*. Os dois passam a estar **dentro**, anotados pelos campos que nomeiam. A barra de `urgencia` não mudou — o que muda é que ela deixa de tirar o turno inteiro da medição, e passa a tirar só o campo. Escreva essa distinção: é ela que o card corrige.

- [ ] **Step 5: Atualize os pisos citados no README**

Grepe por `PISO_DE_TURNOS_ANOTADOS` e `PISO_DE_TURNOS_NEGATIVOS` e por `30`/`23` no contexto deles. O bullet longo sobre o pior caso depois do abandono cita números da TEC-239 (20 turnos anotados, 32 anotações) que continuam sendo história correta — **não os reescreva**, mas acrescente o pior caso de hoje (40 positivos, 51 negativos).

- [ ] **Step 6: Emende o spec da TEC-238**

Ele registra as exclusões de `follow-up-03` i1 e i2 e de `borda-evasivo-02` i1 e i2 como decisões deliberadas. As quatro **continuam valendo** — este card não as desfaz, ele as acompanha com onze irmãs e um guarda.

**Não reescreva o texto original.** Acrescente um bloco de emenda datado dizendo que a TEC-243 triou as 51 restantes, que o conjunto de exclusões passou a ser exaustivo e vigiado por `_FORA_DA_MEDICAO`, e que as quatro exclusões originais foram confirmadas pela triagem, não substituídas. É o mesmo tratamento que a TEC-241 deu ao spec da TEC-145 e a TEC-242 ao da TEC-238.

- [ ] **Step 7: Rode e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff check src tests alembic evals
git add README.md docs/superpowers/
git commit -m "docs(TEC-243): a triagem escrita, e a emenda ao spec da TEC-238"
```

---

## Encerramento

- [ ] **Suíte inteira, lint, tipos** uma última vez.

- [ ] **Se o número do card no Jira não for 243**, `sed -i 's/TEC-243/TEC-XXX/g'` no spec, no plano, no README e nas mensagens de commit que ainda não subiram, mais `git mv` dos dois arquivos de `docs/superpowers/`.

- [ ] **Critérios de aceitação do card:**

| critério | estado esperado ao fim |
|---|---|
| Nenhum turno fora da medição sem motivo escrito | ✅ 17 turnos, cada um com entrada em `_FORA_DA_MEDICAO` e comentário no YAML |
| A regra do imóvel que o lead TEM ganha guarda | ✅ `test_todo_turno_com_palavra_do_vocabulario_tem_tipo_imovel_anotado` |
| Cobertura de invenção sobe de 37 para 66 turnos | ✅ conferido por execução |
| O critério de triagem fica onde um anotador o lê | ✅ docstring de `TurnoAnotado` |
| O efeito na precisão de extração | ❌ **não entregue** — exige execução paga (D5) |

- [ ] **Não rode `pytest evals`.**

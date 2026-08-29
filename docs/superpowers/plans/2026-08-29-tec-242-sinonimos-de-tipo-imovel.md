# TEC-242 — Sinônimos de `tipo_imovel`: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o corpus decidir que *kitnet* é apartamento e *sobrado* é casa, para a métrica parar de contar como erro a tradução que o modelo já faz certo.

**Architecture:** Só anotação e documentação. O schema da chamada é estrito — o modelo nunca devolve "kitnet" —, então não há mapa de tradução a escrever. A decisão vira regra no docstring de `TurnoAnotado`, anotações nos dez turnos, e um teste que impede a regra de apodrecer.

**Tech Stack:** Python 3.12+, pytest, YAML. Nenhuma dependência nova, nenhuma mudança em `src/mobia/domain/`.

**Spec:** [docs/superpowers/specs/2026-08-29-tec-242-sinonimos-de-tipo-imovel-design.md](../specs/2026-08-29-tec-242-sinonimos-de-tipo-imovel-design.md)

## Global Constraints

- **Comandos:** `.venv/Scripts/python.exe -m pytest tests/unit -q` (leva ~4-8 min nesta máquina — **rode em primeiro plano e aguarde**; se o harness mover para segundo plano, **leia o arquivo de saída até o fim**, a notificação não chega); `... -m ruff check src tests alembic evals`; `... -m ruff format src tests alembic`; `... -m mypy src`.
- **NUNCA rode `pytest evals`.** É pago — uma chamada a uma API de LLM por turno do corpus. Nada aqui precisa dele, e o efeito desta card **não será medido**.
- **Nenhuma mudança em `src/mobia/domain/agente/`.** Nada em `extrair`, no schema ou no prompt. Se você se pegar editando `classificador.py` ou `schemas.py`, pare — o desenho desta card é que não há código de tradução a escrever.
- Código e comentários em **português sem acentos**; README e specs **com** acentos.
- **A regra de anotação não pode ser afrouxada:** `campos` presente é contrato de anotação **completa**. Ao anotar um turno, enumere tudo o que a fala afirma, não só o `tipo_imovel`.
- **Contagens conferidas por execução, não por leitura.**

---

### Task 1: A regra, as anotações e o guarda

**Files:**
- Modify: `src/mobia/evals/corpus.py` (docstring de `TurnoAnotado`)
- Modify: `evals/corpus/aluguel.yaml`, `evals/corpus/compra.yaml`, `evals/corpus/investimento.yaml`
- Test: `tests/unit/test_evals_corpus_real.py`

**Interfaces:**
- Consumes: nada.
- Produces: corpus com 45 turnos positivos e 27 anotações de `tipo_imovel`.

- [ ] **Step 1: Escreva o teste que falha**

Em `tests/unit/test_evals_corpus_real.py`:

```python
# Palavras que o lead usa e que NAO estao em `TipoImovel`. Seis, e nao as
# cinco do mapa da TEC-242: `republica` entra aqui de proposito, apesar de
# nao ter traducao, para forcar o turno que a usa a aparecer na lista de
# excecoes com o motivo escrito em vez de sumir por nao ser detectado.
_SINONIMOS_DE_TIPO_IMOVEL = ("kitnet", "studio", "flat", "cobertura", "sobrado", "republica")

# `aluguel-07` i0 diz "procuro republica ou kitnet": o lead oferece duas
# tipologias e nao escolhe nenhuma. Anotar uma delas puniria o modelo por
# escolher a outra, que e o erro simetrico que a regua ja pune.
_SEM_TIPO_APESAR_DO_SINONIMO = {("aluguel-07", 0)}


def test_todo_turno_com_sinonimo_tem_tipo_imovel_anotado(
    conversas: list[ConversaAnotada],
) -> None:
    """A traducao que o modelo faz certo nao pode contar erro.

    O schema da chamada e estrito: o modelo nunca devolve "kitnet", ele
    devolve `APARTAMENTO`. Se o corpus nao anota nada nesse turno, a uniao
    conta o campo como `extra` -- erro cheio, por acertar. Foi assim que
    `tipo_imovel` virou 8 das 29 discrepancias da execucao de 28/08.

    Sem este teste, o proximo turno com "kitnet" entra sem tipo e a punicao
    volta em silencio.
    """
    faltando = []
    for conversa in conversas:
        for indice, turno in enumerate(conversa.turnos):
            if (conversa.id, indice) in _SEM_TIPO_APESAR_DO_SINONIMO:
                continue
            fala = turno.lead.casefold()
            if not any(s in fala for s in _SINONIMOS_DE_TIPO_IMOVEL):
                continue
            if not (turno.campos and "tipo_imovel" in turno.campos):
                faltando.append((conversa.id, indice, turno.lead[:50]))

    assert faltando == [], f"turnos com sinonimo e sem `tipo_imovel`: {faltando}"
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k sinonimo`

Expected: FAIL, listando **nove** turnos — `aluguel-01` i0, `compra-11` i0, `aluguel-05` i1, `aluguel-06` i0, `compra-06` i0/i1/i2, `compra-11` i2 e `investimento-01` i0. `aluguel-07` i0 **não** aparece, porque está na lista de exceções.

Se a lista vier diferente de nove, **pare e reporte** — o levantamento do spec não bate com o corpus.

- [ ] **Step 3: Acrescente `tipo_imovel` aos dois turnos que já são positivos**

Em `evals/corpus/aluguel.yaml`, `aluguel-01`, primeiro turno (*"oi, queria alugar um kitnet perto da usp…"*), o bloco `campos` passa a ser:

```yaml
      campos:
        regiao: perto da usp
        tipo_imovel: APARTAMENTO
```

Em `evals/corpus/compra.yaml`, `compra-11`, primeiro turno (*"vi o anuncio do sobrado na zona sul…"*):

```yaml
      campos:
        regiao: zona sul
        tipo_imovel: CASA
```

Estes dois são o caso caro: estavam anotados com anotação declarada completa, e omitiam o tipo.

- [ ] **Step 4: Anote os sete que estavam fora da medição**

Acrescente o bloco `campos` a cada um. A anotação é **completa** — enumere tudo o que a fala afirma, não só o tipo.

| arquivo | conversa, turno (pela fala) | `campos` |
|---|---|---|
| `aluguel.yaml` | `aluguel-05`, *"pode ser flat tambem, contanto que tenha internet incluida"* | `{tipo_imovel: APARTAMENTO}` |
| `aluguel.yaml` | `aluguel-06`, *"meu contrato de aluguel atual vence mes que vem, voces tem studio disponivel pra essa data?"* | `{tipo_imovel: APARTAMENTO, urgencia: ATE_3_MESES}` |
| `compra.yaml` | `compra-06`, *"vi uma cobertura duplex la no anuncio, ainda esta disponivel pra venda?"* | `{tipo_imovel: APARTAMENTO}` |
| `compra.yaml` | `compra-06`, *"tem churrasqueira na cobertura ou so na area comum do predio?"* | `{tipo_imovel: APARTAMENTO}` |
| `compra.yaml` | `compra-06`, *"qual o valor do condominio dessa cobertura?"* | `{tipo_imovel: APARTAMENTO}` |
| `compra.yaml` | `compra-11`, *"o sobrado tem escritura ja regularizada?"* | `{tipo_imovel: CASA}` |
| `investimento.yaml` | `investimento-01`, *"queria comprar um studio pra por no airbnb, qual bairro rende mais?"* | `{tipo_imovel: APARTAMENTO}` |

O `urgencia` de `aluguel-06` entra pela barra que a TEC-239 fixou: *"vence **mes que vem**"* é marco temporal explícito. Sem ele a anotação ficaria incompleta, e anotação incompleta não vira nota mais baixa do modelo — vira medição errada.

- [ ] **Step 5: Remova os comentários de exclusão que ficaram falsos**

Esta card **desfaz duas exclusões** que outras cards escreveram, porque elas existiam por não haver regra — e a regra passa a existir.

Em `evals/corpus/compra.yaml`, acima do turno *"o sobrado tem escritura ja regularizada?"*, há um comentário de três linhas dizendo que ele não foi anotado como negativo porque *"sobrado"* não está em `TipoImovel` e um modelo que devolve `CASA` está lendo com razão. **Ele agora contradiz o arquivo** — o turno passa a ser anotado `CASA`. Remova-o.

Faça uma varredura por comentários equivalentes: `grep -n "sobrado\|studio\|kitnet\|cobertura\|flat" evals/corpus/*.yaml`. Qualquer comentário que justifique **não** anotar por falta de regra tem de sair. Comentários que expliquem a anotação podem ficar.

- [ ] **Step 6: Escreva a regra no docstring de `TurnoAnotado`**

Em `src/mobia/evals/corpus.py`, acrescente às regras que já estão lá:

```
    - **Sinonimo de tipologia se anota pelo valor do vocabulario.** `kitnet`,
      `studio`, `flat` e `cobertura` sao `APARTAMENTO`; `sobrado` e `CASA`.
      Nao ha traducao em codigo, e nao pode haver: o schema da chamada e
      estrito, entao o modelo ja devolve o valor do enum -- ele traduz
      sozinho. O que faltava era o corpus decidir a mesma traducao, e sem essa
      decisao a traducao certa contava `extra`.

      `republica` NAO tem traducao: e uso, nao tipologia, e pode ser casa ou
      apartamento. O unico turno que a usa (`aluguel-07`, primeiro turno) diz
      "republica ou kitnet" -- o lead oferece duas e nao escolhe --, entao ele
      fica sem `tipo_imovel`, de proposito.
```

- [ ] **Step 7: Confira as contagens por execução**

Run:

```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.evals.corpus import carregar, total_de_turnos
c = carregar(Path('evals/corpus'))
pos = sum(1 for x in c for t in x.turnos if t.positivo)
neg = sum(1 for x in c for t in x.turnos if t.negativo)
tipo = sum(1 for x in c for t in x.turnos if t.campos and 'tipo_imovel' in t.campos)
print('turnos', total_de_turnos(c), '| positivos', pos, '| negativos', neg, '| fora', total_de_turnos(c)-pos-neg)
print('anotacoes de tipo_imovel', tipo)
"
```

Expected, exatamente:

```
turnos 138 | positivos 45 | negativos 37 | fora 56
anotacoes de tipo_imovel 27
```

Se algum número divergir, **pare e reporte** — não ajuste o plano ao corpus.

- [ ] **Step 8: Rode, lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/corpus.py evals/corpus tests/unit/test_evals_corpus_real.py
git commit -m "feat(TEC-242): o corpus decide que kitnet e apartamento e sobrado e casa"
```

**Um teste vizinho pode reprovar, e não é regressão:** `test_o_corpus_tem_turnos_negativos_anotados` e os pisos contam negativos, que não mudam; mas qualquer teste que conte turnos **fora da medição** vai ver 56 em vez de 63. Se algum reprovar, atualize a expectativa e **diga no relatório qual e por quê**.

---

### Task 2: A documentação que ficou falsa

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-29-tec-238-invencao-em-turno-negativo-design.md`

**Interfaces:**
- Consumes: as contagens finais da Task 1 (45 positivos, 27 anotações de `tipo_imovel`, 56 fora).
- Produces: nada de código.

- [ ] **Step 1: O bullet que diz que os sinônimos não têm dono**

O README tem um bullet afirmando que *"os sinônimos de `tipo_imovel` (kitnet, república, sobrado, …) seguem sem dono"* — escrito pela TEC-241, quando era verdade. **Agora tem dono, e é esta card.** Reescreva para descrever a política:

- o mapa de cinco entradas e onde ele vive (regra de anotação, não código);
- **por que não é código:** o schema é estrito, o modelo já devolve o valor do enum, então um mapa de tradução nunca teria entrada — seria código morto;
- `república` fora, com o motivo (uso, não tipologia; e a fala oferece duas);
- o que fica **perdido**: *kitnet*, *studio* e *flat* deixam de se distinguir de *apartamento* no estado, e isso muda faixa de preço e metragem para o lead. Preservar a distinção exigiria alargar `TipoImovel`, que mexe na coluna, no filtro da TEC-158 e no orçamento de contexto (hoje 587 de 600). É escolha, não esquecimento;
- e o agravante que a TEC-240 registrou: `_texto_do_estado` alimenta o **prompt de verdade**, então a memória que o modelo enxerga também lê `APARTAMENTO`, e quando as mensagens literais saírem da janela a palavra do lead some da visão dele.

- [ ] **Step 2: O bullet que documenta a exclusão de `compra-11`**

Há um bullet no README dizendo que *"`compra-11` (…) fica de fora porque `sobrado` não…"*. Esse turno passa a ser anotado `CASA`. **O bullet ficou falso** — reescreva ou remova, conforme couber no texto ao redor.

- [ ] **Step 3: As contagens**

Toda contagem de turnos do README que mudou: **45 positivos** (era 38), **56 fora da medição** (era 63), **27 anotações de `tipo_imovel`** (era 18). Negativos seguem em **37**, turnos em **138**.

Conte por execução com o script do Step 7 da Task 1 e grepe o README por `38`, `63`, `18 ` e `tipo_imovel` para achar todas.

**Atenção à distinção que a TEC-238 estabeleceu:** "anotado" no sentido técnico (`campos is not None`) inclui os negativos; o README usa "anotados **como positivos**" onde precisa desambiguar. Preserve isso.

- [ ] **Step 4: Emende o spec da TEC-238**

Ele registra a exclusão de `compra-11` i2 como decisão deliberada, com o argumento de que *"um modelo que devolve `CASA` para 'sobrado' está lendo a fala com razão"*.

**Não reescreva o texto original** — a decisão estava certa quando foi tomada, e a história tem de continuar legível. Acrescente um bloco de emenda datado dizendo que a TEC-242 criou a regra que faltava, que o turno passou a ser anotado `CASA`, e que o argumento original é justamente o que a nova regra formaliza.

É o mesmo tratamento que a TEC-241 deu ao spec da TEC-145.

- [ ] **Step 5: Rode e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff check src tests alembic evals
git add README.md docs/superpowers/specs/
git commit -m "docs(TEC-242): a regra escrita, e a emenda ao spec da TEC-238"
```

---

## Encerramento

- [ ] **Suíte inteira, lint, tipos** uma última vez.

- [ ] **Critérios de aceitação do card:**

| critério | estado |
|---|---|
| Teste com os pares reais (*kitnet*, *sobrado*) | ✅ o guarda da Task 1 cobre os dois, e mais quatro sinônimos |
| Os 10 turnos deixam de contradizer a política | ✅ nove anotados, `aluguel-07` i0 exceção com motivo escrito |
| A política fica registrada onde um anotador a lê | ✅ docstring de `TurnoAnotado` |
| Se não resolver a TEC-158, fica declarado | ✅ **resolve** — a coluna já só recebe valores do enum. O que fica declarado é a perda do termo original |
| As discrepâncias caem numa execução, com o número | ❌ **não entregue** — exige execução paga |

- [ ] **Não rode `pytest evals`.**

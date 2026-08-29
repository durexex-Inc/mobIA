# TEC-241 — Contrato de forma para `regiao`: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar a `regiao` uma forma canônica única, para que a medição pare de contar desacordo de forma como erro do modelo e o banco passe a guardar algo que a TEC-158 consiga filtrar.

**Architecture:** Uma função `normalizar_regiao` em `schemas.py`, com dois consumidores: `extrair` (grava canônico) e `_comparavel` do eval (compara canônico). Uma função só, porque duas divergem e a divergência só aparece na borda.

**Tech Stack:** Python 3.12+, pytest, dataclasses. Sem dependência nova.

**Spec:** [docs/superpowers/specs/2026-08-29-tec-241-contrato-de-forma-da-regiao-design.md](../specs/2026-08-29-tec-241-contrato-de-forma-da-regiao-design.md)

## Global Constraints

- **Comandos:** testes `.venv/Scripts/python.exe -m pytest tests/unit -q` (~2 min, rode em primeiro plano e aguarde); lint `... -m ruff check src tests alembic evals`; formatação `... -m ruff format src tests alembic`; tipos `... -m mypy src`. Os quatro passam antes de cada commit.
- **NUNCA rode `pytest evals`.** É pago — uma chamada a uma API de LLM por turno do corpus. Nada neste plano precisa dele.
- **Código e comentários em português sem acentos**, seguindo `src/mobia/`. Docstrings explicam *por quê*, não *o quê*.
- **Uma regra de forma, num lugar só.** Se você se pegar escrevendo a lista de prefixos duas vezes, pare — é o defeito que este plano existe para não cometer. O repositório já deletou `faixa_de_catastrofe` e extraiu `campos_a_gravar` pelo mesmo motivo.
- **`zona` nunca é removida.** `zona leste`, `zona sul` e `zona oeste` são nome de região, e três anotações do corpus dependem disso. Um teste guarda.
- **Não edite os cabeçalhos de `evals/corpus/*.yaml`.** O PR #14 (TEC-238) está mexendo neles e o conflito é garantido. A regra de anotação vai no docstring de `TurnoAnotado`.
- **Contagens conferidas por execução, não por leitura.**

---

### Task 1: `normalizar_regiao`, a função e só ela

**Files:**
- Modify: `src/mobia/domain/agente/schemas.py`
- Test: `tests/unit/test_extracao.py` (é onde `Extracao` e `preenchidos` já são testados)

**Interfaces:**
- Consumes: nada.
- Produces: `normalizar_regiao(texto: str) -> str` em `mobia.domain.agente.schemas`.

- [ ] **Step 1: Escreva os testes que falham**

```python
import pytest

from mobia.domain.agente.schemas import normalizar_regiao


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        # O lado ANOTADO sujo: as duas unicas anotacoes do corpus com preposicao.
        ("perto da usp", "usp"),
        ("perto da unicamp", "unicamp"),
        # O lado OBTIDO sujo, que e o caso maioritario: o modelo devolve a
        # forma da fala, e 16 das 18 anotacoes ja sao toponimo limpo.
        ("regiao do brooklin", "brooklin"),
        ("regiao dos jardins", "jardins"),
        ("regiao da paulista", "paulista"),
        ("na regiao da paulista", "paulista"),
        ("estacao vila madalena", "vila madalena"),
        # Prefixos encadeados caem no mesmo passe.
        ("perto da estacao vila madalena", "vila madalena"),
        # Caixa e espaco sobrando.
        ("  Vila   Mariana  ", "vila mariana"),
    ],
)
def test_normalizar_regiao_tira_o_ruido_de_referencia(bruto: str, esperado: str) -> None:
    assert normalizar_regiao(bruto) == esperado


@pytest.mark.parametrize("nome", ["zona leste", "zona sul", "zona oeste"])
def test_normalizar_regiao_nao_come_zona(nome: str) -> None:
    """`zona` e o nome, nao ruido. Tres anotacoes do corpus dependem disto, e
    perde-las transformaria a normalizacao no defeito que ela vem consertar."""
    assert normalizar_regiao(nome) == nome


@pytest.mark.parametrize(
    "nome", ["brooklin", "itaim bibi", "jardim das flores", "tatuape", "sp", "cotia"]
)
def test_normalizar_regiao_nao_mexe_em_toponimo_limpo(nome: str) -> None:
    assert normalizar_regiao(nome) == nome


def test_normalizar_regiao_so_tira_prefixo_e_nao_subcadeia() -> None:
    """"estacao" no meio de um nome sobrevive. So some quando abre a string."""
    assert normalizar_regiao("bairro estacao velha") == "bairro estacao velha"


def test_regiao_que_e_so_ruido_vira_vazio() -> None:
    """Quem decide o que fazer com o vazio e o chamador: `extrair` descarta o
    campo. Devolver o original aqui gravaria ruido no banco."""
    assert normalizar_regiao("perto da") == ""
    assert normalizar_regiao("   ") == ""


def test_normalizar_regiao_e_idempotente() -> None:
    """Vale por construcao, porque a remocao repete ate nao casar -- este teste
    e o que garante que continue valendo se alguem trocar o laco por um passe."""
    for bruto in ("perto da estacao vila madalena", "regiao do brooklin", "zona sul"):
        uma = normalizar_regiao(bruto)
        assert normalizar_regiao(uma) == uma
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py -q -k normalizar_regiao`

Expected: FAIL no import — `ImportError: cannot import name 'normalizar_regiao'`.

- [ ] **Step 3: Implemente**

Em `src/mobia/domain/agente/schemas.py`, depois dos enums e antes de `Extracao`:

```python
# Prefixos de referencia: o jeito de o lead localizar sem nomear. "perto da
# usp" nao e uma regiao, e uma frase com preposicao, e `_comparavel` faz so
# `strip` e `casefold` -- qualquer diferenca de forma contava erro cheio.
#
# `zona` NAO esta aqui, de proposito: `zona leste`, `zona sul` e `zona oeste`
# sao o nome, nao ruido, e tres anotacoes do corpus dependem disso.
_PREFIXOS_DE_REFERENCIA = (
    "na regiao da ",
    "na regiao do ",
    "regiao das ",
    "regiao dos ",
    "regiao da ",
    "regiao do ",
    "regiao de ",
    "proximo da ",
    "proximo do ",
    "proximo ao ",
    "proximo a ",
    "perto da ",
    "perto do ",
    "perto de ",
    "estacao ",
)


def normalizar_regiao(texto: str) -> str:
    """A forma canonica de `regiao`, na gravacao e na medicao.

    Existe uma so, com dois consumidores -- `extrair` e o `_comparavel` do eval
    --, porque duas regras de forma divergem e a divergencia so aparece na
    borda. Mesmo motivo de `faixa_de_catastrofe` ter sido deletada e de
    `campos_a_gravar` ter sido extraida.

    Normalizar perde informacao de proposito: "perto da usp" e "usp" viram a
    mesma coisa, e o lead que disse "perto da usp" queria proximidade, nao o
    campus. A troca e a favor do filtro estruturado da TEC-158, que compara
    `regiao` por igualdade em SQL -- "usp" e filtravel, "perto da usp" nao. O
    texto original da fala continua no historico de mensagens, cifrado, que e
    onde ele pertence.
    """
    limpo = " ".join(texto.split()).casefold()
    # Repete enquanto casar: "perto da estacao vila madalena" perde `perto da`
    # e so entao `estacao`. Um passe so deixaria metade do ruido -- a fala de
    # `aluguel-06` e exatamente esse caso --, e repetir e o que torna a funcao
    # idempotente por construcao em vez de por sorte.
    mudou = True
    while mudou:
        mudou = False
        for prefixo in _PREFIXOS_DE_REFERENCIA:
            if limpo == prefixo.strip():
                limpo = ""
                mudou = True
                break
            if limpo.startswith(prefixo):
                limpo = limpo[len(prefixo) :]
                mudou = True
                break
    return limpo
```

- [ ] **Step 4: Rode e confirme que passam**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py -q -k normalizar_regiao`

Expected: PASS, todos.

- [ ] **Step 5: Lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/agente/schemas.py tests/unit/test_extracao.py
git commit -m "feat(TEC-241): forma canonica de regiao, numa funcao so"
```

---

### Task 2: `extrair` grava a forma canônica

**Files:**
- Modify: `src/mobia/domain/agente/classificador.py` (`_regiao`, linhas ~177-181)
- Test: `tests/unit/test_extracao.py` (é onde `extrair` já é testada; `tests/unit/test_classificador.py` cobre a chamada ao modelo, não o parse)

**Interfaces:**
- Consumes: `normalizar_regiao(texto: str) -> str` da Task 1.
- Produces: `extrair` devolve `Extracao.regiao` já canônica, ou `None` quando a normalização esvazia.

- [ ] **Step 1: Escreva os testes que falham**

```python
def test_extrair_grava_regiao_na_forma_canonica() -> None:
    """O banco passa a guardar o que a TEC-158 consegue filtrar. Sem isto, a
    normalizacao existiria so para a medicao e o filtro SQL continuaria
    comparando formas que o modelo escolheu."""
    extracao = extrair({"regiao": "perto da estacao Vila Madalena"})

    assert extracao.regiao == "vila madalena"


def test_extrair_descarta_regiao_que_e_so_ruido() -> None:
    """Vazio nao pode ser gravado: a TEC-158 filtraria por string vazia. Segue
    a mesma regra das outras guardas de `extrair` -- campo malformado e
    descartado um a um, sem derrubar a resposta."""
    assert extrair({"regiao": "perto da"}).regiao is None


def test_extrair_preserva_toponimo_limpo() -> None:
    assert extrair({"regiao": "Itaim Bibi"}).regiao == "itaim bibi"
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_extracao.py -q -k regiao`

Expected: FAIL. O primeiro com `assert 'perto da estacao vila madalena' == 'vila madalena'` (hoje `_regiao` só faz `strip`), o segundo com `assert 'perto da' is None`, o terceiro com `assert 'Itaim Bibi' == 'itaim bibi'`.

- [ ] **Step 3: Implemente**

Substitua `_regiao` em `src/mobia/domain/agente/classificador.py`:

```python
def _regiao(bruto: Any) -> str | None:
    """Normaliza antes de truncar, e descarta o que sobra vazio.

    `normalizar_regiao` ja faz o colapso de espaco e o `casefold`, entao o
    `strip` de antes ficou dentro dela. O truncamento continua por ultimo:
    `lead_qualification.regiao` e `String(120)`, e normalizar so encurta.
    """
    if not isinstance(bruto, str):
        return None
    limpa = normalizar_regiao(bruto)
    return limpa[:MAX_CARACTERES_DA_REGIAO] if limpa else None
```

Acrescente `normalizar_regiao` ao import que já traz `Extracao`, `FormaPagamento`, `TipoImovel` e `Urgencia` de `mobia.domain.agente.schemas`.

- [ ] **Step 4: Rode e confirme**

Run: `.venv/Scripts/python.exe -m pytest tests/unit -q`

Expected: PASS. **Se algum teste antigo de `extrair` quebrar por causa do `casefold`** — por exemplo um que espere `"Zona Sul"` com maiúsculas —, isso é a mudança de comportamento que o spec declara (D4), não regressão: atualize a expectativa do teste para a forma canônica e diga no relatório qual teste foi e por quê.

- [ ] **Step 5: Lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/domain/agente/classificador.py tests/unit/test_extracao.py
git commit -m "feat(TEC-241): extrair grava regiao canonica, e descarta ruido puro"
```

---

### Task 3: A medição compara formas comparáveis

**Files:**
- Modify: `src/mobia/evals/metricas.py` (`_comparavel` ~361-374, e os dois pontos de chamada em ~403 e ~442)
- Test: `tests/unit/test_evals_metricas.py`

**Interfaces:**
- Consumes: `normalizar_regiao` da Task 1.
- Produces: `_comparavel(campo: str, valor: Any) -> Any` — **a assinatura muda**, ganha o nome do campo como primeiro parâmetro.

- [ ] **Step 1: Escreva os testes que falham**

```python
def test_regiao_com_preposicao_casa_com_o_toponimo() -> None:
    """O par que originou esta card: 10 das 29 discrepancias da execucao de
    28/08 eram `regiao`, todas `divergiu`, e nenhuma era erro do modelo."""
    observadas = [_observada({"regiao": "perto da usp"}, {"regiao": "usp"})]

    metrica = precisao_da_extracao(observadas)

    assert (metrica.acertos, metrica.total) == (1, 1)
    assert discrepancias_da_extracao(observadas) == []


def test_regiao_com_estacao_casa_com_o_bairro() -> None:
    observadas = [_observada({"regiao": "vila madalena"}, {"regiao": "estacao vila madalena"})]

    assert precisao_da_extracao(observadas).acertos == 1
    assert discrepancias_da_extracao(observadas) == []


def test_regioes_realmente_diferentes_continuam_divergindo() -> None:
    """A normalizacao nao pode fazer tudo casar com tudo -- ai ela deixaria de
    medir. `aluguel-02` troca de regiao no meio da conversa, e esse caso e o
    que prova que a sobrescrita e medida."""
    observadas = [_observada({"regiao": "brooklin"}, {"regiao": "itaim bibi"})]

    assert precisao_da_extracao(observadas).acertos == 0
    assert [d.tipo for d in discrepancias_da_extracao(observadas)] == ["divergiu"]


def test_normalizacao_de_regiao_nao_vaza_para_outros_campos_de_texto() -> None:
    """So `regiao` e normalizada. Se `_comparavel` aplicasse a regra a todo
    texto, um campo futuro herdaria uma normalizacao pensada para toponimo."""
    from mobia.evals.metricas import _comparavel

    assert _comparavel("regiao", "perto da usp") == "usp"
    assert _comparavel("tipo_imovel", "perto da usp") == "perto da usp"
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py -q -k "regiao or vaza"`

Expected: FAIL. Os três primeiros porque `_comparavel` só faz `strip`/`casefold`; o quarto com `TypeError: _comparavel() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Mude a assinatura e a implementação**

Em `src/mobia/evals/metricas.py`:

```python
def _comparavel(campo: str, valor: Any) -> Any:
    """Normaliza para comparar anotacao de YAML com valor vindo do parse.

    Recebe o nome do campo porque `regiao` tem contrato de forma proprio
    (TEC-241) e os outros textos nao: caixa e espaco nunca foram erro do
    modelo, mas preposicao e ruido de referencia so sao ruido em toponimo.
    Aplicar `normalizar_regiao` a todo texto faria um campo futuro herdar uma
    regra pensada para outra coisa.

    A regra de forma e importada de `schemas.py`, e nao reescrita aqui: e a
    MESMA que `extrair` aplica antes de gravar, e duas copias divergiriam sem
    nenhum teste acusar.

    Preco vem do YAML como `int` e do parse como `Decimal`, e 600000 e
    Decimal("600000.00") sao o mesmo preco.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return normalizar_regiao(valor) if campo == "regiao" else valor.strip().casefold()
    if isinstance(valor, int | float | Decimal):
        return Decimal(str(valor))
    return valor
```

Importe `normalizar_regiao` no topo, junto do import que já traz `Intencao` de `mobia.domain.agente.schemas`.

- [ ] **Step 4: Atualize os dois pontos de chamada**

Em `precisao_da_extracao` (~linha 403), a condição vira:

```python
            and _comparavel(nome, observada.esperado[nome])
            == _comparavel(nome, observada.obtido[nome])
```

Em `discrepancias_da_extracao` (~linha 442):

```python
                if _comparavel(campo, observada.esperado[campo]) == _comparavel(
                    campo, observada.obtido[campo]
                ):
```

Não há outros chamadores — confirme com `grep -rn "_comparavel" src/ tests/ evals/` antes de commitar, e reporte se houver.

- [ ] **Step 5: Rode a suíte inteira**

Run: `.venv/Scripts/python.exe -m pytest tests/unit -q`

Expected: PASS. A invariante `acertos + len(discrepancias) == total` continua valendo — as duas funções usam a mesma `_comparavel`, e o teste que a guarda já existe.

- [ ] **Step 6: Lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/metricas.py tests/unit/test_evals_metricas.py
git commit -m "feat(TEC-241): a medicao compara regiao na forma canonica"
```

---

### Task 4: A regra escrita — anotação, README e a emenda ao spec da TEC-145

**Files:**
- Modify: `src/mobia/evals/corpus.py` (docstring de `TurnoAnotado`)
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-28-tec-145-extracao-de-qualificacao-design.md`
- Test: `tests/unit/test_evals_corpus_real.py`

**Interfaces:**
- Consumes: `normalizar_regiao` da Task 1.
- Produces: nada de código novo.

- [ ] **Step 1: Escreva o teste que guarda o corpus commitado**

Em `tests/unit/test_evals_corpus_real.py`:

```python
def test_anotacoes_de_regiao_nao_colidem_depois_de_normalizadas(
    conversas: list[ConversaAnotada],
) -> None:
    """Normalizar nao pode fundir duas regioes distintas numa so.

    Se `perto da usp` e `usp` fossem duas anotacoes com sentidos diferentes,
    a normalizacao passaria a medir uma coisa por outra. Hoje nao ha colisao
    assim, e este teste guarda que continue nao havendo quando alguem
    acrescentar anotacao.
    """
    por_forma: dict[str, set[str]] = {}
    for conversa in conversas:
        for turno in conversa.turnos:
            if turno.campos and "regiao" in turno.campos:
                bruta = turno.campos["regiao"]
                por_forma.setdefault(normalizar_regiao(bruta), set()).add(bruta)

    colisoes = {forma: brutas for forma, brutas in por_forma.items() if len(brutas) > 1}

    assert colisoes == {}, f"formas distintas normalizam para a mesma: {colisoes}"
```

Importe `normalizar_regiao` de `mobia.domain.agente.schemas` no topo do arquivo.

- [ ] **Step 2: Rode**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k colidem`

Expected: PASS de primeira. **Isso é esperado e não é violação de TDD** — é um teste de guarda sobre dados commitados, escrito para pegar anotação futura, não para dirigir implementação. Se ele **falhar**, pare e reporte: significaria que duas anotações de sentido diferente viraram a mesma, e a normalização estaria medindo uma coisa por outra.

- [ ] **Step 3: Escreva a regra de anotação no docstring de `TurnoAnotado`**

Em `src/mobia/evals/corpus.py`, acrescente às regras que já estão lá:

```
    - **`regiao` se anota como toponimo, sem preposicao.** "usp", nao "perto da
      usp"; "vila madalena", nao "estacao vila madalena". Desde a TEC-241 a
      medicao normaliza os dois lados, entao anotacao suja ainda casa -- mas
      escrever ja canonico e o que faz o YAML dizer a mesma coisa que o banco
      guarda. As duas anotacoes antigas com preposicao (`aluguel-01`,
      `aluguel-07`) ficaram como estavam de proposito: reanota-las seria mexer
      na regua sem necessidade.
```

**Não toque nos cabeçalhos dos arquivos YAML** — o PR #14 está mexendo neles.

- [ ] **Step 4: README**

Na seção da TEC-145, subseção "Garantias" (perto de onde `regiao` já é mencionada), acrescente a decisão e o que ela custa. Cubra:

- `normalizar_regiao` é a única regra de forma, com dois consumidores — `extrair` e `_comparavel` —, e por que é uma só;
- o que ela tira (prefixos de referência, repetidamente) e o que ela **não** tira (`zona`);
- **normalizar perde informação:** "perto da usp" e "usp" viram a mesma coisa, e o lead que disse a primeira queria proximidade. A troca é a favor do filtro da TEC-158, e o texto original segue no histórico cifrado;
- **é mudança de comportamento de produção, sem migração retroativa:** os registros já gravados ficam na forma velha, e por um tempo `lead_qualification.regiao` terá as duas convivendo. A próxima fala do lead sobrescreve pelo mais novo (D4 da TEC-145);
- **o número não foi medido.** O critério "as divergências caem para perto de zero numa execução" exige execução paga, que esta card não fez. E não há baseline comparável — os 29 de 28/08 são de um corpus que mudou duas vezes desde então;
- **os sinônimos de `tipo_imovel` seguem sem dono.** Eram 8 discrepâncias na mesma execução. O card manda-os para a TEC-239, que é sobre cobertura de campos sem anotação e não sobre sinônimos — a referência está errada e a dívida não tem card.

- [ ] **Step 5: Emende o spec da TEC-145**

O card exige que o contrato escolhido fique escrito no spec da TEC-145, "como emenda, não só no código". Em `docs/superpowers/specs/2026-08-28-tec-145-extracao-de-qualificacao-design.md`, na decisão que estabelece `regiao` como texto livre, acrescente um bloco de emenda datado que diga: a decisão de conjunto aberto continua de pé (esta card dá **forma**, não vocabulário), o que faltou naquele desenho foi analisar a consequência para a **medição** — ele examinou o risco para o filtro SQL da TEC-158 e não o risco para a régua —, e que texto livre sem contrato de comparação não é mensurável. Não reescreva a decisão original: emende-a, para que a história continue legível.

- [ ] **Step 6: Rode tudo e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff check src tests alembic evals
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/corpus.py tests/unit/test_evals_corpus_real.py README.md docs/superpowers/specs/
git commit -m "docs(TEC-241): a regra de forma escrita, e a emenda ao spec da TEC-145"
```

---

## Encerramento

- [ ] **Suíte inteira, lint, tipos** uma última vez.

- [ ] **Confira os critérios de aceitação do card:**

| critério | estado esperado |
|---|---|
| Teste com os pares reais (`"perto da usp"`/`"usp"`, `"vila madalena"`/`"estacao vila madalena"`) | Task 3, Steps 1 |
| O spec da TEC-145 registra o contrato escolhido, com o motivo | Task 4, Step 5 |
| Se a opção escolhida não resolver a TEC-158, isso fica declarado | **Resolve** — o banco passa a guardar canônico. Declare que resolve, e que o custo é perda de informação |
| As divergências caem para perto de zero numa execução, e o número fica registrado | **NÃO entregue** — exige execução paga. Declarado no README |

- [ ] **Não rode `pytest evals`.**

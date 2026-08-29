# TEC-238 — Medir invenção em turno negativo: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o corpus poder dizer "o lead não afirmou nada neste turno", anotar 39 turnos assim, e com isso fechar o exploit em que um modelo que inventa `regiao`/`tipo_imovel` nos 100 turnos não anotados tira 100% VERDE.

**Architecture:** `campos: {}` passa a ser aceito por `carregar` e significa "nada afirmado". A fórmula de `precisao_da_extracao` **não muda** — o denominador de união já trata `esperado = {}` corretamente. O que muda é o contrato do corpus, um piso próprio para turnos negativos vigiado nos mesmos três pontos que o piso de anotados, e uma seção nova do relatório.

**Tech Stack:** Python 3.12+, pytest, PyYAML, dataclasses. Sem dependência nova.

**Spec:** [docs/superpowers/specs/2026-08-29-tec-238-invencao-em-turno-negativo-design.md](../specs/2026-08-29-tec-238-invencao-em-turno-negativo-design.md)

## Global Constraints

- **Comandos:** testes `python -m pytest` (use `.venv/Scripts/python.exe -m pytest` no Windows); lint `python -m ruff check src tests alembic`; formatação `python -m ruff format src tests alembic`; tipos `python -m mypy src`. Os três têm de passar antes de cada commit.
- **Nunca rode `pytest evals`.** É pago (uma chamada ao modelo por turno) e nada neste plano precisa dele. `testpaths = ["tests"]` no `pyproject.toml` já impede a coleta acidental.
- **Código e comentários em português sem acentos**, seguindo o resto de `src/mobia/evals/`. Docstrings explicam *por quê*, não *o quê* — é o padrão do repositório.
- **A regra de anotação não pode ser afrouxada:** anote só o que a fala afirma, e tudo o que ela afirma. Marcar como negativo um turno que afirma algo pune o modelo por acertar; deixar de marcar um turno que não afirma nada deixa invenção sem medição.
- **`campos: {}` nunca é lido por veracidade.** Use as propriedades `TurnoAnotado.anotado` / `.positivo` / `.negativo` criadas na Task 1. Um `if turno.campos` novo em qualquer lugar é bug.
- **Contagens são conferidas por execução, não por leitura.** Os números deste plano (39 negativos, piso 25) foram medidos; confirme-os rodando, e se divergirem, pare e reporte em vez de ajustar o número.

---

### Task 1: O contrato do corpus — `campos: {}` aceito, nulo recusado, propriedades

**Files:**
- Modify: `src/mobia/evals/corpus.py` (`TurnoAnotado`, `_turno_de`)
- Test: `tests/unit/test_evals_corpus.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces: `TurnoAnotado.anotado -> bool`, `TurnoAnotado.positivo -> bool`, `TurnoAnotado.negativo -> bool`. `carregar(Path) -> list[ConversaAnotada]` inalterada na assinatura, mudada no que aceita.

- [ ] **Step 1: Escreva os testes que falham**

Acrescente ao fim de `tests/unit/test_evals_corpus.py`. O helper `_corpus` já existe no arquivo — se o nome for outro, siga o padrão dos testes vizinhos que escrevem YAML em `tmp_path`.

```python
def test_campos_vazio_e_aceito_como_turno_negativo(tmp_path: Path) -> None:
    """`{}` e o unico jeito de dizer "o lead nao afirmou nada aqui".

    Sem ele, invencao so pode ser medida nos turnos que afirmam alguma coisa,
    e um modelo que inventa em todo turno nao anotado tira 100%.
    """
    (tmp_path / "c.yaml").write_text(
        "- id: compra-01\n"
        "  descricao: teste\n"
        "  turnos:\n"
        '    - lead: "quanto tempo leva pra aprovar o cadastro?"\n'
        "      intencao: COMPRA\n"
        "      campos: {}\n",
        encoding="utf-8",
    )

    turno = carregar(tmp_path)[0].turnos[0]

    assert turno.campos == {}
    assert turno.negativo


def test_campos_sem_valor_e_recusado_por_ser_ambiguo(tmp_path: Path) -> None:
    """`campos:` nulo e `campos: {}` sao dois caracteres de diferenca e
    significados opostos -- "fora da medicao" contra "tudo que vier e erro".
    A mensagem tem de dizer as duas saidas, senao quem errar o typo nao sabe
    qual das duas queria."""
    (tmp_path / "c.yaml").write_text(
        "- id: compra-01\n"
        "  descricao: teste\n"
        "  turnos:\n"
        '    - lead: "oi"\n'
        "      intencao: COMPRA\n"
        "      campos:\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusInvalido) as erro:
        carregar(tmp_path)

    assert "compra-01" in str(erro.value)
    assert "campos: {}" in str(erro.value)


def test_os_tres_estados_de_anotacao_tem_propriedade_propria() -> None:
    """Quatro lugares do codigo testavam `campos` por veracidade e um por
    `is not None`. Isso era inocuo so enquanto `{}` era impossivel."""
    fora = TurnoAnotado(lead="oi", intencao=Intencao.COMPRA, campos=None)
    negativo = TurnoAnotado(lead="oi", intencao=Intencao.COMPRA, campos={})
    positivo = TurnoAnotado(lead="oi", intencao=Intencao.COMPRA, campos={"quartos": 2})

    assert (fora.anotado, fora.positivo, fora.negativo) == (False, False, False)
    assert (negativo.anotado, negativo.positivo, negativo.negativo) == (True, False, True)
    assert (positivo.anotado, positivo.positivo, positivo.negativo) == (True, True, False)
```

Garanta os imports no topo do arquivo:

```python
from mobia.domain.agente.schemas import Intencao
from mobia.evals.corpus import CorpusInvalido, TurnoAnotado, carregar
```

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus.py -q -k "vazio or sem_valor or tres_estados"`

Expected: FAIL. O primeiro com `CorpusInvalido: ... tem 'campos' que nao e objeto ou esta vazio`; o segundo porque `campos:` nulo hoje é aceito em silêncio como "fora da medição"; o terceiro com `AttributeError: 'TurnoAnotado' object has no attribute 'anotado'`.

- [ ] **Step 3: Acrescente as propriedades a `TurnoAnotado`**

Em `src/mobia/evals/corpus.py`, dentro de `class TurnoAnotado`, depois dos três campos e antes do fim da classe:

```python
    @property
    def anotado(self) -> bool:
        """O turno entra na medicao de extracao."""
        return self.campos is not None

    @property
    def positivo(self) -> bool:
        """O turno afirma alguma coisa, e a anotacao diz o que."""
        return self.campos is not None and self.campos != {}

    @property
    def negativo(self) -> bool:
        """O turno esta anotado como "o lead nao afirmou nada".

        Tudo que o modelo devolver aqui e invencao, sem ambiguidade: o turno
        esta anotado por completo, e o completo e vazio. E o unico formato em
        que `extra` acusa o modelo em vez de acusar a medicao.
        """
        return self.campos == {}
```

- [ ] **Step 4: Troque a validação de `campos` em `_turno_de`**

Substitua o bloco que começa em `campos_brutos = bruto.get("campos")` e termina em `campos = campos_brutos` por:

```python
    # Distingue por PRESENCA da chave, e nunca por veracidade do valor:
    # `bruto.get("campos")` devolve None tanto para chave ausente quanto para
    # `campos:` sem valor, e desde a TEC-238 esses dois significam coisas
    # opostas.
    if "campos" not in bruto:
        campos = None
    else:
        campos_brutos = bruto["campos"]
        if campos_brutos is None:
            raise CorpusInvalido(
                f"{arquivo}: {conversa_id} tem `campos` sem valor, que nao diz nada. "
                f"Omita a chave para deixar o turno fora da medicao de extracao, "
                f"ou escreva `campos: {{}}` para dizer que o lead nao afirmou "
                f"nada neste turno."
            )
        if not isinstance(campos_brutos, dict):
            raise CorpusInvalido(
                f"{arquivo}: {conversa_id} tem `campos` que nao e um objeto."
            )
        # Anotacao e contrato: `campos` presente significa "este turno esta
        # anotado por completo". A metrica conta campo extraido que nao esta
        # aqui como erro, entao uma anotacao parcial nao vira nota mais baixa
        # do modelo -- vira medicao errada. `{}` e o caso limite disso: nada
        # esperado, tudo obtido e erro.
        for nome, valor in campos_brutos.items():
            if nome not in _CAMPOS_ANOTAVEIS:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota campo desconhecido {nome!r}. "
                    f"Conhecidos: {sorted(_CAMPOS_ANOTAVEIS)}."
                )
            enum = _VOCABULARIO.get(nome)
            if enum is not None and valor not in [membro.value for membro in enum]:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota {nome}={valor!r}, fora do "
                    f"vocabulario {[membro.value for membro in enum]}."
                )
        campos = campos_brutos
```

Atualize também o docstring de `TurnoAnotado` acrescentado pela TEC-239: onde ele diz que `campos` ausente é o jeito de dizer "esta fala não afirma nada extraível", passe a distinguir os dois — chave ausente é "fora da medição", `{}` é "nada afirmado, e isso está medido".

- [ ] **Step 5: Rode os testes da Task 1**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus.py -q`

Expected: PASS, todos.

- [ ] **Step 6: Escreva o teste que o card pede por nome**

Este é o critério de aceitação principal da TEC-238. Acrescente em `tests/unit/test_evals_metricas.py`, no fim:

```python
# --- TEC-238: invencao em turno negativo -----------------------------------


def test_modelo_que_inventa_em_turno_negativo_nao_tira_cem_por_cento() -> None:
    """O exploit que a card existe para fechar.

    Um modelo que acerta os turnos anotados e inventa `regiao`/`tipo_imovel`
    em todo turno nao anotado tirava 100%, VERDE. Com turnos negativos no
    corpus, a mesma invencao entra no denominador pelo lado obtido e nao tem
    como somar acerto.
    """
    observadas = [
        _observada({"quartos": 2}, {"quartos": 2}, indice=0),
        _observada({}, {"regiao": "sp", "tipo_imovel": "CASA"}, indice=1),
    ]

    metrica = precisao_da_extracao(observadas)

    assert (metrica.acertos, metrica.total) == (1, 3)
    assert metrica.faixa is Faixa.VERMELHO


def test_turno_negativo_sem_invencao_nao_altera_a_nota() -> None:
    """Nao inventar nao pode custar nem render ponto: o turno negativo limpo
    contribui zero para os dois lados da fracao. Sem isso, anotar mais
    negativos diluiria a nota de um modelo que se comporta."""
    so_positivo = [_observada({"quartos": 2}, {"quartos": 2}, indice=0)]
    com_negativo = [*so_positivo, _observada({}, {}, indice=1)]

    assert precisao_da_extracao(com_negativo).acertos == precisao_da_extracao(so_positivo).acertos
    assert precisao_da_extracao(com_negativo).total == precisao_da_extracao(so_positivo).total


def test_invencao_em_turno_negativo_e_extra_sem_ambiguidade() -> None:
    """O que torna o diagnostico suficiente sem uma metrica separada.

    Em turno positivo, `extra` pode ser invencao ou lacuna de anotacao. Em
    turno negativo nao pode ser lacuna: o turno esta anotado por completo.
    """
    achadas = discrepancias_da_extracao([_observada({}, {"regiao": "sp"}, indice=0)])

    assert [(d.campo, d.tipo) for d in achadas] == [("regiao", "extra")]


def test_corpus_so_negativo_e_limpo_levanta_em_vez_de_reportar() -> None:
    """A borda que o piso de negativos NAO protege.

    Turno negativo limpo contribui zero para os dois lados, entao um conjunto
    so de negativos sem invencao nenhuma tem total zero, e `faixa_de` recusa
    total zero para que um corpus que falhou ao carregar nao abra o gate com
    0/0. Quem impede esse conjunto de chegar aqui e `PISO_DE_TURNOS_ANOTADOS`,
    contado sobre positivos -- este teste fixa que a protecao mora la, e nao
    numa tolerancia escondida aqui dentro.
    """
    with pytest.raises(ValueError, match="nada medido"):
        precisao_da_extracao([_observada({}, {}, indice=0)])
```

O helper `_observada` já existe no arquivo (usado pelos testes da TEC-239). Confirme que ele aceita `esperado`, `obtido` e `indice`; se a assinatura for outra, use a mesma dos testes vizinhos.

- [ ] **Step 7: Rode e confirme que passam sem mudar a métrica**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py -q -k "negativo or inventa"`

Expected: PASS, **sem tocar em `precisao_da_extracao`**. Isso é esperado e é a descoberta que o spec registra: a fórmula de união já trata `esperado = {}`, e estes testes travam esse comportamento para que ninguém o quebre ao mexer na fórmula. Se algum falhar, **pare** — significa que a fórmula não é o que o spec mediu, e o desenho precisa voltar.

- [ ] **Step 8: Lint, tipos e commit**

```bash
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/corpus.py tests/unit/test_evals_corpus.py tests/unit/test_evals_metricas.py
git commit -m "feat(TEC-238): corpus pode dizer que o lead nao afirmou nada no turno"
```

---

### Task 2: Anotar os 39 turnos negativos

**Files:**
- Modify: `evals/corpus/aluguel.yaml`, `evals/corpus/compra.yaml`, `evals/corpus/investimento.yaml`, `evals/corpus/follow_up.yaml`, `evals/corpus/borda.yaml`
- Test: `tests/unit/test_evals_corpus_real.py`

**Interfaces:**
- Consumes: `TurnoAnotado.negativo` e `.positivo` da Task 1; `carregar` aceitando `campos: {}`.
- Produces: corpus com 38 positivos e 39 negativos, dos 138 turnos.

- [ ] **Step 1: Escreva o teste do corpus commitado**

Em `tests/unit/test_evals_corpus_real.py`:

```python
def test_o_corpus_tem_turnos_negativos_anotados(conversas: list[ConversaAnotada]) -> None:
    """Sem turno negativo, invencao so e medida onde o lead afirmou alguma
    coisa -- e um modelo que inventa em todo turno nao anotado tira 100%."""
    negativos = sum(1 for c in conversas for t in c.turnos if t.negativo)

    assert negativos >= 25  # PISO_DE_TURNOS_NEGATIVOS, nomeado na Task 3
```

A constante `PISO_DE_TURNOS_NEGATIVOS` nasce na Task 3, junto com a aritmética de abandono que justifica o número. Aqui o literal fica com o comentário que aponta para ela, e a Task 3, Step 6 troca um pelo outro. Isso mantém cada task fechada em si — esta commita verde sem depender da próxima.

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py -q -k negativ`

Expected: FAIL no primeiro, `assert 0 >= 25` — o corpus não tem turno negativo nenhum.

- [ ] **Step 3: Anote os 7 de `aluguel.yaml`**

Acrescente `campos: {}` a estes turnos, mantendo a indentação dos vizinhos. Nenhuma outra linha muda.

| conversa | turno | fala |
|---|---|---|
| `aluguel-04` | t0 | "voces pedem fiador ou aceita seguro fianca?" |
| `aluguel-04` | t1 | "e o valor do primeiro mes, e so o aluguel ou tem taxa de admin junto?" |
| `aluguel-04` | t2 | "quanto tempo leva pra aprovar o cadastro?" |
| `aluguel-07` | t1 | "da pra dividir com mais um amigo no contrato?" |
| `aluguel-07` | t2 | "e precisa comprovar renda dos dois ou so de um?" |
| `aluguel-09` | t1 | "voces exigem quantos meses de deposito caucao?" |
| `aluguel-09` | t2 | "e pode ter animal de estimacao no predio?" |

Exemplo da forma exata:

```yaml
    - lead: "quanto tempo leva pra aprovar o cadastro?"
      intencao: ALUGUEL
      campos: {}
```

Acrescente um comentário de cabeçalho em `aluguel.yaml`, acima da primeira conversa, explicando a convenção — este arquivo ainda não tem cabeçalho:

```yaml
# `campos: {}` significa "o lead nao afirmou nada extraivel neste turno", e
# tudo que o modelo devolver ali conta como invencao. Chave ausente e outra
# coisa: tira o turno da medicao. Ver o docstring de `TurnoAnotado`.
```

- [ ] **Step 4: Anote os 5 de `compra.yaml`**

| conversa | turno | fala |
|---|---|---|
| `compra-03` | t1 | "e qual documentacao voces pedem pra dar entrada no processo?" |
| `compra-03` | t2 | "faz quanto tempo em media do inicio ate a chave na mao?" |
| `compra-10` | t1 | "quanto tempo demora entre a proposta e a escritura normalmente?" |
| `compra-10` | t2 | "e precisa de advogado por nossa conta ou voces ja indicam um?" |
| `compra-12` | t2 | "consigo fechar tudo a distancia, sem vir pessoalmente antes?" |

**Não anote `compra-11` t2** ("o sobrado tem escritura ja regularizada?"). `sobrado` não está em `TipoImovel`, e um modelo que devolve `CASA` está lendo a fala com razão; marcá-lo negativo puniria isso com força de gate. Deixe um comentário no arquivo dizendo isso, acima do turno.

- [ ] **Step 5: Anote os 6 de `investimento.yaml`**

| conversa | turno | fala |
|---|---|---|
| `investimento-05` | t2 | "qual o yield medio desse tipo de imovel ja alugado?" |
| `investimento-08` | t1 | "voces administram a locacao tambem ou so a venda?" |
| `investimento-09` | t1 | "quanto tempo leva pra sair uma venda assim depois da reforma?" |
| `investimento-09` | t2 | "voces tem equipe de reforma parceira ou eu contrato por fora?" |
| `investimento-10` | t1 | "voces tem contato de construtora parceira pra esse tipo de projeto?" |
| `investimento-10` | t2 | "e a prefeitura demora muito pra aprovar esse tipo de obra por ali?" |

- [ ] **Step 6: Anote os 7 de `follow_up.yaml`**

| conversa | turno | fala |
|---|---|---|
| `follow-up-02` | t1 | "tem multa se eu quiser renovar por menos tempo?" |
| `follow-up-02` | t2 | "e o reajuste desse novo periodo e pelo mesmo indice de antes?" |
| `follow-up-03` | t1 | "quanto tempo leva pra avaliar o imovel?" |
| `follow-up-05` | t1 | "existe algum indice alternativo que voces aceitam usar?" |
| `follow-up-06` | t1 | "e a comissao de voces e quanto por cento?" |
| `follow-up-07` | t0 | "oi tudo bem? faz tempo que nao dou noticia, ainda ta ai?" |
| `follow-up-07` | t1 | "desculpa o sumico, correria aqui" |

**Não anote `follow-up-03` t2** ("documentacao pra baixa do financiamento"). O financiamento ali é o que o lead já tem, não a forma de pagamento que pretende usar, e a distinção é fina de mais para virar gate. Comentário no arquivo.

- [ ] **Step 7: Anote os 14 de `borda.yaml`**

| conversa | turno | intenção |
|---|---|---|
| `borda-injecao-01` | t0 | FORA_DE_ESCOPO |
| `borda-injecao-02` | t0, t1, t2 | FORA_DE_ESCOPO |
| `borda-fora-01` | t0, t1 | FORA_DE_ESCOPO |
| `borda-fora-02` | t0, t1 | FORA_DE_ESCOPO |
| `borda-mista-02` | t0 | FORA_DE_ESCOPO |
| `borda-evasivo-01` | t0, t1 | INDEFINIDA |
| `borda-evasivo-02` | t0 | INDEFINIDA |
| `borda-mista-01` | t0 | INDEFINIDA |
| `borda-generica-01` | t1 | SUPORTE_CONTRATO |

**Não anote `borda-evasivo-02` t1 e t2** ("depois eu vejo com calma", "ainda to decidindo o que quero"). A TEC-239 decidiu que isso não afirma `SEM_PRESSA`; anotá-los como negativos afirma o contrário, e com força de gate em vez de omissão. Comentário no arquivo explicando.

Acrescente também, acima dos nove `FORA_DE_ESCOPO`, um comentário registrando o que eles medem e o que não medem:

```yaml
# Os turnos FORA_DE_ESCOPO sao negativos por serem baratos de julgar, e nao
# por serem perigosos: `campos_a_gravar` devolve dict vazio para
# FORA_DE_ESCOPO, entao invencao aqui nunca chega a `lead_qualification`. O
# que eles medem e disciplina do modelo sob injecao. A invencao que persiste
# esta nos turnos cuja intencao grava.
```

- [ ] **Step 8: Confira as contagens por execução**

Run:

```bash
.venv/Scripts/python.exe -c "
from collections import Counter
from pathlib import Path
from mobia.evals.corpus import carregar, total_de_turnos
c = carregar(Path('evals/corpus'))
neg = [(x.id, t) for x in c for t in x.turnos if t.negativo]
print('turnos:', total_de_turnos(c))
print('positivos:', sum(1 for x in c for t in x.turnos if t.positivo))
print('negativos:', len(neg))
print('por intencao:', dict(Counter(t.intencao.value for _, t in neg)))
por_conversa = Counter(i for i, _ in neg)
print('pior abandono (5 maiores):', sum(sorted(por_conversa.values(), reverse=True)[:5]))
"
```

Expected, exatamente:

```
turnos: 138
positivos: 38
negativos: 39
por intencao: ALUGUEL 7, COMPRA 5, INVESTIMENTO 6, SUPORTE_CONTRATO 4, VENDER_IMOVEL 2, INDEFINIDA 6, FORA_DE_ESCOPO 9
pior abandono (5 maiores): 12
```

Se algum número divergir, **pare e reporte** — não ajuste o número do plano para casar com o corpus.

- [ ] **Step 9: Rode os testes e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_evals_corpus_real.py tests/unit/test_evals_corpus.py -q
.venv/Scripts/python.exe -m ruff check src tests alembic
git add evals/corpus tests/unit/test_evals_corpus_real.py
git commit -m "feat(TEC-238): 39 turnos negativos, priorizando as intencoes que gravam"
```

---

### Task 3: O piso de negativos, e os três pontos alinhados

**Files:**
- Modify: `src/mobia/evals/metricas.py` (constante nova)
- Modify: `evals/conftest.py:50` (pré-voo)
- Modify: `tests/unit/test_evals_corpus_real.py:92` (CI)
- Modify: `evals/test_acuracia_de_intencao.py` (`_metricas_de`, amostra sobrevivente)
- Test: `tests/unit/test_evals_corpus_real.py`, `tests/unit/test_evals_metricas.py`

**Interfaces:**
- Consumes: `TurnoAnotado.positivo` / `.negativo` (Task 1); 39 negativos no corpus (Task 2).
- Produces: `PISO_DE_TURNOS_NEGATIVOS: int = 25` em `src/mobia/evals/metricas.py`.

- [ ] **Step 1: Escreva o teste do piso e da aritmética de abandono**

Em `tests/unit/test_evals_metricas.py`:

```python
def test_o_piso_de_negativos_sobrevive_ao_teto_de_abandono() -> None:
    """O piso nao e numero de gosto: e o que sobra depois do pior abandono.

    Mesma conta de `test_o_teto_de_abandono_nunca_consegue_furar_o_piso_de_turnos`,
    na dimensao dos negativos. Se o corpus mudar de forma, este teste falha
    de graca, antes de qualquer chamada paga.
    """
    conversas = carregar(CORPUS)
    por_conversa = sorted(
        (sum(1 for t in c.turnos if t.negativo) for c in conversas), reverse=True
    )
    negativos = sum(por_conversa)
    pior_perda = sum(por_conversa[:TETO_DE_CONVERSAS_ABANDONADAS])

    assert negativos - pior_perda >= PISO_DE_TURNOS_NEGATIVOS, (
        f"as {TETO_DE_CONVERSAS_ABANDONADAS} conversas com mais negativos somam "
        f"{pior_perda}, e o corpus tem {negativos} sobre um piso de "
        f"{PISO_DE_TURNOS_NEGATIVOS}"
    )
```

Importe `PISO_DE_TURNOS_NEGATIVOS` de `mobia.evals.metricas` no topo.

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py -q -k piso_de_negativos`

Expected: FAIL no import — `ImportError: cannot import name 'PISO_DE_TURNOS_NEGATIVOS'`.

- [ ] **Step 3: Crie a constante**

Em `src/mobia/evals/metricas.py`, logo abaixo de `PISO_DE_TURNOS_ANOTADOS`:

```python
# Piso dos turnos anotados como "o lead nao afirmou nada" (`campos: {}`).
# Irmao de `PISO_DE_TURNOS_ANOTADOS` na terceira direcao: aquele responde
# "sobrou amostra para medir acerto?", este responde "sobrou amostra para
# pegar invencao?".
#
# Os dois sao separados de proposito. Um piso unico sobre "todo turno
# anotado" se auto-satisfaria: 30 turnos negativos sem invencao nenhuma
# dariam denominador zero, e `faixa_de` levanta `ValueError` em vez de
# reportar -- o mesmo furo que o piso existe para fechar, entrando por outra
# porta.
#
# O numero vem do pior caso de abandono, como o de `TETO_DE_CONVERSAS_ABANDONADAS`:
# sao 39 negativos, e as cinco conversas com mais negativos somam 12, entao a
# execucao mais azarada ainda entrega 27. O piso fica em 25, com folga de dois.
PISO_DE_TURNOS_NEGATIVOS = 25
```

- [ ] **Step 4: Rode e confirme que passa**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py -q -k piso_de_negativos`

Expected: PASS.

- [ ] **Step 5: Alinhe o pré-voo**

Em `evals/conftest.py`, troque a linha 50 e acrescente a segunda guarda. O bloco fica:

```python
    anotados = sum(1 for conversa in carregadas for turno in conversa.turnos if turno.positivo)
    if anotados < PISO_DE_TURNOS_ANOTADOS:
        pytest.fail(
            f"corpus com {anotados} turnos anotados, piso {PISO_DE_TURNOS_ANOTADOS}: "
            f"abortado antes da primeira chamada paga, porque a precisao da extracao "
            f"nao teria amostra."
        )
    negativos = sum(1 for conversa in carregadas for turno in conversa.turnos if turno.negativo)
    if negativos < PISO_DE_TURNOS_NEGATIVOS:
        pytest.fail(
            f"corpus com {negativos} turnos negativos, piso {PISO_DE_TURNOS_NEGATIVOS}: "
            f"abortado antes da primeira chamada paga, porque invencao nao teria "
            f"amostra e a metrica voltaria a medir so um dos dois lados."
        )
```

Importe `PISO_DE_TURNOS_NEGATIVOS` no topo do arquivo. Atualize o docstring da fixture `conversas`: onde ele diz "confere os dois pisos", passe a dizer três, e explique que `positivo` substituiu a veracidade de `campos` porque `{}` agora é um estado, não a ausência de um.

- [ ] **Step 6: Alinhe o teste do CI**

Em `tests/unit/test_evals_corpus_real.py`, troque `if t.campos is not None` por `if t.positivo` em `test_corpus_tem_turnos_anotados_suficientes`, e troque o literal `25` do teste da Task 2 por `PISO_DE_TURNOS_NEGATIVOS`. Importe a constante.

Confira também `test_todo_campo_de_extracao_tem_anotacao` (TEC-239): ele usa `if turno.campos` por veracidade, o que continua correto para o que ele mede (um `{}` não contribui nome de campo nenhum), mas troque para `if turno.positivo` para que não sobre nenhum teste de veracidade no arquivo.

- [ ] **Step 7: Alinhe a amostra sobrevivente**

Em `evals/test_acuracia_de_intencao.py`, dentro de `_metricas_de`, a guarda hoje é `len(observadas) >= PISO_DE_TURNOS_ANOTADOS`. Com negativos dentro de `observadas`, ela se auto-satisfaz. Troque por:

```python
    positivas = sum(1 for o in observadas if o.esperado != {})
    negativas = len(observadas) - positivas
    extracao = (
        [precisao_da_extracao(observadas)]
        if positivas >= PISO_DE_TURNOS_ANOTADOS and negativas >= PISO_DE_TURNOS_NEGATIVOS
        else [
            sem_mecanismo(
                "precisao da extracao",
                f"{positivas} turnos anotados (piso {PISO_DE_TURNOS_ANOTADOS}) e "
                f"{negativas} negativos (piso {PISO_DE_TURNOS_NEGATIVOS}) sobraram "
                f"na execucao: amostra pequena de mais para o piso de 85% "
                f"significar algo",
            )
        ]
    )
```

Importe `PISO_DE_TURNOS_NEGATIVOS`. Acrescente ao docstring de `_metricas_de` o porquê: `precisao_da_extracao(observadas)` continua recebendo **todas** as observadas, positivas e negativas; são as *guardas* que contam os dois grupos em separado, porque um deles sozinho não sustenta o número.

- [ ] **Step 8: Rode tudo e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals/metricas.py evals/conftest.py evals/test_acuracia_de_intencao.py tests/unit
git commit -m "feat(TEC-238): piso proprio de negativos, vigiado nos mesmos tres pontos"
```

---

### Task 4: O relatório afirma invenção em vez de sugerir

**Files:**
- Modify: `src/mobia/evals/metricas.py` (`ResumoDeNegativos`, `resumo_de_negativos`)
- Modify: `src/mobia/evals/relatorio.py` (`_secao_de_extracao`, `render`)
- Modify: `evals/test_acuracia_de_intencao.py` (passar o resumo ao `render`)
- Test: `tests/unit/test_evals_metricas.py`, `tests/unit/test_evals_relatorio.py`

**Interfaces:**
- Consumes: `ExtracaoObservada` (já existe).
- Produces: `ResumoDeNegativos(turnos: int, com_invencao: int, campos_inventados: int)` e `resumo_de_negativos(observadas: Sequence[ExtracaoObservada]) -> ResumoDeNegativos`; `render(..., negativos: ResumoDeNegativos | None = None)`.

- [ ] **Step 1: Escreva os testes que falham**

Em `tests/unit/test_evals_metricas.py`:

```python
def test_resumo_de_negativos_conta_turnos_e_invencoes() -> None:
    """Turno negativo sem invencao nao aparece em `discrepancias_da_extracao`,
    entao o relatorio nao teria como dizer quantos foram medidos. Sem esse
    numero, "3 invencoes" nao se distingue de "3 invencoes em 3 turnos"."""
    observadas = [
        _observada({"quartos": 2}, {"quartos": 2}, indice=0),
        _observada({}, {}, indice=1),
        _observada({}, {"regiao": "sp", "tipo_imovel": "CASA"}, indice=2),
    ]

    resumo = resumo_de_negativos(observadas)

    assert resumo == ResumoDeNegativos(turnos=2, com_invencao=1, campos_inventados=2)
```

Em `tests/unit/test_evals_relatorio.py`:

```python
def test_a_secao_de_extracao_nomeia_os_turnos_negativos() -> None:
    """Sem isto, um `extra` no relatorio nao diz se foi invencao ou lacuna de
    anotacao -- e a distincao e o motivo de a TEC-238 existir."""
    saida = render(
        [],
        {},
        discrepancias=[_discrepancia("borda-fora-01", 0, "regiao", "extra")],
        negativos=ResumoDeNegativos(turnos=39, com_invencao=1, campos_inventados=1),
    )

    assert "39 turnos negativos" in saida
    assert "1 com invencao" in saida
```

O helper `_discrepancia` já existe em `tests/unit/test_evals_relatorio.py`.

- [ ] **Step 2: Rode para ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py tests/unit/test_evals_relatorio.py -q -k negativ`

Expected: FAIL no import de `ResumoDeNegativos` / `resumo_de_negativos`.

- [ ] **Step 3: Crie o resumo em `metricas.py`**

Ao lado de `ExtracaoObservada` e `Discrepancia`:

```python
@dataclass(frozen=True)
class ResumoDeNegativos:
    """Quantos turnos negativos entraram na medicao, e quanto se inventou neles.

    Nao carrega faixa: e diagnostico, como `ResumoDeConfianca`. Quem bloqueia
    e `precisao_da_extracao`, que ja conta a invencao no denominador.

    `turnos` precisa existir separado de `com_invencao` porque turno negativo
    limpo nao gera discrepancia nenhuma: sem este numero, o relatorio nao teria
    como dizer se "uma invencao" saiu de dois turnos medidos ou de trinta e nove.
    """

    turnos: int
    com_invencao: int
    campos_inventados: int


def resumo_de_negativos(observadas: Sequence[ExtracaoObservada]) -> ResumoDeNegativos:
    """Turno negativo e o que tem `esperado` vazio -- anotado por completo, e o
    completo e nada."""
    negativas = [observada for observada in observadas if observada.esperado == {}]
    return ResumoDeNegativos(
        turnos=len(negativas),
        com_invencao=sum(1 for observada in negativas if observada.obtido),
        campos_inventados=sum(len(observada.obtido) for observada in negativas),
    )
```

- [ ] **Step 4: Ligue no relatório**

Em `src/mobia/evals/relatorio.py`, mude a assinatura de `_secao_de_extracao` para `(discrepancias: Sequence[Discrepancia], negativos: ResumoDeNegativos | None)` e acrescente as linhas logo depois de `- total de discrepancias:`:

```python
    if negativos is not None:
        linhas += [
            f"- {negativos.turnos} turnos negativos medidos, "
            f"{negativos.com_invencao} com invencao "
            f"({negativos.campos_inventados} campos)",
            "",
            "  Num turno negativo, `extra` e invencao sem ambiguidade: o turno",
            "  esta anotado por completo, e o completo e vazio.",
        ]
```

Em `render`, acrescente o parâmetro `negativos: ResumoDeNegativos | None = None` ao bloco keyword-only e repasse-o. Ajuste a condição para que a seção saia quando houver discrepâncias **ou** resumo de negativos — um corpus em que ninguém inventou nada é exatamente o resultado que vale imprimir.

Em `evals/test_acuracia_de_intencao.py`, passe `negativos=resumo_de_negativos(observadas)` na chamada a `render` que hoje passa `discrepancias=discrepancias_da_extracao(observadas)` (por volta da linha 321).

- [ ] **Step 5: Rode e commite**

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q
.venv/Scripts/python.exe -m ruff format src tests alembic
.venv/Scripts/python.exe -m ruff check src tests alembic
.venv/Scripts/python.exe -m mypy src
git add src/mobia/evals tests/unit evals/test_acuracia_de_intencao.py
git commit -m "feat(TEC-238): relatorio afirma invencao em turno negativo"
```

---

### Task 5: README

**Files:**
- Modify: `README.md` (seção TEC-145, subseções "A medição" e "Lacunas conhecidas")

**Interfaces:**
- Consumes: os números finais das Tasks 2 e 3.
- Produces: nada de código.

- [ ] **Step 1: Reescreva o bullet do exploit**

Em "Lacunas conhecidas", o bullet que começa com **"A precisão de extração pune os dois lados só nos 38 turnos anotados; nos outros 100, invenção não é medida por ninguém."** descreve um furo que esta card fecha. Substitua por um bullet que diga:

- a métrica agora mede **77 dos 138** turnos — 38 positivos e 39 negativos;
- `campos: {}` é o estado novo, e chave ausente continua significando "fora da medição";
- o exploit descrito antes (inventar em todo turno não anotado e tirar 100% VERDE) **não funciona mais**, e há teste com esse nome;
- **61 turnos continuam fora da medição** — este é o buraco que sobra, e ele tem de ficar escrito com o mesmo desconforto do anterior, incluindo as três exclusões deliberadas (`compra-11` t2, `follow-up-03` t2, `borda-evasivo-02` t1/t2) e o porquê de cada uma;
- invenção nos 9 turnos `FORA_DE_ESCOPO` é medida mas **nunca chega a `lead_qualification`**, porque `campos_a_gravar` devolve dict vazio para essa intenção — o número deles não deve ser lido como risco de dado permanente.

- [ ] **Step 2: Atualize a subseção "A medição"**

O parágrafo de `PISO_DE_TURNOS_ANOTADOS` diz "Hoje **38 turnos estão anotados**, distribuídos em..." e enumera cinco arquivos. Acrescente ao lado a contagem de negativos por arquivo e a existência de `PISO_DE_TURNOS_NEGATIVOS`, com a aritmética do pior caso de abandono (39 negativos, cinco piores somam 12, sobram 27, piso 25). Conte por execução:

```bash
.venv/Scripts/python.exe -c "
from pathlib import Path
from mobia.evals.corpus import carregar
for f in sorted(Path('evals/corpus').glob('*.yaml')):
    d = Path('_um'); d.mkdir(exist_ok=True); a = d / f.name
    a.write_text(f.read_text(encoding='utf-8'), encoding='utf-8')
    convs = carregar(d)
    print(f.name, 'positivos:', sum(1 for c in convs for t in c.turnos if t.positivo),
          'negativos:', sum(1 for c in convs for t in c.turnos if t.negativo))
    a.unlink(); d.rmdir()
"
```

- [ ] **Step 3: Documente o contrato de três estados**

Ainda em "A medição", acrescente a tabela dos três estados (chave ausente / `campos: {}` / `campos: {…}`) e diga que `campos:` com valor nulo é **recusado** por ser ambíguo. Explique por que as propriedades `anotado`/`positivo`/`negativo` existem: quatro lugares testavam `campos` por veracidade e um por `is not None`, e isso era inócuo só enquanto `{}` era impossível.

- [ ] **Step 4: Commite**

```bash
git add README.md
git commit -m "docs(TEC-238): o exploit fechado, e os 61 turnos que ficam fora"
```

---

## Encerramento

- [ ] **Rode a suíte inteira uma última vez**

Run: `.venv/Scripts/python.exe -m pytest tests/unit -q` (leva ~3 min), mais `ruff check`, `ruff format --check` e `mypy src`.

- [ ] **Confira os critérios de aceitação do card, um a um**

| critério | como provar |
|---|---|
| Teste provando que um modelo que inventa em turnos negativos não tira 100% | `test_modelo_que_inventa_em_turno_negativo_nao_tira_cem_por_cento` |
| Corpus tem turnos negativos anotados, e `test_evals_corpus_real.py` guarda um piso deles | `test_o_corpus_tem_turnos_negativos_anotados` contra `PISO_DE_TURNOS_NEGATIVOS` |
| README descreve a cobertura real, sem virar promessa maior do que é | Task 5, Step 1 — os 61 turnos declarados |

- [ ] **Não rode `pytest evals`.** É pago. `precisao_da_extracao` segue sem nunca ter sido executada, e isso continua verdadeiro no README.

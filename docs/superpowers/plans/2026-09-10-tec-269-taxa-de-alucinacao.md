# TEC-269 — Taxa de alucinação no gate: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A taxa de alucinação deixa de sair como `SEM_MECANISMO` no relatório do gate e passa a ser um número medido, reusando a guarda que a TEC-161 entregou.

**Architecture:** A lógica mora em `src/mobia/evals/metricas.py`, onde `tests/unit/test_evals_metricas.py` a alcança sem gastar chamada paga; `evals/test_acuracia_de_intencao.py` fica só com a fiação. A detecção não é reimplementada: importa `divergencias_de` de `domain/agente/citacao.py`, a mesma função que `executar_turno` roda em produção.

**Tech Stack:** Python 3.13, dataclasses `frozen=True`, pytest. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-10-tec-269-taxa-de-alucinacao-design.md` — decisões D1 a D8, lacunas 1 a 4. Leia os dois.

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `evals/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates estáticos, nesta ordem, com este escopo exato**, antes de qualquer commit:
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter. O código deste plano foi escrito à mão e **não** passou pelo formatador: se `--check` reprovar, rode `ruff format src tests alembic evals` e commite o resultado.
- **`evals/` está no escopo do ruff mas NÃO do mypy.** O mypy cobre só `src`.
- **Mensagem de commit:** `tipo(TEC-269): o que passou a ser verdade`, português sem acento no assunto.
- **Nenhuma task de 1 a 3 gasta crédito da Anthropic.** `pytest` puro nunca coleta `evals/` — `testpaths = ["tests"]` no `pyproject.toml` garante isso. Só a Task 4 chama o provedor, e ela exige autorização explícita.
- **Não rode `pytest evals`** em nenhuma task de 1 a 3. Isso dispara as 146 chamadas pagas.
- **A suíte é lenta** (~13 min, 1408 testes em 10/09/2026). Rode arquivo isolado durante o trabalho; a suíte inteira só na Task 3.
- **O nome da métrica é `taxa de alucinacao (cifra e codigo)`**, com o parêntese. Ver D4: sem ele, um VERDE ali afirma cobertura que a guarda não tem.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `src/mobia/evals/metricas.py` | **Modificar.** Ganha `InvencaoObservada`, `invencao_do_turno` e `taxa_de_alucinacao`. É onde a lógica fica testável de graça. | 1 |
| `tests/unit/test_evals_metricas.py` | **Modificar.** Os testes da métrica. Arquivo já existe; **não crie um novo** — basename repetido entre `tests/unit/` e `tests/integration/` aborta a coleta da suíte inteira e não aparece rodando o arquivo isolado. | 1 |
| `evals/test_acuracia_de_intencao.py` | **Modificar.** Só fiação: coleta no laço, propaga na tupla, troca o `sem_mecanismo`. | 2 |

---

### Task 1: A métrica, onde ela é testável de graça

**Files:**
- Modify: `src/mobia/evals/metricas.py`
- Test: `tests/unit/test_evals_metricas.py`

**Interfaces:**
- Consumes: `divergencias_de(prosa, *, candidatos, faixa) -> tuple[Divergencia, ...]` e `Divergencia(tipo, citado)` de `mobia.domain.agente.citacao` (entregues pela TEC-161, em `main`). Tupla vazia = prosa ancorada.
- Produces:
  - `InvencaoObservada(conversa_id: str, indice: int, divergencias: tuple[Divergencia, ...])`
  - `invencao_do_turno(texto, *, conversa_id, indice, candidatos, faixa) -> InvencaoObservada | None`
  - `taxa_de_alucinacao(invencoes, respostas) -> ResultadoDaMetrica`
  - `NOME_DA_TAXA_DE_ALUCINACAO`, `ALVO_DE_ANCORAGEM_PCT = 98`, `PISO_ANDAIME_DE_ANCORAGEM_PCT = 50`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/unit/test_evals_metricas.py`:

```python
def _sem_faixa() -> tuple[int | None, int | None]:
    return (None, None)


def _invencao(indice: int, citado: str = "R$ 900.000") -> InvencaoObservada:
    return InvencaoObservada(
        conversa_id="c1",
        indice=indice,
        divergencias=(Divergencia(tipo="preco", citado=citado),),
    )


def test_prosa_ancorada_nao_vira_invencao() -> None:
    """Sem cifra e sem codigo nao ha o que ancorar."""
    assert (
        invencao_do_turno(
            "Achei tres opcoes que encaixam no que voce falou.",
            conversa_id="c1",
            indice=0,
            candidatos=[],
            faixa=_sem_faixa(),
        )
        is None
    )


def test_cifra_sem_base_vira_invencao() -> None:
    """D1: sem busca no corpus, citar preco de imovel e invencao por construcao."""
    observada = invencao_do_turno(
        "Tenho um otimo por R$ 900 mil.",
        conversa_id="c1",
        indice=2,
        candidatos=[],
        faixa=_sem_faixa(),
    )
    assert observada is not None
    assert observada.indice == 2
    assert observada.divergencias == (Divergencia(tipo="preco", citado="R$ 900.000"),)


def test_eco_do_orcamento_do_lead_nao_e_invencao() -> None:
    """D3. Sem esta valvula a metrica contaria como alucinacao o modelo
    repetindo o numero que o proprio lead deu -- e o prompt PEDE que ele
    repita, porque `montar_contexto` poe a faixa no bloco de estado."""
    assert (
        invencao_do_turno(
            "Entendi, vou procurar ate R$ 600 mil.",
            conversa_id="c1",
            indice=1,
            candidatos=[],
            faixa=(None, 60_000_000),
        )
        is None
    )


def test_taxa_conta_por_turno_e_nao_por_divergencia() -> None:
    """Um turno que inventa dois precos e um turno ruim, nao dois.

    Mesma regra de `aderencia_ao_tom`: o lead vive o turno.
    """
    duas_no_mesmo_turno = InvencaoObservada(
        conversa_id="c1",
        indice=0,
        divergencias=(
            Divergencia(tipo="preco", citado="R$ 900.000"),
            Divergencia(tipo="codigo", citado="AP-9999"),
        ),
    )
    respostas = [_resposta("qualquer coisa", indice=i) for i in range(4)]
    metrica = taxa_de_alucinacao([duas_no_mesmo_turno], respostas)
    assert metrica.acertos == 3
    assert metrica.total == 4


def test_o_detalhe_reporta_a_taxa_e_nao_o_complemento() -> None:
    """D5. Por dentro conta turnos limpos, porque `faixa_de` e
    quanto-maior-melhor. Por fora reporta a taxa, que e o que a RNF-26 pede.
    Sem isto a linha exibiria "98,6%" ao lado da palavra "alucinacao".
    """
    respostas = [_resposta("qualquer coisa", indice=i) for i in range(4)]
    metrica = taxa_de_alucinacao([_invencao(0)], respostas)
    assert metrica.nome == "taxa de alucinacao (cifra e codigo)"
    assert "1/4 turnos com cifra sem base" in metrica.detalhe
    assert "25.0%" in metrica.detalhe


def test_sem_amostra_volta_para_sem_mecanismo() -> None:
    """D7. Nunca verde: slot que reporta verde sem medir finge cobertura."""
    metrica = taxa_de_alucinacao([], [])
    assert metrica.faixa is Faixa.SEM_MECANISMO
    assert metrica.acertos is None


def test_a_borda_do_alvo_e_exatamente_a_da_rnf_26() -> None:
    """1 turno sujo em 50 sao 2% -- o alvo da RNF-26 -- e tem de sair VERDE.

    `faixa_de` compara `acertos * 100 >= total * alvo` em inteiro: 49*100 e
    50*98 dao 4900 dos dois lados. A borda e inclusiva, e este teste existe
    para que trocar `>=` por `>` em `faixa_de` apareca aqui e nao numa
    execucao paga.
    """
    respostas = [_resposta("qualquer coisa", indice=i) for i in range(50)]
    assert taxa_de_alucinacao([_invencao(0)], respostas).faixa is Faixa.VERDE
    assert taxa_de_alucinacao([_invencao(0), _invencao(1)], respostas).faixa is Faixa.AMARELO


def test_o_andaime_nao_reprova_execucao_ruim() -> None:
    """D6. O piso da primeira entrega e andaime, nao medida: gatear em 2% na
    primeira execucao seria gatear em ruido. Este teste existe para alguem
    que substituir o andaime por piso medido ver que o comportamento mudou.
    """
    respostas = [_resposta("qualquer coisa", indice=i) for i in range(10)]
    tres_sujos = [_invencao(i) for i in range(3)]
    assert taxa_de_alucinacao(tres_sujos, respostas).faixa is not Faixa.VERMELHO
```

Acrescente `Divergencia` ao import de `mobia.domain.agente.citacao` e `InvencaoObservada`, `invencao_do_turno`, `taxa_de_alucinacao` ao import de `mobia.evals.metricas`, no topo do arquivo. `_resposta` e `Faixa` já existem ali — reuse, não redefina.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py -k "invencao or taxa or andaime or ancorada" -v`
Expected: FAIL com `ImportError: cannot import name 'InvencaoObservada'`

- [ ] **Step 3: Implementar**

Acrescente em `src/mobia/evals/metricas.py`, depois de `aderencia_ao_tom`:

```python
# O nome carrega o escopo de proposito (D4 do desenho). A guarda da TEC-161
# cobre cifra e codigo; NAO cobre parafrase -- "tenho um bem espacoso na
# praia" sobre imovel inexistente passa, e a lacuna 1 daquela card declara
# isso. Sem o parenteses, um VERDE nesta linha diria a quem audita o RT-01
# que toda alucinacao esta coberta.
#
# `turnos sem invencao` foi recusado: colide com `com_invencao` neste mesmo
# modulo, que conta campo de extracao inventado em turno negativo.
NOME_DA_TAXA_DE_ALUCINACAO = "taxa de alucinacao (cifra e codigo)"

# A RNF-26 pede taxa abaixo de 2%, logo 98% de turnos ancorados. A metrica
# conta o complemento por dentro porque `faixa_de` e quanto-maior-melhor.
ALVO_DE_ANCORAGEM_PCT = 98

# ANDAIME, nao medida -- D6 do desenho. Substituir por piso medido quando
# houver execucoes, que foi o que a TEC-255 fez com a aderencia ao tom
# (trocou o andaime de 50 por 90 depois de medir). Gatear em 2% na primeira
# execucao seria gatear em ruido: duas execucoes do MESMO codigo ja diferiram
# 5,7 pontos noutra metrica deste relatorio.
#
# **Este numero e propriedade do par modelo-detector, nao do modelo** (D2).
# Alargar a gramatica de `divergencias_de` faz a taxa subir sem o modelo ter
# piorado. Quem alargar re-mede o piso na mesma card, e a pergunta e "subiu
# porque o modelo piorou ou porque o detector melhorou?" antes de "quanto
# subo o piso?".
PISO_ANDAIME_DE_ANCORAGEM_PCT = 50


@dataclass(frozen=True)
class InvencaoObservada:
    """Um turno cuja prosa citou cifra ou codigo sem base, com o endereco.

    Carrega as divergencias e nao so a contagem, pela licao que
    `ViolacaoDeFormato` ja registra neste arquivo: endereco sozinho nao
    diagnostica, e descobrir o porque exigiria outra execucao paga.
    """

    conversa_id: str
    indice: int
    divergencias: tuple[Divergencia, ...]


def invencao_do_turno(
    texto: str,
    *,
    conversa_id: str,
    indice: int,
    candidatos: Sequence[Mapping[str, Any]],
    faixa: tuple[int | None, int | None],
) -> InvencaoObservada | None:
    """A invencao deste turno, ou `None` quando a prosa esta ancorada.

    Chama `divergencias_de` -- a MESMA funcao que `executar_turno` roda em
    producao -- e nao uma copia. Uma segunda definicao de "alucinacao" neste
    repo seriam duas medindo coisas diferentes com o mesmo nome, e a TEC-161
    recusou a gramatica gemea tres vezes dentro da propria branch.

    `candidatos` chega vazio em todo turno do corpus, porque o eval nao passa
    `porta` e portanto nao ha tool use (D1). Com lista vazia so a faixa do
    lead absolve, que e exatamente o caso RT-01 puro: o agente citou preco
    sem ter buscado nada.
    """
    divergencias = divergencias_de(texto, candidatos=candidatos, faixa=faixa)
    if not divergencias:
        return None
    return InvencaoObservada(conversa_id=conversa_id, indice=indice, divergencias=divergencias)


def taxa_de_alucinacao(
    invencoes: Sequence[InvencaoObservada],
    respostas: Sequence[RespostaObservada],
) -> ResultadoDaMetrica:
    """Fracao dos turnos cuja prosa nao inventou cifra nem codigo.

    Por turno e nao por divergencia, pela mesma razao de `aderencia_ao_tom`:
    o lead vive o turno, e um turno que inventa dois precos e um turno ruim,
    nao dois.

    `acertos` conta turnos LIMPOS porque `faixa_de` e quanto-maior-melhor; o
    `detalhe` -- a unica coisa que o relatorio renderiza -- reporta a taxa na
    direcao que a RNF-26 pede. A inversao e deliberada (D5).
    """
    total = len(respostas)
    if total == 0:
        return sem_mecanismo(
            NOME_DA_TAXA_DE_ALUCINACAO,
            "nenhuma resposta sobreviveu a execucao",
        )
    sujos = len({(i.conversa_id, i.indice) for i in invencoes})
    acertos = total - sujos
    pct = sujos * 100 / total
    return ResultadoDaMetrica(
        nome=NOME_DA_TAXA_DE_ALUCINACAO,
        faixa=faixa_de(
            acertos,
            total,
            alvo=ALVO_DE_ANCORAGEM_PCT,
            piso=PISO_ANDAIME_DE_ANCORAGEM_PCT,
        ),
        acertos=acertos,
        total=total,
        detalhe=(
            f"{sujos}/{total} turnos com cifra sem base ({pct:.1f}%), "
            f"alvo <{100 - ALVO_DE_ANCORAGEM_PCT}%, "
            f"piso <{100 - PISO_ANDAIME_DE_ANCORAGEM_PCT}% (andaime)"
        ),
    )
```

E no topo de `src/mobia/evals/metricas.py`, junto dos outros imports:

```python
from mobia.domain.agente.citacao import Divergencia, divergencias_de
```

`Sequence` e `Mapping` vêm de `collections.abc`, `Any` de `typing` — confira se já estão importados antes de acrescentar.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_evals_metricas.py -v --tb=short`
Expected: PASS, incluindo todos os testes que já existiam no arquivo.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
git add src/mobia/evals/metricas.py tests/unit/test_evals_metricas.py
git commit -m "feat(TEC-269): a metrica de alucinacao existe e e testavel sem gastar chamada"
```

---

### Task 2: A fiação no gate

**Files:**
- Modify: `evals/test_acuracia_de_intencao.py`

**Interfaces:**
- Consumes: `InvencaoObservada`, `invencao_do_turno`, `taxa_de_alucinacao` (Task 1).
- Produces: nenhum símbolo novo. O efeito observável é a linha do relatório deixar de dizer `SEM_MECANISMO`.

**Aviso honesto sobre verificação:** este arquivo é o gate pago e **não tem cobertura unitária** — foi por isso que a lógica ficou toda na Task 1. A prova real da fiação é a Task 4. Aqui você verifica que importa, que o mypy e o ruff passam, e que a coleta funciona.

- [ ] **Step 1: Acrescentar os imports**

No bloco `from mobia.evals.metricas import (...)`, acrescente `InvencaoObservada`, `invencao_do_turno` e `taxa_de_alucinacao`. Deixe o ruff ordenar.

- [ ] **Step 2: Coletar no laço**

Em `_rodar_conversa`, junto das outras listas de acumulação (perto de `respostas: list[RespostaObservada] = []`):

```python
    # TEC-269. Os turnos em que a prosa citou cifra ou codigo sem base.
    invencoes: list[InvencaoObservada] = []
```

E dentro do laço, **imediatamente antes** de `respostas.append(...)`:

```python
        # TEC-269, D3. Depois de `estado_acumulado.update(...)` de proposito:
        # em producao a guarda le a faixa DEPOIS de `gravar_estado`, entao ela
        # inclui o que este turno acabou de extrair. Coletar antes contaria
        # como invencao o modelo ecoando o orcamento que o lead deu neste
        # mesmo turno -- o falso positivo que a D5 da TEC-161 existe para
        # impedir.
        invencao = invencao_do_turno(
            resposta.resposta,
            conversa_id=conversa.id,
            indice=indice,
            candidatos=resposta.candidatos,
            faixa=(
                estado_acumulado.get("faixa_preco_min_centavos"),
                estado_acumulado.get("faixa_preco_max_centavos"),
            ),
        )
        if invencao is not None:
            invencoes.append(invencao)
```

- [ ] **Step 3: Propagar na tupla de retorno**

`_rodar_conversa` devolve hoje uma tupla de 6. Acrescente `list[InvencaoObservada]` à anotação de retorno, depois de `list[PerguntaObservada]`, e `invencoes` ao `return`, na mesma posição.

- [ ] **Step 4: Desempacotar no chamador**

Em `test_acuracia_de_intencao_no_corpus`, o `await _rodar_conversa(...)` desempacota 6 nomes. Acrescente `invencoes_conversa` na mesma posição, declare `invencoes: list[InvencaoObservada] = []` junto das outras listas, e acrescente ao lado dos outros `extend`:

```python
            invencoes.extend(invencoes_conversa)
```

- [ ] **Step 5: Trocar o slot vazio**

Em `_metricas_de`, acrescente o parâmetro `invencoes: list[InvencaoObservada]` depois de `respostas`, e troque a linha

```python
        sem_mecanismo("taxa de alucinacao", "sem mecanismo: bloqueada pela TEC-161"),
```

por

```python
        # TEC-269. Deixou de ser slot vazio: a TEC-161 entregou o mecanismo e
        # esta em `main`. Sem amostra ela cai de volta no slot sozinha, como
        # as outras -- `taxa_de_alucinacao` devolve `sem_mecanismo` quando
        # nenhuma resposta sobreviveu.
        taxa_de_alucinacao(invencoes, respostas),
```

E atualize a chamada: `_metricas_de(resultados, observadas, respostas, invencoes)`.

Atualize também o docstring de `_metricas_de`, que hoje começa com *"As duas declaradas sem mecanismo saem sempre"* — passou a ser **uma**. Comentário desatualizado é defeito neste repo.

- [ ] **Step 6: Verificar sem gastar chamada**

```bash
./.venv/Scripts/python.exe -m pytest evals --collect-only -q
```
Expected: coleta sem erro de import. **`--collect-only` não executa nada e não chama o provedor.**

Depois:
```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 7: Commit**

```bash
git add evals/test_acuracia_de_intencao.py
git commit -m "feat(TEC-269): o gate mede alucinacao em vez de declarar slot vazio"
```

---

### Task 3: Verificação estática e suíte

**Files:** nenhum.

- [ ] **Step 1: Os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 2: A suíte inteira**

```bash
./.venv/Scripts/python.exe -u -m pytest -v --tb=short
```

Baseline em 10/09/2026, commit `f42ea94`: **1408 passed, 2 deselected**, 12min39s. Esta card acrescenta testes unitários, então espere mais que 1408 e nenhum a menos.

**Leia isto antes de interpretar falha.** `ConnectionResetError [WinError 64]` na negociação SSL dentro de fixture é infraestrutura, não código — ~5% dos connects nesta máquina, em rajada. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados. Rode o arquivo sozinho antes de atribuir a falha a esta card, e guarde o hash junto com o resultado.

- [ ] **Step 3: Commit, se algo precisou de ajuste**

Só se houver mudança. Caso contrário, siga.

---

### Task 4: A primeira medição paga

**Files:** nenhum código. Esta task produz um número e o registra.

> **PARE E PEÇA AUTORIZAÇÃO ANTES DESTA TASK.** São 146 chamadas pagas à Anthropic. Nenhuma task anterior gastou um centavo, e esta não deve rodar por inércia.

- [ ] **Step 1: Confirmar com o dono do projeto**

Diga quantas chamadas são e o que a execução vai produzir. Espere um sim explícito.

- [ ] **Step 2: Disparar o gate na branch**

```bash
gh workflow run evals.yml --ref feat/tec-269-taxa-de-alucinacao
```

O `workflow_dispatch` existe para isto — medir sem depender de um PR aberto. Pegue o id com `gh run list --workflow=evals.yml --limit 1`.

- [ ] **Step 3: Ler o relatório**

O CI sobe o relatório como artefato mesmo quando o gate reprova:

```bash
gh run download <RUN_ID> -D <dir>
```

Confira três coisas:
1. A linha `taxa de alucinacao (cifra e codigo)` saiu com número, e **nenhuma linha do relatório cita a TEC-161 como bloqueadora** — é o primeiro cenário Gherkin da card.
2. `conversas abandonadas por infraestrutura: 0`. Se não for 0, a execução não sustenta o número.
3. As outras quatro métricas não se moveram além do ruído conhecido. Baseline de 10/09: intenção 98,6%, efetiva 97,3%, extração 89,1%, tom 98,0%.

- [ ] **Step 4: Registrar a medição no docstring**

Acrescente ao comentário de `PISO_ANDAIME_DE_ANCORAGEM_PCT` uma linha com a data, o commit e o número medido — no molde do histórico que a docstring do teto do orçamento do prompt mantém. **Não substitua o andaime pelo piso medido nesta card:** uma execução não é distribuição, e o próprio relatório avisa que duas execuções do mesmo código já diferiram 5,7 pontos noutra métrica. Trocar o andaime por piso é card própria, depois de haver histórico.

- [ ] **Step 5: Commit**

```bash
git add src/mobia/evals/metricas.py
git commit -m "docs(TEC-269): a primeira medicao da taxa de alucinacao entra no historico"
```

---

## Cobertura do desenho

| Decisão | Onde |
|---|---|
| D1 — mede invenção sem busca | Task 1, `invencao_do_turno` com `candidatos` vazio; Task 2 passa `resposta.candidatos` |
| D2 — reusa `divergencias_de`, piso versionado | Task 1, o import e o comentário de `PISO_ANDAIME_DE_ANCORAGEM_PCT` |
| D3 — faixa depois da extração do turno | Task 2, Step 2 (posição no laço) + `test_eco_do_orcamento_do_lead_nao_e_invencao` |
| D4 — nome carrega o escopo | Task 1, `NOME_DA_TAXA_DE_ALUCINACAO` + asserção no teste do detalhe |
| D5 — conta limpos, reporta taxa | Task 1, `taxa_de_alucinacao` + `test_o_detalhe_reporta_a_taxa_e_nao_o_complemento` |
| D6 — piso-andaime | Task 1, a constante; Task 4 Step 4, o histórico |
| D7 — sem amostra volta a `sem_mecanismo` | Task 1, `test_sem_amostra_volta_para_sem_mecanismo` |
| D8 — onde o código mora | Estrutura de arquivos |

# TEC-282 — Estender a listagem de comentários à prosa que descreve o código

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/comentarios_tocados.py` passa a apontar a prosa versionada cuja citação `arquivo.py:linha` recai sobre arquivo que a branch mexeu, numa seção própria agrupada por documento.

**Architecture:** Todas as peças novas vivem no mesmo script, que vai de 352 para ~500 linhas. As funções que **decidem** são puras — recebem texto, conjuntos e uma função que mede arquivo, e não tocam git nem disco. As que tocam git e disco (`_documentos_no_escopo`, `examinar_prosa`) só coletam e delegam. É o mesmo corte que a TEC-277 deixou entre `examinar`/`limitar` e `main`, e é o que torna a suíte unitária possível sem Docker.

**Tech Stack:** Python 3.13, stdlib apenas (`re`, `subprocess`, `dataclasses`, `pathlib`). pytest para os testes. Sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-15-tec-282-prosa-que-descreve-o-codigo-design.md`

## Global Constraints

- **Comentários e docstrings em `src/`, `tests/` e `scripts/`: português SEM acento.** Exceto valor citado, que segue o valor.
- **Prosa em `docs/` e `CLAUDE.md`: com acento.**
- **Mensagem de commit:** `tipo(TEC-282): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Os três gates, com este escopo exato, antes de qualquer commit:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- **Os testes desta card são unitários e não precisam de `docker compose`:** `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short`. Sem `-n`.
- **A ferramenta continua devolvendo 0 sempre.** Nada aqui vira gate.
- **O teto `MAXIMO_DE_CITACOES_POR_DOCUMENTO = 5` é constante nova**, não reutiliza `MAXIMO_DE_VIZINHOS_POR_BLOCO` (D6 do desenho).

---

## File Structure

| arquivo | responsabilidade |
| --- | --- |
| `scripts/comentarios_tocados.py` (modifica) | tudo: regex, resolução, classificação, teto e impressão |
| `tests/unit/test_comentarios_tocados.py` (acrescenta) | os testes das peças novas, puros |
| `CLAUDE.md` (modifica, Task 8) | a seção "Comentário não mente" passa a descrever as três marcas novas |

Nada é criado. O script é uma ferramenta de um arquivo e continua assim: parti-lo exigiria um pacote sob `scripts/`, e o desenho recusou esse custo.

---

### Task 1: O regex que reconhece uma citação

**Files:**
- Modify: `scripts/comentarios_tocados.py` (acrescenta `_CITACAO` perto de `_CABECALHO:46` e `citacoes_do_texto` depois de `_blocos:162`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: nada
- Produces: `citacoes_do_texto(texto: str) -> list[tuple[int, str, int, int]]` — por citação, `(linha do documento, alvo cru, primeira linha citada, ultima linha citada)`. Linha única devolve `inicio == fim`.

- [ ] **Step 1: Write the failing test**

Em `tests/unit/test_comentarios_tocados.py`, acrescenta ao final:

```python
def test_citacao_reconhece_linha_unica_e_faixa() -> None:
    """As duas formas que a prosa deste repo usa, medidas na TEC-282.

    Faixa devolve inicio e fim distintos; linha unica devolve os dois iguais,
    para o resto do codigo nao precisar de dois caminhos.
    """
    texto = "olha `tests/conftest.py:464` e tambem turno.py:132-142 aqui"
    assert citacoes_do_texto(texto) == [
        (1, "tests/conftest.py", 464, 464),
        (1, "turno.py", 132, 142),
    ]


def test_citacao_nao_casa_no_meio_de_um_caminho() -> None:
    """O lookbehind existe para o alvo sair inteiro, nao pela metade.

    Sem ele `src/mobia/turno.py:10` poderia casar comecando em `mobia/`, e a
    resolucao receberia um caminho que nao existe.
    """
    assert citacoes_do_texto("src/mobia/turno.py:10") == [(1, "src/mobia/turno.py", 10, 10)]


def test_citacao_ignora_o_que_nao_e_citacao() -> None:
    """Extensao vizinha e link com `#L` nao sao a forma `arquivo.py:linha`.

    O link markdown deste repo traz o texto visivel `turno.py:508` junto, e e
    ele que casa -- o alvo do link nao precisa casar tambem, sob pena de o
    mesmo ponto virar dois achados.
    """
    assert citacoes_do_texto("nada.pyc:12 nem x.py sozinho") == []
    assert citacoes_do_texto("[`turno.py:508`](../src/turno.py#L508)") == [
        (1, "turno.py", 508, 508)
    ]


def test_citacao_informa_a_linha_do_documento() -> None:
    """A linha e a do .md, nao a citada -- e por ela que o revisor abre o texto."""
    assert citacoes_do_texto("primeira\nsegunda\nveja turno.py:50") == [(3, "turno.py", 50, 50)]
```

E ao bloco de import do arquivo de teste, acrescenta `citacoes_do_texto`:

```python
from scripts.comentarios_tocados import (
    MAXIMO_DE_VIZINHOS_POR_BLOCO,
    Achado,
    _blocos,
    _comentarios,
    _docstrings,
    citacoes_do_texto,
    examinar,
    limitar,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k citacao --tb=short`
Expected: FAIL com `ImportError: cannot import name 'citacoes_do_texto'`

- [ ] **Step 3: Write minimal implementation**

Em `scripts/comentarios_tocados.py`, logo abaixo de `_CABECALHO` (linha 46):

```python
# `arquivo.py:12` e `arquivo.py:12-34`, com ou sem caminho antes do nome.
#
# O lookbehind existe para o alvo sair inteiro: sem ele o motor casaria
# `mobia/turno.py:10` dentro de `src/mobia/turno.py:10`, e a resolucao
# receberia um caminho que nao existe em lugar nenhum.
#
# Exige `:` colado no `.py`, o que descarta de graca `.pyc`, `.pyi` e o
# `arquivo.py#L508` dos links markdown -- este ultimo importa, porque o link
# deste repo traz o texto visivel `turno.py:508` junto, e casar os dois faria
# um ponto so virar dois achados.
_CITACAO = re.compile(r"(?<![\w/.-])((?:[\w./-]+/)?[\w-]+\.py):(\d+)(?:-(\d+))?")
```

E depois de `_blocos` (que termina na linha 179):

```python
def citacoes_do_texto(texto: str) -> list[tuple[int, str, int, int]]:
    """Cada citacao como (linha do documento, alvo cru, primeira, ultima).

    A linha e a do documento, nao a citada: e por ela que quem revisa abre o
    .md para reconferir. Linha unica devolve `inicio == fim` para o resto do
    codigo nao precisar de dois caminhos.
    """
    achados = []
    for numero, linha in enumerate(texto.splitlines(), 1):
        for casa in _CITACAO.finditer(linha):
            inicio = int(casa.group(2))
            fim = int(casa.group(3)) if casa.group(3) is not None else inicio
            achados.append((numero, casa.group(1), inicio, fim))
    return achados
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k citacao --tb=short`
Expected: 4 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): a ferramenta reconhece a citacao arquivo.py:linha na prosa

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A resolução do alvo em três degraus

**Files:**
- Modify: `scripts/comentarios_tocados.py` (acrescenta `resolver` depois de `citacoes_do_texto`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: os alvos crus que `citacoes_do_texto` devolve
- Produces: `resolver(alvo: str, arquivos_py: set[str]) -> list[str]` — os `.py` versionados que o alvo pode designar, ordenados. Lista de um elemento significa inequívoco; vazia significa que não resolve.

- [ ] **Step 1: Write the failing test**

```python
_PY = {
    "src/mobia/domain/agente/turno.py",
    "src/mobia/domain/followup/repositorio.py",
    "src/mobia/domain/outbound/repositorio.py",
    "tests/conftest.py",
}


def test_resolver_aceita_o_caminho_exato() -> None:
    assert resolver("tests/conftest.py", _PY) == ["tests/conftest.py"]


def test_resolver_aceita_sufixo_de_caminho() -> None:
    """`agente/turno.py` designa o arquivo sem que a prosa repita src/mobia/."""
    assert resolver("agente/turno.py", _PY) == ["src/mobia/domain/agente/turno.py"]


def test_resolver_aceita_o_nome_sozinho() -> None:
    """55 das 155 citacoes medidas na TEC-282 sao so o nome, sem caminho."""
    assert resolver("turno.py", _PY) == ["src/mobia/domain/agente/turno.py"]


def test_resolver_devolve_os_dois_quando_o_nome_e_ambiguo() -> None:
    """`repositorio.py` bate 9 arquivos no repo real.

    A ferramenta nao escolhe um: devolve os candidatos e deixa a classificacao
    decidir, que e onde a regra de errar por sobra e nao por falta mora.
    """
    assert resolver("repositorio.py", _PY) == [
        "src/mobia/domain/followup/repositorio.py",
        "src/mobia/domain/outbound/repositorio.py",
    ]


def test_resolver_devolve_vazio_para_arquivo_que_nao_existe() -> None:
    assert resolver("inventado.py", _PY) == []


def test_resolver_nao_confunde_sufixo_parcial_de_nome() -> None:
    """`no.py` nao e sufixo de caminho de `turno.py` -- a fronteira e a barra.

    Sem a barra na comparacao, qualquer nome que termine igual casaria, e a
    listagem apontaria arquivos que a prosa nunca citou.
    """
    assert resolver("no.py", _PY) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k resolver --tb=short`
Expected: FAIL com `ImportError: cannot import name 'resolver'`

- [ ] **Step 3: Write minimal implementation**

```python
def resolver(alvo: str, arquivos_py: set[str]) -> list[str]:
    """Os .py versionados que este alvo pode designar, em tres degraus.

    Caminho exato, depois sufixo de caminho (`agente/turno.py`), depois o nome
    sozinho (`turno.py`). Devolver mais de um e o caso ambiguo e nao um erro:
    medido na TEC-282, 145 das 155 citacoes do repo resolvem para um arquivo
    so, porque quase todo nome citado e unico.

    A comparacao de sufixo leva a barra junto, senao `no.py` casaria com
    `turno.py` e a listagem apontaria arquivo que a prosa nunca citou.
    """
    if alvo in arquivos_py:
        return [alvo]
    if "/" in alvo:
        return sorted(p for p in arquivos_py if p.endswith("/" + alvo))
    return sorted(p for p in arquivos_py if p.rsplit("/", 1)[-1] == alvo)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k resolver --tb=short`
Expected: 6 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): o alvo citado resolve por caminho, sufixo ou nome

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A classificação — `PROSA`, `FALSO`, ou nada

**Files:**
- Modify: `scripts/comentarios_tocados.py` (acrescenta `Citacao` depois de `Achado:81`, e `classificar` depois de `resolver`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: `resolver` (Task 2)
- Produces:
  - `Citacao` — dataclass congelada com `documento: str`, `linha: int`, `texto: str`, `marca: str`, `destino: str = ""`.
  - `classificar(candidatos: list[str], fim: int, alterados: set[str], tamanho_de: Callable[[str], int]) -> str | None` — devolve `"FALSO"`, `"PROSA"` ou `None`. `None` significa que a citação não diz respeito a esta branch.

- [ ] **Step 1: Write the failing test**

```python
def _tamanhos(mapa: dict[str, int]) -> Callable[[str], int]:
    return lambda caminho: mapa[caminho]


def test_citacao_a_arquivo_alterado_e_prosa() -> None:
    marca = classificar(["a/turno.py"], 50, {"a/turno.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca == "PROSA"


def test_citacao_a_arquivo_intocado_nao_vira_achado() -> None:
    """A ferramenta continua sendo sobre o que a branch tocou."""
    assert classificar(["a/turno.py"], 50, {"outro.py"}, _tamanhos({"a/turno.py": 300})) is None


def test_citacao_que_nao_resolve_nao_vira_achado() -> None:
    assert classificar([], 50, {"a/turno.py"}, _tamanhos({})) is None


def test_faixa_alem_do_fim_do_arquivo_e_falso() -> None:
    """A unica marca que afirma, em vez de suspeitar."""
    marca = classificar(["a/turno.py"], 900, {"a/turno.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca == "FALSO"


def test_a_ultima_linha_do_arquivo_ainda_e_prosa() -> None:
    """A fronteira e `>`, nao `>=`: citar a ultima linha e citacao valida."""
    marca = classificar(["a/turno.py"], 300, {"a/turno.py"}, _tamanhos({"a/turno.py": 300}))
    assert marca == "PROSA"


def test_citacao_ambigua_alem_do_fim_sai_como_prosa_e_nao_falso() -> None:
    """FALSO exige resolucao inequivoca, e a razao e a direcao do erro.

    Declarar falsa uma citacao que talvez aponte o OUTRO candidato seria a
    ferramenta afirmando o que nao sabe -- o unico erro que ela nao pode
    cometer, porque `FALSO` e a marca que dispensa o revisor de conferir.
    """
    marca = classificar(
        ["a/repositorio.py", "b/repositorio.py"],
        900,
        {"a/repositorio.py"},
        _tamanhos({"a/repositorio.py": 300, "b/repositorio.py": 1000}),
    )
    assert marca == "PROSA"
```

E acrescenta `from collections.abc import Callable` ao topo do arquivo de teste, mais `Citacao` e `classificar` ao import.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "classificar or falso or prosa or ambigua" --tb=short`
Expected: FAIL com `ImportError: cannot import name 'classificar'`

- [ ] **Step 3: Write minimal implementation**

Acrescenta `from collections.abc import Callable` aos imports do script (linha 41, junto de `dataclasses`).

Depois de `Achado` (linha 81):

```python
@dataclass(frozen=True)
class Citacao:
    # `linha` e a do DOCUMENTO, nao a citada: e por ela que quem revisa abre o
    # .md. `destino` so e preenchido quando a resolucao foi inequivoca e diz
    # algo que o alvo cru nao dizia -- para `turno.py:50` ele mostra onde o
    # arquivo mora; para um alvo que ja veio com caminho completo, fica vazio.
    documento: str
    linha: int
    texto: str
    marca: str
    destino: str = ""
```

Depois de `resolver`:

```python
def classificar(
    candidatos: list[str],
    fim: int,
    alterados: set[str],
    tamanho_de: Callable[[str], int],
) -> str | None:
    """A marca desta citacao, ou None quando ela nao diz respeito a esta branch.

    `FALSO` exige resolucao inequivoca porque e a unica marca que AFIRMA algo
    em vez de suspeitar: ela dispensa o revisor de conferir. Declarar falsa uma
    citacao que talvez aponte o outro candidato seria errar justamente na
    direcao em que esta ferramenta nao pode errar. Citacao ambigua alem do fim
    de um dos candidatos sai como `PROSA` e o revisor decide.

    A comparacao e `>` e nao `>=`: citar a ultima linha do arquivo e citacao
    valida, nao afirmacao falsa.
    """
    if not any(caminho in alterados for caminho in candidatos):
        return None
    if len(candidatos) == 1 and fim > tamanho_de(candidatos[0]):
        return "FALSO"
    return "PROSA"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "classificar or falso or prosa or ambigua" --tb=short`
Expected: 6 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): FALSO so sai com resolucao inequivoca, PROSA cobre o resto

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `NOMEIA` — a prosa que nomeia um script alterado

**Files:**
- Modify: `scripts/comentarios_tocados.py` (acrescenta `scripts_nomeados` depois de `classificar`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: nada das tarefas anteriores
- Produces: `scripts_nomeados(texto: str, scripts: set[str]) -> list[tuple[int, str]]` — `(linha do documento, nome do script)`, no máximo uma entrada por script.

- [ ] **Step 1: Write the failing test**

```python
def test_nomeia_encontra_o_script_alterado_no_texto() -> None:
    texto = "rode `scripts/comentarios_tocados.py` antes do PR"
    assert scripts_nomeados(texto, {"comentarios_tocados.py"}) == [(1, "comentarios_tocados.py")]


def test_nomeia_ignora_script_que_a_branch_nao_tocou() -> None:
    assert scripts_nomeados("veja gerar_base_simulada.py", {"comentarios_tocados.py"}) == []


def test_nomeia_sai_uma_vez_so_por_script() -> None:
    """O CLAUDE.md nomeia o script duas vezes e e um documento a reconferir, nao dois.

    Repetir a marca por ocorrencia encheria a secao com o mesmo aviso e e
    exatamente o volume que a TEC-277 mediu e cortou.
    """
    texto = "comentarios_tocados.py\noutra linha\ncomentarios_tocados.py --tudo"
    assert scripts_nomeados(texto, {"comentarios_tocados.py"}) == [
        (1, "comentarios_tocados.py")
    ]


def test_nomeia_encontra_dentro_de_bloco_de_codigo() -> None:
    """Medido na TEC-282: no CLAUDE.md as duas mencoes estao DENTRO de fences.

    Filtrar bloco de codigo excluiria justamente o documento que a card existe
    para pegar -- a prosa que descreve o script vive ao redor do bloco, sem
    repetir o nome do arquivo.
    """
    texto = "```bash\n./.venv/Scripts/python.exe scripts/comentarios_tocados.py\n```"
    assert scripts_nomeados(texto, {"comentarios_tocados.py"}) == [
        (2, "comentarios_tocados.py")
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k nomeia --tb=short`
Expected: FAIL com `ImportError: cannot import name 'scripts_nomeados'`

- [ ] **Step 3: Write minimal implementation**

```python
def scripts_nomeados(texto: str, scripts: set[str]) -> list[tuple[int, str]]:
    """A primeira linha em que este documento nomeia cada script alterado.

    Uma entrada por script, nao por ocorrencia: o CLAUDE.md nomeia a ferramenta
    duas vezes e e UM documento a reconferir. Repetir por ocorrencia encheria a
    secao com o mesmo aviso, que e o volume que a TEC-277 mediu e cortou.

    Busca literal, inclusive dentro de bloco de codigo cercado. Medido na
    TEC-282: no CLAUDE.md as duas mencoes estao dentro de fences e fora deles
    ha zero, entao filtrar bloco de codigo excluiria justamente o documento que
    esta regra existe para pegar -- a prosa que descreve o script vive ao redor
    do bloco, sem repetir o nome do arquivo.

    Este e o unico casamento por NOME da ferramenta, e e estreito de proposito:
    a TEC-277 mediu 83,8% de homonimia ao casar prosa com codigo por nome de
    simbolo. Nome de script nao tem esse problema porque o conjunto e minusculo
    e os nomes sao longos.
    """
    achados = []
    for nome in sorted(scripts):
        for numero, linha in enumerate(texto.splitlines(), 1):
            if nome in linha:
                achados.append((numero, nome))
                break
    return achados
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k nomeia --tb=short`
Expected: 4 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): mudanca sob scripts aponta a prosa que nomeia o script

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: O teto por documento

**Files:**
- Modify: `scripts/comentarios_tocados.py` (acrescenta `MAXIMO_DE_CITACOES_POR_DOCUMENTO` depois de `MAXIMO_DE_VIZINHOS_POR_BLOCO:64`, e `limitar_citacoes` depois de `limitar:238`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: `Citacao` (Task 3)
- Produces: `limitar_citacoes(citacoes: list[Citacao], *, teto: int) -> tuple[list[Citacao], int]` — as que ficam, em ordem de linha do documento, e quantas ficaram de fora. `teto <= 0` desliga o corte.

- [ ] **Step 1: Write the failing test**

```python
def _prosa(linha: int, marca: str = "PROSA") -> Citacao:
    return Citacao(documento="d.md", linha=linha, texto="x.py:1", marca=marca)


def test_documento_abaixo_do_teto_passa_inteiro() -> None:
    citacoes = [_prosa(n) for n in range(1, MAXIMO_DE_CITACOES_POR_DOCUMENTO + 1)]
    ficam, omitidas = limitar_citacoes(citacoes, teto=MAXIMO_DE_CITACOES_POR_DOCUMENTO)
    assert len(ficam) == MAXIMO_DE_CITACOES_POR_DOCUMENTO
    assert omitidas == 0


def test_o_teto_corta_prosa_e_conta_o_que_omitiu() -> None:
    citacoes = [_prosa(n) for n in range(1, 10)]
    ficam, omitidas = limitar_citacoes(citacoes, teto=5)
    assert [c.linha for c in ficam] == [1, 2, 3, 4, 5]
    assert omitidas == 4


def test_falso_e_nomeia_escapam_do_teto() -> None:
    """Pela mesma razao que ALTERADO escapa: o teto existe contra vizinhanca.

    Um FALSO cortado seria a ferramenta escondendo a unica coisa que ela sabe
    com certeza estar errada.
    """
    citacoes = [_prosa(n) for n in range(1, 10)]
    citacoes.append(_prosa(20, marca="FALSO"))
    citacoes.append(_prosa(21, marca="NOMEIA"))
    ficam, omitidas = limitar_citacoes(citacoes, teto=2)
    assert [c.linha for c in ficam] == [1, 2, 20, 21]
    assert omitidas == 7


def test_teto_zero_desliga_o_corte_das_citacoes() -> None:
    """E assim que --tudo e implementado, sem caminho separado que possa divergir."""
    citacoes = [_prosa(n) for n in range(1, 10)]
    ficam, omitidas = limitar_citacoes(citacoes, teto=0)
    assert len(ficam) == 9
    assert omitidas == 0


def test_as_citacoes_saem_em_ordem_de_linha_do_documento() -> None:
    ficam, _ = limitar_citacoes([_prosa(9), _prosa(2), _prosa(5)], teto=0)
    assert [c.linha for c in ficam] == [2, 5, 9]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "limitar_citacoes or teto_zero_desliga_o_corte_das or escapam" --tb=short`
Expected: FAIL com `ImportError: cannot import name 'limitar_citacoes'`

- [ ] **Step 3: Write minimal implementation**

Depois de `MAXIMO_DE_VIZINHOS_POR_BLOCO` (linha 64):

```python
# O teto de citacoes impressas por documento na saida padrao.
#
# Constante propria, e nao o MAXIMO_DE_VIZINHOS_POR_BLOCO acima, porque sao
# dois cortes diferentes: aquele limita vizinhanca dentro de um def, este
# limita citacoes dentro de um .md. Reutilizar aquele nome o faria mentir
# sobre o que limita, e este repo trata nome que mente como defeito.
#
# **O valor foi herdado da TEC-277, nao calibrado.** Medido na TEC-282 sobre
# os 11 merges mais recentes, ele quase nunca morde: mediana de 9 citacoes
# espalhadas por ate 8 documentos da 1 a 3 por documento, e o maximo observado
# (25 em 8 documentos) tambem passa longe. Ele existe como rede contra o
# documento que venha a concentrar citacoes, nao como corte rotineiro -- se um
# dia a secao ficar longa, a calibracao e dele, e a medicao acima e o ponto de
# partida.
MAXIMO_DE_CITACOES_POR_DOCUMENTO = 5
```

Depois de `limitar` (que termina na linha 282):

```python
def limitar_citacoes(citacoes: list[Citacao], *, teto: int) -> tuple[list[Citacao], int]:
    """As citacoes que ficam neste documento, e quantas ficaram de fora.

    So `PROSA` e cortada. `FALSO` e `NOMEIA` escapam pela mesma razao que
    `ALTERADO` escapa em `limitar`: o teto existe contra ruido de vizinhanca e
    nenhuma das duas e vizinhanca. Um `FALSO` cortado seria a ferramenta
    escondendo a unica coisa que ela sabe com certeza estar errada.

    `teto` de 0 desliga o corte -- e assim que `--tudo` e implementado, pelo
    mesmo caminho que `limitar` usa, sem um ramo separado que possa divergir.

    Ordena por linha do documento, que e a unica ordem estavel disponivel: ao
    contrario de `VIZINHO`, uma citacao nao tem distancia ate a alteracao.
    """
    ordenadas = sorted(citacoes, key=lambda c: c.linha)
    if teto <= 0:
        return ordenadas, 0
    ficam = [c for c in ordenadas if c.marca != "PROSA"]
    prosa = [c for c in ordenadas if c.marca == "PROSA"]
    ficam.extend(prosa[:teto])
    return sorted(ficam, key=lambda c: c.linha), max(len(prosa) - teto, 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "limitar_citacoes or teto_zero_desliga_o_corte_das or escapam or ordem_de_linha_do_documento or abaixo_do_teto_passa" --tb=short`
Expected: 5 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): a prosa ganha teto proprio por documento

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: A cola — escopo dos documentos e montagem dos achados

**Files:**
- Modify: `scripts/comentarios_tocados.py` (acrescenta `PREFIXO_DOS_PLANOS`, `_documentos_no_escopo`, `_arquivos_versionados` e `examinar_prosa`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: `citacoes_do_texto` (T1), `resolver` (T2), `classificar` + `Citacao` (T3), `scripts_nomeados` (T4)
- Produces:
  - `_documentos_no_escopo() -> list[str]` — `.md` versionados fora de `docs/superpowers/plans/`.
  - `_arquivos_versionados() -> set[str]` — todos os `.py` versionados.
  - `examinar_prosa(documento: str, texto: str, arquivos_py: set[str], alterados: set[str], scripts: set[str], tamanho_de: Callable[[str], int]) -> list[Citacao]` — puro; quem lê disco é o chamador.

- [ ] **Step 1: Write the failing test**

```python
def test_examinar_prosa_monta_as_tres_marcas() -> None:
    texto = (
        "o corte em repositorio.py:209 explica tudo\n"
        "e test_x.py:900 aponta alem do fim\n"
        "rode scripts/comentarios_tocados.py antes do PR\n"
        "mas intocado.py:5 nao interessa\n"
    )
    achados = examinar_prosa(
        "CLAUDE.md",
        texto,
        arquivos_py={"a/repositorio.py", "t/test_x.py", "intocado.py"},
        alterados={"a/repositorio.py", "t/test_x.py"},
        scripts={"comentarios_tocados.py"},
        tamanho_de=lambda c: 300,
    )
    assert [(c.linha, c.marca) for c in achados] == [
        (1, "PROSA"),
        (2, "FALSO"),
        (3, "NOMEIA"),
    ]


def test_examinar_prosa_preenche_o_destino_so_quando_ele_acrescenta() -> None:
    """Para `repositorio.py:209` o destino diz onde o arquivo mora.

    Para um alvo que ja veio com caminho completo, repetir o caminho na saida
    seria ruido -- o revisor ja leu a mesma string dois centimetros antes.
    """
    achados = examinar_prosa(
        "d.md",
        "repositorio.py:9 e a/turno.py:9",
        arquivos_py={"a/repositorio.py", "a/turno.py"},
        alterados={"a/repositorio.py", "a/turno.py"},
        scripts=set(),
        tamanho_de=lambda c: 300,
    )
    assert [c.destino for c in achados] == ["a/repositorio.py", ""]


def test_examinar_prosa_nao_marca_nada_sem_script_alterado() -> None:
    achados = examinar_prosa(
        "CLAUDE.md",
        "rode scripts/comentarios_tocados.py",
        arquivos_py=set(),
        alterados=set(),
        scripts=set(),
        tamanho_de=lambda c: 300,
    )
    assert achados == []


def test_o_escopo_exclui_planos_e_inclui_o_claude_md(monkeypatch) -> None:
    """D1 do desenho: 70% do volume medido vinha de planos de branches fechadas."""
    monkeypatch.setattr(
        ferramenta,
        "_rodar",
        lambda *a: "CLAUDE.md\ndocs/superpowers/plans/x.md\ndocs/superpowers/specs/y.md\n",
    )
    assert ferramenta._documentos_no_escopo() == ["CLAUDE.md", "docs/superpowers/specs/y.md"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "examinar_prosa or escopo_exclui" --tb=short`
Expected: FAIL com `ImportError: cannot import name 'examinar_prosa'`

- [ ] **Step 3: Write minimal implementation**

Junto das outras constantes, depois de `MAXIMO_DE_CITACOES_POR_DOCUMENTO`:

```python
# Planos de implementacao ficam fora da varredura de prosa.
#
# Um plano registra o que se fez numa branch num dia: ele nao afirma o que o
# codigo E hoje, afirma o que se pretendia mexer naquela ocasiao. Envelhecer e
# o comportamento esperado dele, e "corrigir" um plano fechado seria reescrever
# historico -- o mesmo raciocinio que mantem as emendas do SRS como itens
# aninhados em vez de reescrita.
#
# Medido na TEC-282: o corte leva a mediana de citacoes por branch de 39 para
# 9, e leva os documentos que nomeiam este script de 21 para 2. **Custo real e
# declarado:** 3 das 6 citacoes comprovadamente falsas de hoje estao em planos
# e deixam de ser apontadas.
PREFIXO_DOS_PLANOS = "docs/superpowers/plans/"
```

Depois de `_pendentes_fora_do_commit`:

```python
def _documentos_no_escopo() -> list[str]:
    """Os .md versionados que a varredura de prosa examina."""
    saida = _rodar("ls-files", "*.md")
    return [d for d in saida.split() if not d.startswith(PREFIXO_DOS_PLANOS)]


def _arquivos_versionados() -> set[str]:
    """Todo .py versionado, que e o universo contra o qual um alvo resolve."""
    return {p for p in _rodar("ls-files", "*.py").split()}


def examinar_prosa(
    documento: str,
    texto: str,
    arquivos_py: set[str],
    alterados: set[str],
    scripts: set[str],
    tamanho_de: Callable[[str], int],
) -> list[Citacao]:
    """As citacoes deste documento que esta branch obriga a reconferir.

    Puro de proposito: recebe o texto ja lido, para o teste nao precisar de
    disco nem de git. Quem le e o chamador.
    """
    achados = []
    for linha, alvo, _, fim in citacoes_do_texto(texto):
        candidatos = resolver(alvo, arquivos_py)
        marca = classificar(candidatos, fim, alterados, tamanho_de)
        if marca is None:
            continue
        # O destino so acrescenta quando a resolucao descobriu algo que o alvo
        # cru nao dizia. Repetir um caminho completo que o revisor acabou de
        # ler dois centimetros antes e ruido.
        destino = candidatos[0] if len(candidatos) == 1 and candidatos[0] != alvo else ""
        achados.append(Citacao(documento, linha, f"{alvo}:{fim}", marca, destino))
    for linha, nome in scripts_nomeados(texto, scripts):
        achados.append(Citacao(documento, linha, f"descreve scripts/{nome}", "NOMEIA"))
    return sorted(achados, key=lambda c: c.linha)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "examinar_prosa or escopo_exclui" --tb=short`
Expected: 4 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): a varredura de prosa exclui os planos e monta os achados

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: A seção nova na saída

**Files:**
- Modify: `scripts/comentarios_tocados.py:284-347` (a função `main`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: tudo das tarefas 1 a 6
- Produces: a seção impressa e o rodapé. Nenhuma função nova exportada.

- [ ] **Step 1: Write the failing test**

```python
def test_main_imprime_a_secao_de_prosa(monkeypatch, capsys, tmp_path) -> None:
    """O caminho inteiro, de ponta a ponta, com git e disco falsos."""
    alvo = tmp_path / "turno.py"
    alvo.write_text("x = 1\n" * 300, encoding="utf-8")
    documento = tmp_path / "CLAUDE.md"
    documento.write_text("o corte em turno.py:50 explica tudo\n", encoding="utf-8")

    def _git(*argumentos: str) -> str:
        if argumentos[0] == "diff":
            return "+++ b/turno.py\n@@ -1 +40,3 @@\n"
        if argumentos[:2] == ("ls-files", "*.md"):
            return "CLAUDE.md\n"
        if argumentos[:2] == ("ls-files", "*.py"):
            return "turno.py\n"
        return ""

    monkeypatch.setattr(ferramenta, "_rodar", _git)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py"])

    assert ferramenta.main() == 0
    saida = capsys.readouterr().out
    assert "CLAUDE.md" in saida
    assert "PROSA" in saida
    assert "turno.py:50" in saida
    assert "1 em prosa" in saida


def test_main_continua_devolvendo_zero_com_prosa_falsa(monkeypatch, capsys, tmp_path) -> None:
    """A ferramenta informa e nao reprova, e a marca FALSO nao muda isso."""
    (tmp_path / "turno.py").write_text("x = 1\n" * 10, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("veja turno.py:900\n", encoding="utf-8")

    def _git(*argumentos: str) -> str:
        if argumentos[0] == "diff":
            return "+++ b/turno.py\n@@ -1 +5,1 @@\n"
        if argumentos[:2] == ("ls-files", "*.md"):
            return "CLAUDE.md\n"
        if argumentos[:2] == ("ls-files", "*.py"):
            return "turno.py\n"
        return ""

    monkeypatch.setattr(ferramenta, "_rodar", _git)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py"])

    assert ferramenta.main() == 0
    saida = capsys.readouterr().out
    assert "FALSO" in saida
    assert "comprovadamente falsa" in saida
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k main_imprime --tb=short`
Expected: FAIL — a saída não contém `PROSA`

- [ ] **Step 3: Write minimal implementation**

Em `main`, substitui o bloco `argumentos = analisador.parse_args()` até o `return 0` final.

Ajusta o help de `--tudo` (linha 296), que hoje fala só de vizinhos:

```python
    analisador.add_argument(
        "--tudo",
        action="store_true",
        help="imprime todos os vizinhos e todas as citacoes, sem teto",
    )
```

Depois do laço que imprime os arquivos `.py`, antes do `if not alterados and not vizinhos`:

```python
    em_prosa = falsas = 0
    alterados_como_texto = {str(caminho).replace("\\", "/") for caminho in por_arquivo}
    scripts_alterados = {
        caminho.rsplit("/", 1)[-1]
        for caminho in alterados_como_texto
        if caminho.startswith("scripts/")
    }
    arquivos_py = _arquivos_versionados()
    tamanhos: dict[str, int] = {}

    def tamanho_de(caminho: str) -> int:
        # Memorizado porque um documento pode citar o mesmo arquivo dezenas de
        # vezes, e cada citacao perguntaria o tamanho de novo.
        if caminho not in tamanhos:
            try:
                tamanhos[caminho] = len(Path(caminho).read_text(encoding="utf-8").splitlines())
            except OSError:
                tamanhos[caminho] = 0
        return tamanhos[caminho]

    for documento in _documentos_no_escopo():
        try:
            texto = Path(documento).read_text(encoding="utf-8")
        except OSError:
            continue
        citacoes = examinar_prosa(
            documento,
            texto,
            arquivos_py,
            alterados_como_texto,
            scripts_alterados,
            tamanho_de,
        )
        if not citacoes:
            continue
        ficam, omitidas = limitar_citacoes(citacoes, teto=teto_da_prosa)
        print(f"\n{documento}")
        for citacao in ficam:
            destino = f"  -> {citacao.destino}" if citacao.destino else ""
            print(f"  {citacao.marca:<6} :{citacao.linha}  {citacao.texto}{destino}")
            if citacao.marca == "FALSO":
                falsas += 1
            else:
                em_prosa += 1
        if omitidas:
            # Conta o que EXISTE, nao o que coube na tela -- mesma regra do
            # resumo de vizinhos, pelo mesmo motivo.
            em_prosa += omitidas
            print(f"  ... +{omitidas} citacao(oes) omitida(s) -- use --tudo")
```

O `teto_da_prosa` sai junto do `teto`, logo depois de `parse_args`:

```python
    teto = 0 if argumentos.tudo else MAXIMO_DE_VIZINHOS_POR_BLOCO
    teto_da_prosa = 0 if argumentos.tudo else MAXIMO_DE_CITACOES_POR_DOCUMENTO
```

E o rodapé passa a contar a prosa:

```python
    if not alterados and not vizinhos and not em_prosa and not falsas:
        print(f"Nenhum comentario, docstring ou prosa a reconferir em relacao a {base}.")
        return 0

    resumo = f"\n{alterados} alterado(s) nesta branch, {vizinhos} vizinho(s) de codigo que mudou"
    if em_prosa or falsas:
        resumo += f", {em_prosa + falsas} em prosa ({falsas} comprovadamente falsa(s))"
    print(
        f"{resumo}.\n"
        "VIZINHO e o que nao aparece no diff: confira se ainda descreve o codigo.\n"
        "PROSA e suspeita e FALSO e certeza: a citacao aponta alem do fim do arquivo."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short`
Expected: toda a suíte do arquivo passa, antigos inclusive

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-282): a listagem ganha secao de prosa agrupada por documento

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: A prosa que descreve a própria ferramenta, e a verificação de ponta a ponta

**Files:**
- Modify: `scripts/comentarios_tocados.py:1-33` (a docstring do módulo)
- Modify: `CLAUDE.md:109-132` (a seção "Comentário não mente")
- Test: a própria ferramenta, rodada contra esta branch

Esta task é o critério de aceite nº 3 da card exercitado contra si mesmo: a branch altera `scripts/comentarios_tocados.py`, então a ferramenta **tem** de apontar o `CLAUDE.md` com `NOMEIA`. Se não apontar, a Task 4 ou a Task 7 está errada.

- [ ] **Step 1: Rodar a ferramenta contra a própria branch**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
```

Expected: a saída contém uma seção `CLAUDE.md` com `NOMEIA`, e uma seção para o desenho da TEC-277 (que também nomeia o script). Guarde a saída — ela é a evidência do critério de aceite, e vai no comentário da card.

- [ ] **Step 2: Atualizar a docstring do módulo**

Em `scripts/comentarios_tocados.py`, a docstring hoje descreve **duas** categorias. Passam a ser cinco. Substitui o bloco que começa em "Duas categorias, e a segunda e a que pega o defeito da TEC-146:" por:

```
Cinco marcas. As duas primeiras sao sobre comentario dentro do codigo; as tres
ultimas, sobre a prosa versionada que descreve o codigo (TEC-282):

  ALTERADO  o comentario mudou nesta branch. Releia o codigo e confirme que ele
            ainda descreve o que esta ali.

  VIZINHO   o comentario NAO mudou, mas o codigo dentro do mesmo def/class
            mudou. E o caso perigoso: ninguem olha para o que nao aparece no
            diff, e e exatamente assim que um comentario passa a mentir. A
            saida padrao mostra so os VIZINHO mais proximos da alteracao em
            cada bloco e resume o resto numa linha, porque a listagem inteira
            costuma passar de 100 linhas e deixar de caber numa leitura.

  PROSA     um .md versionado cita `arquivo.py:linha` de um arquivo que esta
            branch mexeu. Suspeita, nao veredito: a ferramenta nao decide se a
            citacao ficou errada, so diz que precisa ser reconferida.

  FALSO     a citacao aponta alem do fim do arquivo. E a unica marca que
            afirma em vez de suspeitar, e por isso exige que o alvo resolva
            para um arquivo so.

  NOMEIA    a branch mexeu num arquivo sob `scripts/` e um documento nomeia
            aquele script -- o unico casamento por nome desta ferramenta.

Planos de implementacao (`docs/superpowers/plans/`) ficam fora da varredura de
prosa; a razao esta em PREFIXO_DOS_PLANOS.
```

- [ ] **Step 3: Atualizar o `CLAUDE.md`**

A seção "Comentário não mente" (linha 109) descreve hoje só `ALTERADO` e `VIZINHO`. Depois do parágrafo que começa com "`ALTERADO` é o que mudou no diff", acrescenta:

```markdown
**Desde a TEC-282 a listagem também aponta a prosa.** `PROSA` é um `.md` versionado que cita `arquivo.py:linha` de um arquivo que a branch mexeu — suspeita, não veredito. `FALSO` é a citação que aponta além do fim do arquivo, a única marca que afirma em vez de suspeitar. `NOMEIA` é o documento que nomeia um script que a branch alterou, e existe por um caso concreto: o merge da TEC-277 tornou este arquivo falso na mesma hora, e ninguém notou por horas, porque `CLAUDE.md` não é `.py`.

**Planos de implementação ficam de fora, de propósito.** Um plano registra o que se fez num dia; envelhecer é o esperado dele. Medido na TEC-282, incluí-los triplicaria o volume — a mediana por branch vai de 9 para 39 citações — sem apontar nada que ainda afirme algo sobre o código de hoje.
```

- [ ] **Step 4: Rodar tudo**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Expected: os três gates limpos e a suíte inteira verde. **Uma execução basta** — guarde o hash junto com o resultado. Se falhar, repita sobre a mesma árvore antes de culpar a mudança: é o que separa flake de regressão neste repo.

- [ ] **Step 5: Rodar a ferramenta de novo e conferir a própria prosa**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
```

Agora que o `CLAUDE.md` e a docstring mudaram, releia o que a listagem apontar. É a ferramenta pedindo o julgamento que ela existe para devolver a uma pessoa.

- [ ] **Step 6: Commit**

```bash
git add scripts/comentarios_tocados.py CLAUDE.md
git commit -m "docs(TEC-282): a prosa que descreve a ferramenta descreve as cinco marcas

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite da card

| cenário Gherkin | onde é exercitado |
| --- | --- |
| Citação de linha num arquivo que a branch mexeu | T3 `test_citacao_a_arquivo_alterado_e_prosa`, T6 `test_examinar_prosa_monta_as_tres_marcas`, T7 ponta a ponta |
| Citação que aponta além do fim do arquivo | T3 `test_faixa_alem_do_fim_do_arquivo_e_falso` e a fronteira em `test_a_ultima_linha_do_arquivo_ainda_e_prosa` |
| Mudança de ferramenta aponta a prosa que a descreve | T4 inteira, e T8 Step 1 contra esta própria branch |
| A prosa não estoura o orçamento de leitura | T5 inteira, `--tudo` em `test_teto_zero_desliga_o_corte_das_citacoes` |

**Fica sem teste automatizado:** o cenário "branch que toca um arquivo citado por dezenas de documentos" só é exercitado no seu componente (o teto, T5), não com dezenas de documentos reais. Montar essa fixture custaria mais que o que ela provaria, já que o teto é por documento e não global.

**Divergência em relação à card, decidida no desenho (D4):** `FALSO` só sai entre citações que apontam arquivo alterado, e não em toda execução. Vai no comentário da card.

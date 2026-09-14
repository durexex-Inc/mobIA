# TEC-277 — Afinar a listagem de comentários a reconferir antes do PR

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a saída padrão de `scripts/comentarios_tocados.py` caber numa leitura, sem perder nada, e dar teste à ferramenta que hoje não tem nenhum.

**Architecture:** Um teto de 5 `VIZINHO` por bloco, ranqueado por distância à linha alterada mais próxima, com o resto substituído por uma linha de resumo que nomeia o bloco e conta o que omitiu. `--tudo` desliga o teto e devolve a listagem de hoje. Nenhuma mudança no que é classificado como `ALTERADO` ou `VIZINHO` — só no que é impresso.

**Tech Stack:** Python 3.13 puro (`ast`, `tokenize`, `re`, `argparse`, `subprocess`), pytest. Sem banco, sem Docker, sem dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-277-afinar-a-listagem-de-comentarios-design.md`

## Global Constraints

- **Os três gates, nesta ordem, antes de qualquer commit.** O formatador é gate separado do linter; passar num não diz nada sobre o outro. O escopo inclui `scripts`, então este arquivo é alvo dos três.
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m mypy`
- **Comentários e docstrings em `src/`, `tests/` e `scripts/`: português SEM acento.** Não é checado por linter nenhum. O arquivo inteiro já segue isso — mantenha.
- **Comentário explica o PORQUÊ, não o quê.** Comentário desatualizado é defeito. Esta card mexe justamente na ferramenta que existe para isso, então o padrão vale em dobro: **ao mudar `_blocos` e `examinar`, as docstrings deles têm de mudar junto.**
- **Não cite número de linha de outro arquivo em comentário.** Cite por nome de função ou constante.
- Testes unitários rodam sem Docker e sem `-n`: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -q --tb=short`
- `pythonpath = ["."]` já está no `pyproject.toml`, e `scripts/` é importável como namespace package sem `__init__.py`. **Verificado:** `from scripts.comentarios_tocados import examinar` funciona. Não crie `scripts/__init__.py`.
- Commit: assunto em português sem acento, `tipo(TEC-277): o que passou a ser verdade`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **A ferramenta continua devolvendo `0` sempre.** Virar gate está fora de escopo, e o comentário ao fim de `main` que explica isso não se toca.

---

### Task 1: Dar teste à ferramenta, antes de mexer nela

**Files:**
- Create: `tests/unit/test_comentarios_tocados.py`
- Modify: nenhum

**Interfaces:**
- Consumes: `linhas_alteradas`, `_comentarios`, `_docstrings`, `_blocos`, `examinar`, `Achado` de `scripts.comentarios_tocados`, todos com as assinaturas de hoje.
- Produces: a rede que as Tasks 2 e 3 precisam para mudar o classificador sem voar às cegas.

**Por que esta task vem primeiro:** as Tasks 2 e 3 mudam `_blocos`, `examinar` e `main`. Sem teste, a única evidência de que a ferramenta ainda funciona seria rodá-la à mão e olhar. Estes testes travam o comportamento de HOJE; se um deles quebrar na Task 2 ou 3, a mudança alterou algo que não devia.

- [ ] **Step 1: Escrever os testes do comportamento atual**

Criar `tests/unit/test_comentarios_tocados.py`:

```python
"""A ferramenta que lista comentarios a reconferir, testada.

TEC-277. Pura: as partes que decidem o que e ALTERADO e o que e VIZINHO nao
tocam git nem disco -- recebem texto de diff, fonte e um conjunto de linhas.
Antes desta card o script nao tinha teste nenhum.
"""

import ast
import textwrap
from pathlib import Path

from scripts.comentarios_tocados import (
    Achado,
    _blocos,
    _comentarios,
    _docstrings,
    examinar,
)


def test_comentario_dentro_de_string_nao_e_comentario() -> None:
    """A razao de o script usar `tokenize` e nao regex, e nada provava isso.

    Um `#` dentro de string e texto, nao comentario. Com regex, este caso sai
    como comentario e a listagem passa a apontar linhas que nao existem.
    """
    fonte = textwrap.dedent('''
        url = "http://exemplo/#ancora"
        # este sim
    ''')
    achados = _comentarios(fonte)
    assert [texto for _, texto in achados] == ["# este sim"]


def test_docstring_de_modulo_classe_funcao_e_async() -> None:
    fonte = textwrap.dedent('''
        """do modulo"""


        class C:
            """da classe"""

            def m(self):
                """do metodo"""


        async def f():
            """da async"""
    ''')
    textos = [texto for _, _, texto in _docstrings(ast.parse(fonte))]
    assert textos == [
        '"""do modulo',
        '"""da classe',
        '"""do metodo',
        '"""da async',
    ]


def test_string_solta_no_corpo_nao_e_docstring() -> None:
    """So a PRIMEIRA expressao do corpo conta. Uma string no meio e valor."""
    fonte = textwrap.dedent('''
        def f():
            x = 1
            "isto nao e docstring"
    ''')
    assert _docstrings(ast.parse(fonte)) == []


def test_blocos_devolve_faixa_de_cada_def_e_class(tmp_path: Path) -> None:
    fonte = textwrap.dedent('''
        class C:
            def m(self):
                pass
    ''')
    faixas = _blocos(ast.parse(fonte))
    # A classe contem o metodo: as duas faixas se sobrepoem, e e por isso que
    # mexer no metodo marca os comentarios de todos os outros metodos da
    # classe. Lacuna medida na TEC-277: cortar isso renderia 0,036%.
    assert len(faixas) == 2


def _escrever(tmp_path: Path, fonte: str) -> Path:
    arquivo = tmp_path / "alvo.py"
    arquivo.write_text(textwrap.dedent(fonte), encoding="utf-8")
    return arquivo


def test_comentario_na_linha_alterada_e_alterado(tmp_path: Path) -> None:
    arquivo = _escrever(tmp_path, '''
        def f():
            # este comentario
            return 1
    ''')
    (achado,) = examinar(arquivo, {3})
    assert achado.alterado is True


def test_comentario_no_bloco_mexido_e_vizinho(tmp_path: Path) -> None:
    arquivo = _escrever(tmp_path, '''
        def f():
            # este comentario
            return 1
    ''')
    (achado,) = examinar(arquivo, {4})
    assert achado.alterado is False


def test_alterado_ganha_de_vizinho(tmp_path: Path) -> None:
    """Quando as duas condicoes valem, nao ha dupla contagem."""
    arquivo = _escrever(tmp_path, '''
        def f():
            # este comentario
            return 1
    ''')
    achados = examinar(arquivo, {3, 4})
    assert len(achados) == 1
    assert achados[0].alterado is True


def test_comentario_fora_de_bloco_nunca_e_vizinho(tmp_path: Path) -> None:
    """Lacuna L2 do desenho, travada em teste para nao sumir sem alguem notar.

    Comentario de nivel de modulo nao esta contido em def nem class, entao
    `dentro_de_bloco_mexido` nunca o alcanca. Se um dia isto passar a marcar,
    foi mudanca deliberada e este teste e o lugar de registra-la.
    """
    arquivo = _escrever(tmp_path, '''
        # comentario de modulo


        def f():
            return 1
    ''')
    assert examinar(arquivo, {5}) == []


def test_arquivo_que_nao_parseia_devolve_lista_vazia(tmp_path: Path) -> None:
    arquivo = tmp_path / "quebrado.py"
    arquivo.write_text("def (", encoding="utf-8")
    assert examinar(arquivo, {1}) == []
```

E os testes de `linhas_alteradas`. **Atenção:** `linhas_alteradas` chama git. Ela recebe `base` e roda `_rodar`. Para testá-la sem repositório, use `monkeypatch` sobre `_rodar` no módulo:

```python
import scripts.comentarios_tocados as ferramenta


def _com_diff(monkeypatch, saida: str) -> dict:
    monkeypatch.setattr(ferramenta, "_rodar", lambda *_: saida)
    return ferramenta.linhas_alteradas("qualquer")


def test_hunk_sem_virgula_conta_uma_linha(monkeypatch) -> None:
    resultado = _com_diff(monkeypatch, "+++ b/a.py\n@@ -1 +12 @@\n")
    assert resultado == {Path("a.py"): {12}}


def test_hunk_com_contagem_conta_todas(monkeypatch) -> None:
    resultado = _com_diff(monkeypatch, "+++ b/a.py\n@@ -1,3 +12,3 @@\n")
    assert resultado == {Path("a.py"): {12, 13, 14}}


def test_hunk_de_remocao_pura_nao_gera_linha(monkeypatch) -> None:
    """Lacuna L3 do desenho. Apagar o codigo que um comentario descrevia e
    deixar o comentario nao dispara ALTERADO -- so VIZINHO, e so se houver
    alguma linha adicionada no mesmo bloco. Travado para nao mudar por acaso."""
    resultado = _com_diff(monkeypatch, "+++ b/a.py\n@@ -1,3 +12,0 @@\n")
    assert resultado == {}


def test_arquivo_deletado_e_ignorado(monkeypatch) -> None:
    resultado = _com_diff(monkeypatch, "+++ /dev/null\n@@ -1,3 +0,0 @@\n")
    assert resultado == {}
```

- [ ] **Step 2: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -q --tb=short`
Expected: PASS, todos. **Estes testes descrevem o comportamento de hoje — se algum falhar agora, o teste está errado, não o script.** Conserte o teste e diga no relatório qual e por quê.

> Se `_docstrings` devolver os textos noutra ordem que a do teste, use a ordem real — `ast.walk` é BFS e a ordem depende da estrutura. Ajuste o teste ao que o código faz e registre no relatório.

- [ ] **Step 3: Rodar os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Step 4: Commitar**

```bash
git add tests/unit/test_comentarios_tocados.py
git commit -F- <<'MSG'
test(TEC-277): a ferramenta de comentarios passa a ter rede antes de mudar

Ela nao tinha teste nenhum, e as tasks seguintes mexem no classificador.
Estes travam o comportamento de hoje, incluindo duas lacunas declaradas:
comentario de modulo nunca e VIZINHO, e hunk so de remocao nao gera linha.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: A distância e o bloco dono de cada achado

**Files:**
- Modify: `scripts/comentarios_tocados.py` (`Achado`, `_blocos`, `examinar`)
- Test: `tests/unit/test_comentarios_tocados.py` (acrescenta)

**Interfaces:**
- Consumes: o que a Task 1 travou.
- Produces: `Achado` com dois campos novos — `distancia: int` e `bloco: str` (vazio para `ALTERADO` e para achado fora de bloco). `_blocos` passa a devolver `list[tuple[int, int, str]]`, com o nome do bloco. A Task 3 consome os dois.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/unit/test_comentarios_tocados.py`:

```python
def test_a_distancia_e_ate_a_linha_alterada_mais_proxima(tmp_path: Path) -> None:
    arquivo = _escrever(tmp_path, '''
        def f():
            # comentario
            a = 1
            b = 2
            c = 3
            return a
    ''')
    # alteradas: 6 e 7. O comentario esta na 3, entao a mais proxima e a 6.
    (achado,) = [a for a in examinar(arquivo, {6, 7}) if not a.alterado]
    assert achado.distancia == 3


def test_a_distancia_de_um_alterado_e_zero(tmp_path: Path) -> None:
    arquivo = _escrever(tmp_path, '''
        def f():
            # comentario
            return 1
    ''')
    (achado,) = examinar(arquivo, {3})
    assert achado.distancia == 0


def test_a_distancia_de_docstring_mede_da_faixa_inteira(tmp_path: Path) -> None:
    """A docstring ocupa varias linhas; a distancia sai da borda mais proxima,
    nao da primeira linha -- senao uma docstring longa parece longe de uma
    alteracao colada no fim dela."""
    arquivo = _escrever(tmp_path, '''
        def f():
            """linha um
            linha dois
            linha tres
            """
            return 1
    ''')
    (achado,) = [a for a in examinar(arquivo, {7}) if not a.alterado]
    assert achado.distancia == 1


def test_o_bloco_dono_e_o_menor_que_contem_o_achado(tmp_path: Path) -> None:
    """Para ATRIBUIR, e nao para classificar.

    O desenho mediu que usar o menor bloco para CLASSIFICAR rende 0,036% e nao
    vale. Mas para dizer "+K em qual funcao" o menor bloco e o unico nome util:
    dizer "+703 em C" quando o comentario esta em `C.m` nao ajuda ninguem.
    """
    arquivo = _escrever(tmp_path, '''
        class C:
            def m(self):
                # comentario
                return 1
    ''')
    (achado,) = [a for a in examinar(arquivo, {4}) if not a.alterado]
    assert achado.bloco == "m"


def test_alterado_nao_recebe_bloco(tmp_path: Path) -> None:
    """O teto nao morde ALTERADO, entao ele nao precisa de dono."""
    arquivo = _escrever(tmp_path, '''
        def f():
            # comentario
            return 1
    ''')
    (achado,) = examinar(arquivo, {3})
    assert achado.bloco == ""
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -q --tb=short -k "distancia or bloco"`
Expected: FAIL com `AttributeError: 'Achado' object has no attribute 'distancia'`.

- [ ] **Step 3: Implementar**

Em `scripts/comentarios_tocados.py`, trocar `Achado`:

```python
@dataclass(frozen=True)
class Achado:
    linha: int
    texto: str
    alterado: bool
    # Distancia em linhas ate a alteracao mais proxima do mesmo arquivo, e o
    # nome do menor bloco que contem este achado. Os dois existem para o teto
    # de `main`: `distancia` ordena quem fica, `bloco` agrupa e nomeia o que
    # foi omitido. Um ALTERADO tem distancia 0 e bloco vazio -- o teto nao o
    # alcanca, entao nao precisa de nenhum dos dois.
    distancia: int = 0
    bloco: str = ""
```

`_blocos` passa a carregar o nome, e a docstring muda junto:

```python
def _blocos(arvore: ast.AST) -> list[tuple[int, int, str]]:
    """Faixa de linhas e nome de cada def/class, para decidir o que e VIZINHO.

    O def e a unidade certa: e o escopo que um comentario costuma descrever.
    Usar o arquivo inteiro marcaria comentario nenhum como seguro, e usar so as
    linhas coladas perderia o comentario de topo de funcao, que e justamente o
    que envelhece quando o corpo dela muda.

    O nome nao entra na classificacao -- entra no teto de `main`, que precisa
    dizer em QUAL bloco ficaram os vizinhos que ele omitiu. Sem ele a linha de
    resumo seria "+703 vizinhos omitidos", que nao diz onde procurar.
    """
    faixas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            faixas.append((no.lineno, no.end_lineno or no.lineno, no.name))
    return faixas
```

E em `examinar`, acrescentar as duas funções auxiliares e usá-las. **A classificação não muda** — só o que se anexa ao `Achado`:

```python
def examinar(arquivo: Path, alteradas: set[int]) -> list[Achado]:
    try:
        fonte = arquivo.read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
    except (OSError, SyntaxError):
        return []

    blocos = [(i, f, n) for i, f, n in _blocos(arvore) if any(i <= x <= f for x in alteradas)]

    def dentro_de_bloco_mexido(inicio: int, fim: int) -> bool:
        return any(i <= inicio and fim <= f for i, f, _ in blocos)

    def distancia(inicio: int, fim: int) -> int:
        # Zero quando a alteracao cai DENTRO da faixa do achado. Para uma
        # docstring longa isso importa: medir sempre da primeira linha faria
        # uma alteracao colada no fim dela parecer distante.
        return min(
            0 if inicio <= n <= fim else min(abs(n - inicio), abs(n - fim)) for n in alteradas
        )

    def dono(inicio: int, fim: int) -> str:
        # O MENOR bloco que contem o achado. Usar o maior diria "+703 em C"
        # para um comentario que esta em `C.m`, e quem le nao saberia onde
        # procurar. Isto e atribuicao, nao classificacao: o desenho mediu que
        # trocar a classificacao para o menor bloco rende 0,036%.
        candidatos = [(f - i, n) for i, f, n in blocos if i <= inicio and fim <= f]
        return min(candidatos)[1] if candidatos else ""

    achados = []
    for linha, texto in _comentarios(fonte):
        if linha in alteradas:
            achados.append(Achado(linha, texto, alterado=True))
        elif dentro_de_bloco_mexido(linha, linha):
            achados.append(
                Achado(linha, texto, False, distancia(linha, linha), dono(linha, linha))
            )
    for inicio, fim, texto in _docstrings(arvore):
        if any(n in alteradas for n in range(inicio, fim + 1)):
            achados.append(Achado(inicio, texto, alterado=True))
        elif dentro_de_bloco_mexido(inicio, fim):
            achados.append(
                Achado(inicio, texto, False, distancia(inicio, fim), dono(inicio, fim))
            )
    return sorted(achados, key=lambda a: a.linha)
```

> `alteradas` nunca é vazio quando `examinar` é chamado — `linhas_alteradas` descarta arquivos com conjunto vazio. Se isso mudar, `min()` sobre vazio levanta. Não acrescente uma guarda especulativa; se quiser travar a premissa, faça um teste.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -q --tb=short`
Expected: PASS, os novos **e os da Task 1** — os da Task 1 provam que a classificação não mudou.

- [ ] **Step 5: Os três gates, e commitar**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -F- <<'MSG'
feat(TEC-277): cada achado passa a saber sua distancia e seu bloco dono

Nenhuma mudanca de classificacao -- os testes da task anterior provam isso.
Os dois campos existem para o teto: distancia ordena quem fica, bloco nomeia
onde ficou o que foi omitido. O dono e o MENOR bloco que contem o achado,
porque dizer "+703 em C" para um comentario que esta em C.m nao ajuda.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: O teto por bloco e a flag `--tudo`

**Files:**
- Modify: `scripts/comentarios_tocados.py` (constante nova, `main`, e a docstring do módulo)
- Test: `tests/unit/test_comentarios_tocados.py` (acrescenta)

**Interfaces:**
- Consumes: `Achado.distancia` e `Achado.bloco` da Task 2.
- Produces: `MAXIMO_DE_VIZINHOS_POR_BLOCO = 5` e `limitar(achados, *, teto) -> tuple[list[Achado], dict[str, int]]`, função pura que devolve o que fica e quantos ficaram de fora por bloco. Nada depende dela depois.

**Por que uma função pura e não um `if` dentro do laço de impressão:** `main` faz I/O e não é testável sem git. Pondo a decisão numa função pura, o teto ganha teste e `main` só imprime.

- [ ] **Step 1: Escrever os testes que falham**

```python
from scripts.comentarios_tocados import MAXIMO_DE_VIZINHOS_POR_BLOCO, limitar


def _vizinho(linha: int, distancia: int, bloco: str = "f") -> Achado:
    return Achado(linha, f"# {linha}", False, distancia, bloco)


def test_bloco_abaixo_do_teto_passa_inteiro() -> None:
    achados = [_vizinho(n, n) for n in range(1, MAXIMO_DE_VIZINHOS_POR_BLOCO + 1)]
    ficam, omitidos = limitar(achados, teto=MAXIMO_DE_VIZINHOS_POR_BLOCO)
    assert len(ficam) == MAXIMO_DE_VIZINHOS_POR_BLOCO
    assert omitidos == {}


def test_o_teto_guarda_os_mais_proximos() -> None:
    achados = [_vizinho(n, distancia=n) for n in range(1, 11)]
    ficam, omitidos = limitar(achados, teto=3)
    assert [a.distancia for a in ficam] == [1, 2, 3]
    assert omitidos == {"f": 7}


def test_o_teto_e_por_bloco_e_nao_global() -> None:
    achados = [_vizinho(n, n, "f") for n in range(1, 6)] + [
        _vizinho(n, n, "g") for n in range(1, 6)
    ]
    ficam, omitidos = limitar(achados, teto=2)
    assert len(ficam) == 4
    assert omitidos == {"f": 3, "g": 3}


def test_alterado_nao_e_limitado() -> None:
    """A obrigacao sobre ALTERADO e de outra natureza: e o comentario que voce
    mesmo acabou de tocar. O teto existe contra ruido de vizinhanca."""
    achados = [Achado(n, f"# {n}", True) for n in range(1, 21)]
    ficam, omitidos = limitar(achados, teto=3)
    assert len(ficam) == 20
    assert omitidos == {}


def test_o_que_fica_sai_em_ordem_de_linha() -> None:
    """Ordena por distancia para ESCOLHER, por linha para IMPRIMIR -- a saida
    tem de continuar navegavel de cima para baixo no arquivo."""
    achados = [_vizinho(10, 1), _vizinho(2, 2), _vizinho(30, 3)]
    ficam, _ = limitar(achados, teto=3)
    assert [a.linha for a in ficam] == [2, 10, 30]


def test_teto_zero_desliga_o_corte() -> None:
    """E como `--tudo` e implementado: um teto que nao morde."""
    achados = [_vizinho(n, n) for n in range(1, 51)]
    ficam, omitidos = limitar(achados, teto=0)
    assert len(ficam) == 50
    assert omitidos == {}
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -q --tb=short -k "teto or limitar or alterado_nao"`
Expected: FAIL na coleta — `ImportError: cannot import name 'MAXIMO_DE_VIZINHOS_POR_BLOCO'`.

- [ ] **Step 3: Implementar a constante e `limitar`**

No topo do módulo, junto de `_CABECALHO`:

```python
# O teto de VIZINHOS impressos por bloco na saida padrao.
#
# Medido na TEC-277 sobre 19 branches ja mergeadas (PRs #87 a #108): a saida
# tinha mediana de 890 linhas e maximo de 1928, e 16 das 19 passavam de 100.
# Com este teto a mediana cai para 188.
#
# **5 nao e um otimo, e o joelho de uma curva plana.** Medido para 3, 5, 10 e
# 20, a diferenca de itens omitidos entre 3 e 20 e de ~9%: o volume nao vem de
# poucos blocos com muitos achados, vem de MUITOS blocos batendo o teto. Como
# 3 e 5 custam quase o mesmo, 5 e o maior que nao paga nada a mais.
#
# O teto existe porque nao ha regra melhor, e isso foi medido, nao suposto:
# 75,9% do ruido sai de `executar_turno`, que tem 1877 linhas. Uma regra de
# vizinhanca por distancia deixaria 65,9% de pe num raio de 50 linhas, e
# "menor bloco que contem a linha alterada" rende 0,036%. Enquanto aquela
# funcao existir, esta saida vive de teto -- ver a L1 do desenho.
MAXIMO_DE_VIZINHOS_POR_BLOCO = 5
```

E a função pura, antes de `main`:

```python
def limitar(achados: list[Achado], *, teto: int) -> tuple[list[Achado], dict[str, int]]:
    """Os achados que ficam, e quantos ficaram de fora em cada bloco.

    `teto` de 0 desliga o corte: e assim que `--tudo` e implementado, sem um
    caminho separado que possa divergir do normal.

    ALTERADO nunca e cortado. A obrigacao sobre ele e de outra natureza -- e o
    comentario que quem abre o PR acabou de tocar --, e o teto existe contra
    ruido de vizinhanca. **Consequencia declarada:** numa branch que reescreve
    muito, e ALTERADO que domina o que resta (a TEC-153 tem 623 e a TEC-184,
    525), e a saida continua longa apesar do teto.

    Ordena por distancia para ESCOLHER e por linha para DEVOLVER: a escolha
    quer os mais perto da alteracao, a saida quer ser navegavel de cima para
    baixo no arquivo.
    """
    if teto <= 0:
        return achados, {}

    por_bloco: dict[str, list[Achado]] = {}
    ficam = [a for a in achados if a.alterado]
    for achado in achados:
        if not achado.alterado:
            por_bloco.setdefault(achado.bloco, []).append(achado)

    omitidos = {}
    for bloco, do_bloco in por_bloco.items():
        # `a.linha` desempata distancia igual, para a escolha ser estavel entre
        # execucoes em vez de depender da ordem de `ast.walk`.
        ordenados = sorted(do_bloco, key=lambda a: (a.distancia, a.linha))
        ficam.extend(ordenados[:teto])
        if sobrando := len(ordenados) - teto:
            omitidos[bloco] = sobrando

    return sorted(ficam, key=lambda a: a.linha), omitidos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -q --tb=short`
Expected: PASS, todos.

- [ ] **Step 5: Ligar em `main`, com `argparse`**

Trocar o começo de `main`:

```python
def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__, formatter_class=...)
    analisador.add_argument("base", nargs="?", default="origin/main")
    analisador.add_argument(
        "--tudo",
        action="store_true",
        help="imprime todos os vizinhos, sem o teto por bloco",
    )
    argumentos = analisador.parse_args()
    base = argumentos.base
    teto = 0 if argumentos.tudo else MAXIMO_DE_VIZINHOS_POR_BLOCO
```

**`nargs="?"` preserva a chamada de hoje** (`python scripts/comentarios_tocados.py main`), que é a única forma documentada na docstring do módulo. Acrescente `import argparse` no bloco de imports, em ordem alfabética (antes de `ast`).

> Escolha o `formatter_class` que preservar a docstring legível, ou simplesmente passe uma `description` curta própria em vez de `__doc__` — a docstring do módulo tem 29 linhas e o `argparse` a reflui por padrão. Decida e registre no relatório qual escolheu.

E o laço de impressão passa a limitar e a imprimir os resumos:

```python
    for arquivo in sorted(por_arquivo):
        achados = examinar(arquivo, por_arquivo[arquivo])
        if not achados:
            continue
        ficam, omitidos = limitar(achados, teto=teto)
        print(f"\n{arquivo}")
        for achado in ficam:
            marca = "ALTERADO" if achado.alterado else "VIZINHO "
            texto = achado.texto if len(achado.texto) <= 96 else achado.texto[:93] + "..."
            print(f"  {marca} {arquivo}:{achado.linha}  {texto}")
            if achado.alterado:
                alterados += 1
            else:
                vizinhos += 1
        for bloco, quantos in sorted(omitidos.items()):
            vizinhos += quantos
            print(f"  ... +{quantos} vizinho(s) em {bloco}, os mais distantes -- use --tudo")
```

**`vizinhos += quantos` não é detalhe:** a contagem final tem de contar o que existe, não o que coube na tela. Se ela contasse só os impressos, o resumo diria "12 vizinhos" numa branch com 715 — e a ferramenta passaria a mentir sobre si mesma, que é exatamente o defeito que ela existe para pegar.

- [ ] **Step 6: Atualizar a docstring do módulo**

A docstring lista os modos de uso (linhas ~25-29) e explica as duas categorias. Ela **não** menciona o teto nem `--tudo`, e depois desta task estaria incompleta. Acrescente:

- `--tudo` ao bloco de uso;
- uma frase, junto da descrição de `VIZINHO`, dizendo que a saída padrão mostra os mais próximos de cada bloco e resume o resto, e por quê.

Não reescreva o resto: a explicação da TEC-146 e do porquê de a ferramenta existir continua válida e é o melhor do arquivo.

- [ ] **Step 7: Verificar na prática, não só no teste**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main | tail -20
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main --tudo | wc -l
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main | wc -l
```

Expected: a segunda contagem maior que a terceira, e a saída padrão com pelo menos uma linha `... +N vizinho(s) em ...`. **Se as duas contagens forem iguais, o teto não está mordendo** — investigue antes de seguir.

> Esta branch é pequena, então pode não haver bloco acima do teto. Nesse caso, meça contra uma branch grande: `git stash` não é preciso — rode `./.venv/Scripts/python.exe scripts/comentarios_tocados.py <sha-da-merge-base-de-uma-branch-grande>` a partir de um `git worktree` naquele commit, como a medição do desenho fez. Registre no relatório qual comando usou e os dois números.

- [ ] **Step 8: Os três gates, e commitar**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -F- <<'MSG'
feat(TEC-277): a saida padrao cabe numa leitura, e --tudo devolve o resto

Teto de 5 vizinhos por bloco, ranqueado por distancia da alteracao mais
proxima, com uma linha de resumo que nomeia o bloco e conta o que omitiu.
Medido em 19 branches: a mediana da saida cai de 890 para 188 linhas.

Nada se perde -- --tudo imprime a listagem de antes, e a contagem final
continua contando o que existe e nao o que coube na tela. ALTERADO nao e
limitado: e o comentario que quem abre o PR acabou de tocar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: Fechamento

**Files:** o que a listagem apontar.

- [ ] **Step 1: Rodar a própria ferramenta sobre esta branch**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

É a primeira card em que a ferramenta se audita. Leia as duas categorias. Dois candidatos conhecidos, que devem ter sido tratados nas Tasks 2 e 3 — confirme que sim:

- a docstring de `_blocos`, cuja assinatura mudou;
- a docstring do módulo, que descrevia a saída sem teto.

- [ ] **Step 2: Rodar a suíte inteira, UMA vez**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short -q`
Expected: verde. Guarde o hash junto com o resultado.

> Esta card não toca `src/` nem migrations, então uma falha de integração aqui é ambiental quase por definição. `ConnectionResetError [WinError 64]` isolado não autoriza conclusão nenhuma; a segunda execução é diagnóstico, e só quando a primeira falha.

- [ ] **Step 3: Os três gates**

- [ ] **Step 4: Abrir o PR e comentar na card**

Mover para **Em análise**, não para Feito. O comentário precisa registrar, no mínimo:

- **Que a evidência nº 2 da card é falsa**, com a verificação: `handoff/models.py` e `handoff/resumo.py` estavam no diff da TEC-176 (merge `3ced517`). A ferramenta os viu; quem não os leu foi uma pessoa.
- **Que o cenário 2 do Gherkin não é entregue** (`D3`), e os três motivos medidos.
- **Que a regra de negócio "vizinhança por distância" foi medida e substituída por teto**, com os números — é divergência em relação ao texto da card.
- **Que `executar_turno`, com 1877 linhas, é 75,9% do problema e continua lá** (`L1`) — isso é decisão de produto/prioridade, não de código: enquanto ela existir, esta ferramenta vive de teto.
- Que `ALTERADO` não é limitado, e o que isso significa para branches que reescrevem muito.

## Cobertura dos critérios de aceite

| Cenário da card | Onde | Situação |
| --- | --- | --- |
| 1 — Função enorme com mudança pontual não marca o arquivo inteiro | Task 3, o teto | **Pelo efeito, não pela regra.** A card pede vizinhança por distância; medido, isso deixa 65,9% de pé num raio de 50. O teto entrega o efeito (os comentários longe deixam de ser impressos), por outro mecanismo. Divergência declarada |
| 2 — Mudança de contrato aponta para fora do diff | — | **Não entregue** (`D3`). A premissa do cenário é falsa e o mecanismo mede ~1 item/branch com 83,8% de homonímia |
| 3 — O volume cabe numa leitura | Task 3 | Coberto na mediana (890 → 188 linhas). **Não é garantia:** branches com muito `ALTERADO` continuam longas (`L5`) |
| 4 — A ferramenta continua não reprovando | Task 3 preserva o `return 0` e o comentário que o justifica | Coberto |

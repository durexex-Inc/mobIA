# TEC-299 — Citação por âncora, com gate no CI — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/comentarios_tocados.py` passa a verificar âncoras `arquivo.py::Nome` por `ast` e a reprovar citação nova por número de linha, com um `--checar` que vira passo no CI; as citações quebradas de hoje são corrigidas.

**Architecture:** Funções puras novas no próprio script (extração de âncora, nomes definidos por `ast`, linhas em bloco cercado, checagem por documento), no mesmo padrão das que já existem — recebem texto, não tocam disco nem git. `main` ganha `--checar` (saída 1 com ocorrência) e integra as duas marcas novas na listagem normal, que continua saindo com 0.

**Tech Stack:** Python 3.13 stdlib (`ast`, `re`), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-299-ancora-de-citacao-design.md`

## Global Constraints

- Comentários e docstrings em `scripts/` e `tests/`: português **sem** acento. Prosa em `docs/` e `CLAUDE.md`: **com** acento.
- **Nenhuma linha que esta branch acrescenta a um `.md` fora de `docs/superpowers/plans/` pode conter `nome.py:` seguido de dígito fora de bloco cercado** — é a regra que a própria branch implanta, e o `--checar` da Task 4 reprova a branch se ela a violar. Para falar de uma linha, escreva "a linha 1364 de `turno.py`".
- Comentário diz o porquê, não o quê. Comentário que a mudança torna falso muda junto (ver a lista na Task 3).
- Gates antes de todo commit: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Testes do script: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short` (sem Docker, sem `-n`).
- Commit: `tipo(TEC-299): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Atributo de instância citado como âncora** (`Classe.campo` definido só em `self.campo = ...` no `__init__`) — um leitor espera que isso resolva; `nomes_definidos` cobre `self.X` dentro de método (teste na Task 1).
2. **Âncora pontuada com cauda de nome de módulo** (`mobia.infra.crypto.py::x`) — não deve casar pela cauda, mesmo lookbehind de `_CITACAO` (teste na Task 1).
3. **Docs-only PR** — branch que só mexe em `.md` precisa ter `LINHA` e `ANCORA` verificadas; hoje `main` retorna cedo quando nenhum `.py` mudou (teste na Task 3).
4. **Mesma citação sai como `LINHA` e `PROSA`** quando está em linha acrescentada e aponta arquivo mexido — deve sair uma vez só, como `LINHA` (teste na Task 3).
5. **Bloco cercado não fechado** até o fim do documento — o resto do documento conta como cercado, como no CommonMark (teste na Task 2).

---

### Task 1: Âncoras e nomes definidos

**Files:**
- Modify: `scripts/comentarios_tocados.py` (constantes no topo, funções novas depois de `resolver`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Produces:
  - `_ANCORA: re.Pattern[str]`
  - `ancoras_do_texto(texto: str) -> list[tuple[int, str, str]]` — (linha do documento, alvo cru, nome pontuado)
  - `nomes_definidos(fonte: str) -> set[str] | None` — `None` quando não parseia
  - `ancora_quebrada(candidatos: list[str], nome: str, nomes_de: Callable[[str], set[str] | None]) -> bool`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao import de `tests/unit/test_comentarios_tocados.py`: `ancora_quebrada`, `ancoras_do_texto`, `nomes_definidos`. Acrescente no fim do arquivo:

```python
def test_ancora_reconhece_nome_simples_e_pontuado() -> None:
    texto = "ver `turno.py::executar` e `workers/main.py::WorkerSettings.job_timeout`\n"
    assert ancoras_do_texto(texto) == [
        (1, "turno.py", "executar"),
        (1, "workers/main.py", "WorkerSettings.job_timeout"),
    ]


def test_ancora_ignora_a_cauda_de_um_nome_pontuado() -> None:
    """Mesmo lookbehind de `_CITACAO`: `crypto.py` nao e caminho nenhum."""
    assert ancoras_do_texto("mobia.infra.crypto.py::cifrar") == []


def test_ancora_nao_e_citacao_por_linha() -> None:
    """As duas formas nao se confundem: `::nome` nao casa `_CITACAO`."""
    assert citacoes_do_texto("turno.py::executar") == []
    assert ancoras_do_texto("turno.py:12") == []


def test_ancora_informa_a_linha_do_documento() -> None:
    assert ancoras_do_texto("a\nb\nc turno.py::f\n") == [(3, "turno.py", "f")]


def test_nomes_definidos_cobre_def_class_e_aninhados() -> None:
    fonte = textwrap.dedent("""
        def f():
            def interna():
                pass
        async def g():
            pass
        class C:
            def m(self):
                pass
    """)
    assert nomes_definidos(fonte) == {"f", "f.interna", "g", "C", "C.m"}


def test_nomes_definidos_cobre_atribuicoes() -> None:
    fonte = textwrap.dedent("""
        TETO = 5
        LIMITE: int = 3
        a, (b, *c) = 1, (2, 3)
        class Settings:
            campo: str = "x"
            OUTRO = 1
    """)
    assert nomes_definidos(fonte) == {
        "TETO", "LIMITE", "a", "b", "c", "Settings", "Settings.campo", "Settings.OUTRO",
    }


def test_nomes_definidos_cobre_atributo_de_instancia() -> None:
    """`self.x = ...` num metodo define `Classe.x` -- e o que um leitor cita."""
    fonte = textwrap.dedent("""
        class C:
            def __init__(self):
                self.x = 1
                self.y: int = 2
                outro.z = 3
    """)
    assert nomes_definidos(fonte) == {"C", "C.__init__", "C.x", "C.y"}


def test_nomes_definidos_atravessa_bloco_sem_escopo() -> None:
    fonte = textwrap.dedent("""
        if TYPE_CHECKING:
            def so_tipo():
                pass
        try:
            A = 1
        except ImportError:
            B = 2
        else:
            C = 3
        finally:
            D = 4
        with abrir() as arq:
            E = 5
        for i in range(3):
            F = 6
        while False:
            G = 7
        match x:
            case 1:
                H = 8
    """)
    nomes = nomes_definidos(fonte)
    assert nomes is not None
    assert {"so_tipo", "A", "B", "C", "D", "E", "F", "G", "H"} <= nomes


def test_import_nao_define_nome() -> None:
    fonte = "from os import path\nimport sys\n"
    assert nomes_definidos(fonte) == set()


def test_fonte_que_nao_parseia_nao_tem_nomes() -> None:
    assert nomes_definidos("def (:\n") is None


def _nomes(tabela: dict[str, set[str] | None]) -> Callable[[str], set[str] | None]:
    return lambda caminho: tabela[caminho]


def test_ancora_com_nome_existente_nao_e_quebrada() -> None:
    assert not ancora_quebrada(["a/turno.py"], "f", _nomes({"a/turno.py": {"f"}}))


def test_ancora_com_nome_ausente_e_quebrada() -> None:
    assert ancora_quebrada(["a/turno.py"], "sumiu", _nomes({"a/turno.py": {"f"}}))


def test_ancora_ambigua_vale_se_algum_candidato_tem_o_nome() -> None:
    nomes = _nomes({"a/models.py": {"X"}, "b/models.py": {"Y"}})
    assert not ancora_quebrada(["a/models.py", "b/models.py"], "Y", nomes)


def test_ancora_ambigua_e_quebrada_se_nenhum_candidato_tem_o_nome() -> None:
    """A diferenca para a citacao por linha: aqui a ambiguidade nao impede a
    certeza, porque a conclusao vale para qualquer leitura da citacao."""
    nomes = _nomes({"a/models.py": {"X"}, "b/models.py": {"Y"}})
    assert ancora_quebrada(["a/models.py", "b/models.py"], "Z", nomes)


def test_ancora_sem_arquivo_nao_e_quebrada() -> None:
    """Alvo que nao resolve e ignorado, como a citacao por linha ja e."""
    assert not ancora_quebrada([], "f", _nomes({}))


def test_ancora_em_arquivo_que_nao_parseia_nao_e_quebrada() -> None:
    """Falha de leitura nao autoriza afirmar nada -- mesmo raciocinio de
    `tamanho_de` devolver `maxsize`."""
    nomes = _nomes({"a/x.py": None, "b/x.py": {"Y"}})
    assert not ancora_quebrada(["a/x.py", "b/x.py"], "Z", nomes)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short -q`
Expected: erro de coleta, `ImportError: cannot import name 'ancora_quebrada'`.

- [ ] **Step 3: Implementar**

Em `scripts/comentarios_tocados.py`, logo depois da definição de `_CITACAO`:

```python
# `arquivo.py::Nome` e `arquivo.py::Classe.metodo` -- a ancora nominal da
# TEC-299, na forma do node id do pytest, que o repo ja usava antes dela.
#
# Mesmo lookbehind de `_CITACAO`, pelo mesmo motivo: sem ele,
# `mobia.infra.crypto.py::x` casaria pela cauda `crypto.py`.
_ANCORA = re.compile(r"(?<![\w/.-])((?:[\w./-]+/)?[\w-]+\.py)::([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
```

Depois de `resolver`:

```python
def ancoras_do_texto(texto: str) -> list[tuple[int, str, str]]:
    """Cada ancora como (linha do documento, alvo cru, nome pontuado)."""
    achados = []
    for numero, linha in enumerate(texto.splitlines(), 1):
        for casa in _ANCORA.finditer(linha):
            achados.append((numero, casa.group(1), casa.group(2)))
    return achados


def _nomes_do_alvo(alvo: ast.expr, prefixo: str, classe: str, nomes: set[str]) -> None:
    if isinstance(alvo, ast.Name):
        nomes.add(prefixo + alvo.id)
    elif isinstance(alvo, ast.Tuple | ast.List):
        for elemento in alvo.elts:
            _nomes_do_alvo(elemento, prefixo, classe, nomes)
    elif isinstance(alvo, ast.Starred):
        _nomes_do_alvo(alvo.value, prefixo, classe, nomes)
    elif (
        classe
        and isinstance(alvo, ast.Attribute)
        and isinstance(alvo.value, ast.Name)
        and alvo.value.id == "self"
    ):
        nomes.add(f"{classe}.{alvo.attr}")


def nomes_definidos(fonte: str) -> set[str] | None:
    """Todo nome que uma ancora pode designar neste arquivo, pontuado.

    Definicao, e nao mencao: `def`, `class`, alvo de atribuicao, e o
    `self.x` atribuido num metodo, que define `Classe.x` para quem le.
    Import nao entra -- citar `mod.py::y` para um `y` so importado aponta o
    lugar errado. Blocos que nao abrem escopo (`if`, `try`, `with`, laco,
    `match`) sao atravessados com o mesmo prefixo, porque um `def` dentro de
    `if TYPE_CHECKING:` continua sendo `modulo::nome`.

    `None` quando a fonte nao parseia: quem chama trata como "nao
    verificavel", nunca como "nome ausente".
    """
    try:
        arvore = ast.parse(fonte)
    except (SyntaxError, ValueError):
        return None
    nomes: set[str] = set()

    def visitar(corpo: list[ast.stmt], prefixo: str, classe: str) -> None:
        for no in corpo:
            if isinstance(no, ast.ClassDef):
                nome = prefixo + no.name
                nomes.add(nome)
                visitar(no.body, nome + ".", nome)
            elif isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
                nome = prefixo + no.name
                nomes.add(nome)
                # A classe dona passa adiante para `self.x` virar `Classe.x`;
                # uma funcao solta nao tem `self` que valha.
                visitar(no.body, nome + ".", classe if prefixo == classe + "." else "")
            elif isinstance(no, ast.Assign):
                for alvo in no.targets:
                    _nomes_do_alvo(alvo, prefixo, classe, nomes)
            elif isinstance(no, ast.AnnAssign):
                _nomes_do_alvo(no.target, prefixo, classe, nomes)
            elif isinstance(no, ast.TypeAlias):
                nomes.add(prefixo + no.name.id)
            elif isinstance(no, ast.Match):
                for caso in no.cases:
                    visitar(caso.body, prefixo, classe)
            elif isinstance(
                no,
                ast.If | ast.Try | ast.TryStar | ast.With | ast.AsyncWith
                | ast.For | ast.AsyncFor | ast.While,
            ):
                for campo in ("body", "orelse", "finalbody"):
                    visitar(getattr(no, campo, []), prefixo, classe)
                for tratador in getattr(no, "handlers", []):
                    visitar(tratador.body, prefixo, classe)

    visitar(arvore.body, "", "")
    return nomes


def ancora_quebrada(
    candidatos: list[str],
    nome: str,
    nomes_de: Callable[[str], set[str] | None],
) -> bool:
    """Se esta ancora e comprovadamente falsa.

    Ao contrario da citacao por linha, a ambiguidade de arquivo NAO impede a
    certeza: se o nome nao existe em nenhum candidato, a ancora e falsa em
    qualquer leitura dela. Basta um candidato que nao parseia para a resposta
    ser "nao sei" -- e "nao sei" aqui e False, porque esta marca reprova.

    Alvo sem candidato nenhum e False tambem: e o caminho de fora do repo, ou
    o arquivo apagado da cegueira da TEC-284, que continua aberta.
    """
    if not candidatos:
        return False
    return all((nomes := nomes_de(c)) is not None and nome not in nomes for c in candidatos)
```

Nota para quem implementa: `classe if prefixo == classe + "." else ""` faz um método (definido diretamente no corpo da classe) herdar a classe, e uma função aninhada dentro de método perder — `self` dentro dela não é garantido. Se o `ruff format` quebrar a tupla do `isinstance` de outro jeito, aceite o formato dele.

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short -q`
Expected: todos passam.

- [ ] **Step 5: Gates e commit**

Rode os três gates da seção Global Constraints. Depois:

```bash
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-299): a ferramenta sabe dizer se uma ancora arquivo.py::Nome existe

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Bloco cercado, linhas acrescentadas e a checagem por documento

**Files:**
- Modify: `scripts/comentarios_tocados.py`
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: `ancoras_do_texto`, `ancora_quebrada` (Task 1); `citacoes_do_texto`, `resolver`, `Citacao`, `_rodar` (existentes)
- Produces:
  - `linhas_cercadas(texto: str) -> set[int]`
  - `_linhas_do_diff(saida: str) -> dict[str, set[int]]` (extraída de `linhas_alteradas`, que passa a usá-la)
  - `linhas_adicionadas_em_documentos(base: str) -> dict[str, set[int]]`
  - `checar_documento(documento: str, texto: str, adicionadas: set[int], arquivos_py: set[str], nomes_de: Callable[[str], set[str] | None]) -> list[Citacao]` — marcas `"ANCORA"` e `"LINHA"`; `Citacao.texto` é `f"{alvo}::{nome}"` para ANCORA e `f"{alvo}:{citada}"` (mesmo formato de PROSA) para LINHA

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao import: `checar_documento`, `linhas_cercadas`. No fim do arquivo:

```python
def test_linhas_cercadas_com_crases_e_tis() -> None:
    texto = "a\n```bash\nb\n```\nc\n~~~\nd\n~~~\ne\n"
    assert linhas_cercadas(texto) == {2, 3, 4, 6, 7, 8}


def test_cerca_so_fecha_com_o_mesmo_caractere() -> None:
    texto = "```\na\n~~~\nb\n```\nc\n"
    assert linhas_cercadas(texto) == {1, 2, 3, 4, 5}


def test_cerca_nao_fechada_vai_ate_o_fim() -> None:
    """Como no CommonMark: o resto do documento e codigo."""
    assert linhas_cercadas("a\n```\nb\nc\n") == {2, 3, 4}


def test_cerca_com_info_string_nao_fecha() -> None:
    assert linhas_cercadas("```\na\n```python\nb\n```\n") == {1, 2, 3, 4, 5}


def test_linhas_adicionadas_em_documentos(monkeypatch) -> None:
    saida = "+++ b/CLAUDE.md\n@@ -1 +3,2 @@\n+++ b/docs/x.md\n@@ -4 +9 @@\n"
    monkeypatch.setattr(ferramenta, "_rodar", lambda *_: saida)
    assert ferramenta.linhas_adicionadas_em_documentos("qualquer") == {
        "CLAUDE.md": {3, 4},
        "docs/x.md": {9},
    }


def _nomes_fixos(caminho: str) -> set[str] | None:
    return {"a/turno.py": {"existe"}}.get(caminho)


def test_checar_documento_marca_ancora_quebrada() -> None:
    texto = "ok `turno.py::existe`\nruim `turno.py::sumiu`\n"
    achados = checar_documento("d.md", texto, set(), {"a/turno.py"}, _nomes_fixos)
    assert [(c.linha, c.texto, c.marca) for c in achados] == [(2, "turno.py::sumiu", "ANCORA")]


def test_checar_documento_verifica_ancora_dentro_de_cerca() -> None:
    """A isencao de bloco cercado e so de LINHA: ancora quebrada e falsa em
    qualquer contexto."""
    texto = "```\nturno.py::sumiu\n```\n"
    achados = checar_documento("d.md", texto, set(), {"a/turno.py"}, _nomes_fixos)
    assert [c.marca for c in achados] == ["ANCORA"]


def test_checar_documento_marca_linha_so_em_linha_acrescentada() -> None:
    texto = "antiga turno.py:10\nnova turno.py:20-30\n"
    achados = checar_documento("d.md", texto, {2}, {"a/turno.py"}, _nomes_fixos)
    assert [(c.linha, c.texto, c.marca) for c in achados] == [(2, "turno.py:20-30", "LINHA")]


def test_checar_documento_isenta_linha_acrescentada_dentro_de_cerca() -> None:
    """Traceback e saida de pytest vivem em bloco cercado: sao citacao de
    saida, nao afirmacao sobre o codigo."""
    texto = "```\ntests/x.py:123: AssertionError\n```\n"
    assert checar_documento("d.md", texto, {1, 2, 3}, set(), _nomes_fixos) == []


def test_checar_documento_marca_linha_mesmo_sem_resolver() -> None:
    """LINHA e sobre a forma da citacao, nao sobre o alvo."""
    achados = checar_documento("d.md", "fora.py:3\n", {1}, set(), _nomes_fixos)
    assert [c.marca for c in achados] == ["LINHA"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short -q`
Expected: `ImportError: cannot import name 'checar_documento'`.

- [ ] **Step 3: Implementar**

Troque o corpo de `linhas_alteradas` por uma função auxiliar compartilhada — o comportamento de `linhas_alteradas` não muda (os testes `test_hunk_*` e `test_arquivo_deletado_e_ignorado` continuam valendo):

```python
def _linhas_do_diff(saida: str) -> dict[str, set[int]]:
    """Por arquivo, as linhas que um `git diff --unified=0` acrescentou.

    Compartilhada entre o diff de `.py` e o de `.md`: as duas leituras tem de
    concordar sobre o que e linha acrescentada, e dois parsers divergiriam.
    """
    por_arquivo: dict[str, set[int]] = {}
    atual: set[int] | None = None
    for linha in saida.splitlines():
        if linha.startswith("+++ b/"):
            atual = por_arquivo.setdefault(linha[6:], set())
        elif linha.startswith("+++ /dev/null"):
            atual = None
        elif atual is not None and (casa := _CABECALHO.match(linha)):
            inicio = int(casa.group(1))
            # Grupo 2 ausente significa uma linha so; `,0` significa remocao
            # pura, que nao deixa linha nova para reconferir.
            quantas = int(casa.group(2)) if casa.group(2) is not None else 1
            atual.update(range(inicio, inicio + quantas))
    return {arquivo: linhas for arquivo, linhas in por_arquivo.items() if linhas}


def linhas_alteradas(base: str) -> dict[Path, set[int]]:
    """<docstring atual, inalterada>"""
    saida = _rodar("diff", "--unified=0", f"{base}...HEAD", "--", "*.py")
    return {Path(arquivo): linhas for arquivo, linhas in _linhas_do_diff(saida).items()}


def linhas_adicionadas_em_documentos(base: str) -> dict[str, set[int]]:
    """Por .md, as linhas que esta branch acrescentou -- o alcance de LINHA.

    Chave em texto com barra normal, como o git devolve e como
    `_documentos_no_escopo` lista: as duas se cruzam por igualdade.
    """
    return _linhas_do_diff(_rodar("diff", "--unified=0", f"{base}...HEAD", "--", "*.md"))
```

Depois de `ancora_quebrada`:

```python
# Abertura ou fechamento de bloco cercado: ate tres espacos, e tres ou mais
# crases ou tis.
_CERCA = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def linhas_cercadas(texto: str) -> set[int]:
    """As linhas do documento que estao dentro de bloco cercado, cercas inclusas.

    Regra do CommonMark, no que importa aqui: fecha com o mesmo caractere, com
    pelo menos o mesmo comprimento e sem nada depois; bloco nao fechado vai ate
    o fim do documento.
    """
    dentro: set[int] = set()
    aberta = ""
    for numero, linha in enumerate(texto.splitlines(), 1):
        casa = _CERCA.match(linha)
        if not aberta:
            if casa:
                aberta = casa.group(1)
                dentro.add(numero)
            continue
        dentro.add(numero)
        if (
            casa
            and casa.group(1)[0] == aberta[0]
            and len(casa.group(1)) >= len(aberta)
            and not casa.group(2).strip()
        ):
            aberta = ""
    return dentro


def checar_documento(
    documento: str,
    texto: str,
    adicionadas: set[int],
    arquivos_py: set[str],
    nomes_de: Callable[[str], set[str] | None],
) -> list[Citacao]:
    """As duas marcas que reprovam: ANCORA e LINHA.

    ANCORA vale para o documento inteiro, e nao so para arquivos que a branch
    mexeu -- o invariante e "toda ancora resolve", e ele so se sustenta se for
    verificado sempre. LINHA vale so para linha que a branch acrescentou, fora
    de bloco cercado: e assim que a citacao antiga fica onde esta ate alguem
    editar a linha dela, e ai a conversao e obrigatoria.

    Puro de proposito, como `examinar_prosa`.
    """
    achados = []
    for linha, alvo, nome in ancoras_do_texto(texto):
        if ancora_quebrada(resolver(alvo, arquivos_py), nome, nomes_de):
            achados.append(Citacao(documento, linha, f"{alvo}::{nome}", "ANCORA"))
    if adicionadas:
        cercadas = linhas_cercadas(texto)
        for linha, alvo, inicio, fim in citacoes_do_texto(texto):
            if linha in adicionadas and linha not in cercadas:
                citada = f"{inicio}-{fim}" if inicio != fim else f"{inicio}"
                achados.append(Citacao(documento, linha, f"{alvo}:{citada}", "LINHA"))
    return sorted(achados, key=lambda c: c.linha)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short -q`
Expected: todos passam, inclusive os `test_hunk_*` antigos.

- [ ] **Step 5: Gates e commit**

```bash
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-299): ancora quebrada e citacao nova por linha viram achado por documento

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `--checar`, as marcas na listagem, e a prosa do script que fica falsa

**Files:**
- Modify: `scripts/comentarios_tocados.py` (`main`, docstring do módulo, `Citacao`, `classificar`, `examinar_prosa`, `limitar_citacoes`)
- Test: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consumes: `checar_documento`, `linhas_adicionadas_em_documentos`, `nomes_definidos` (Tasks 1-2)
- Produces: CLI `comentarios_tocados.py [base] --checar` → código de saída 1 com ocorrência, 0 sem. É o comando que a Task 5 põe no CI.

- [ ] **Step 1: Escrever os testes que falham**

```python
def _git_falso(md_diff: str) -> Callable[..., str]:
    def _git(*argumentos: str) -> str:
        if argumentos[0] == "diff":
            return md_diff if argumentos[-1] == "*.md" else ""
        if argumentos[:2] == ("ls-files", "*.md"):
            return "CLAUDE.md\n"
        if argumentos[:2] == ("ls-files", "*.py"):
            return "turno.py\n"
        return ""

    return _git


def test_checar_reprova_ancora_quebrada_e_linha_nova(monkeypatch, capsys, tmp_path) -> None:
    (tmp_path / "turno.py").write_text("def existe():\n    pass\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(
        "ver turno.py::sumiu\nveja turno.py:1\nantiga turno.py:2\nok turno.py::existe\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ferramenta, "_rodar", _git_falso("+++ b/CLAUDE.md\n@@ -1 +2 @@\n"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py", "--checar"])

    assert ferramenta.main() == 1
    saida = capsys.readouterr().out
    # O formato exato da linha do achado: o rodape tambem nomeia as marcas, e
    # `"ANCORA" in saida` passaria sem achado nenhum.
    assert "ANCORA CLAUDE.md:1  turno.py::sumiu" in saida
    assert "LINHA  CLAUDE.md:2  turno.py:1" in saida
    assert "CLAUDE.md:3" not in saida
    assert "turno.py::existe" not in saida


def test_checar_passa_sem_ocorrencia(monkeypatch, capsys, tmp_path) -> None:
    (tmp_path / "turno.py").write_text("def existe():\n    pass\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("antiga turno.py:2\nok turno.py::existe\n", encoding="utf-8")
    monkeypatch.setattr(ferramenta, "_rodar", _git_falso(""))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py", "--checar"])

    assert ferramenta.main() == 0


def test_listagem_mostra_linha_mesmo_sem_py_alterado(monkeypatch, capsys, tmp_path) -> None:
    """PR so de documentacao: sem isto, `main` retornava antes da prosa."""
    (tmp_path / "turno.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("nova turno.py:1\n", encoding="utf-8")
    monkeypatch.setattr(ferramenta, "_rodar", _git_falso("+++ b/CLAUDE.md\n@@ -0,0 +1 @@\n"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["comentarios_tocados.py"])

    assert ferramenta.main() == 0
    saida = capsys.readouterr().out
    assert "  LINHA  :1  turno.py:1" in saida


def test_linha_nova_a_arquivo_mexido_sai_uma_vez_como_linha(monkeypatch, capsys, tmp_path) -> None:
    """A mesma citacao seria PROSA (arquivo mexido) e LINHA (linha nova); a
    marca que reprova e a que fica."""
    (tmp_path / "turno.py").write_text("x = 1\n" * 50, encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("nova turno.py:10\n", encoding="utf-8")

    def _git(*argumentos: str) -> str:
        if argumentos[0] == "diff":
            if argumentos[-1] == "*.md":
                return "+++ b/CLAUDE.md\n@@ -0,0 +1 @@\n"
            return "+++ b/turno.py\n@@ -1 +5 @@\n"
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
    assert saida.count("turno.py:10") == 1
    assert "  LINHA  :1" in saida and "  PROSA  :1" not in saida


def test_ancora_e_linha_escapam_do_teto() -> None:
    citacoes = [Citacao("d.md", n, f"t.py:{n}", "PROSA") for n in range(1, 10)]
    citacoes += [
        Citacao("d.md", 20, "t.py::x", "ANCORA"),
        Citacao("d.md", 21, "t.py:3", "LINHA"),
    ]
    ficam, omitidas = limitar_citacoes(citacoes, teto=2)
    assert {c.marca for c in ficam} == {"PROSA", "ANCORA", "LINHA"}
    assert omitidas == 7
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short -q`
Expected: os de `--checar` falham com `SystemExit: 2` (argparse não conhece a flag); `test_listagem_mostra_linha_mesmo_sem_py_alterado` falha no assert de `LINHA`. `test_ancora_e_linha_escapam_do_teto` já passa (a regra "só PROSA é cortada" já cobre) — fica como trava.

- [ ] **Step 3: Implementar em `main`**

1. Novo argumento, depois de `--tudo`:

```python
    analisador.add_argument(
        "--checar",
        action="store_true",
        help="so ANCORA e LINHA, e sai com 1 se houver alguma -- o passo do CI",
    )
```

2. Uma fábrica memorizada de nomes, função de módulo antes de `main`:

```python
def _nomes_por_arquivo() -> Callable[[str], set[str] | None]:
    """`nomes_definidos` de cada arquivo, lido uma vez so.

    Arquivo ilegivel vira None, "nao verificavel" -- nunca conjunto vazio,
    que faria toda ancora para ele sair como ANCORA.
    """
    memoria: dict[str, set[str] | None] = {}

    def nomes_de(caminho: str) -> set[str] | None:
        if caminho not in memoria:
            try:
                memoria[caminho] = nomes_definidos(Path(caminho).read_text(encoding="utf-8"))
            except OSError:
                memoria[caminho] = None
        return memoria[caminho]

    return nomes_de


def _checar(
    arquivos_py: set[str],
    adicionadas: dict[str, set[int]],
    nomes_de: Callable[[str], set[str] | None],
) -> int:
    """O modo do CI: so as duas marcas mecanicas, e o codigo de saida."""
    ocorrencias = 0
    for documento in _documentos_no_escopo():
        try:
            texto = Path(documento).read_text(encoding="utf-8")
        except OSError:
            continue
        achados = checar_documento(
            documento, texto, adicionadas.get(documento, set()), arquivos_py, nomes_de
        )
        for citacao in achados:
            print(f"{citacao.marca:<6} {documento}:{citacao.linha}  {citacao.texto}")
        ocorrencias += len(achados)
    if not ocorrencias:
        print("Nenhuma ancora quebrada e nenhuma citacao nova por numero de linha.")
        return 0
    print(
        f"\n{ocorrencias} citacao(oes) a corrigir.\n"
        "ANCORA: o nome citado nao existe mais no arquivo -- ache o novo nome e troque.\n"
        "LINHA: citacao por numero de linha em linha que esta branch acrescentou -- "
        "cite `arquivo.py::Nome` (ver 'Comentario nao mente' no CLAUDE.md)."
    )
    return 1
```

3. Em `main`, logo depois de `base = argumentos.base`:

```python
    arquivos_py = _arquivos_versionados()
    nomes_de = _nomes_por_arquivo()
    adicionadas = linhas_adicionadas_em_documentos(base)
    if argumentos.checar:
        return _checar(arquivos_py, adicionadas, nomes_de)
```

e apague a linha `arquivos_py = _arquivos_versionados()` que existia mais abaixo.

4. O retorno cedo deixa de retornar — um PR só de documentação precisa chegar à seção de prosa:

```python
    if not por_arquivo:
        print(f"Nenhum arquivo .py commitado mudou em relacao a {base}.")
```

(sem o `return 0`; o laço de código seguinte simplesmente não itera).

5. No laço de documentos, troque o bloco `citacoes = examinar_prosa(...)` / `if not citacoes: continue` por:

```python
        citacoes = examinar_prosa(
            documento,
            texto,
            arquivos_py,
            alterados_como_texto,
            scripts_alterados,
            tamanho_de,
        )
        certas = checar_documento(
            documento, texto, adicionadas.get(documento, set()), arquivos_py, nomes_de
        )
        # A mesma citacao numa linha nova a arquivo mexido seria PROSA e LINHA;
        # fica a que reprova, para o revisor nao ler o mesmo ponto duas vezes.
        repetidas = {(c.linha, c.texto) for c in certas if c.marca == "LINHA"}
        citacoes = [c for c in citacoes if (c.linha, c.texto) not in repetidas] + certas
        if not citacoes:
            continue
```

6. Contagem e impressão: inicialize `em_prosa = falsas = a_corrigir = 0`. No `for citacao in ficam_citacoes`, a impressão não muda (ANCORA/LINHA saem com `extra` vazio, porque `destino` é vazio). A contagem vira:

```python
            if citacao.marca == "FALSO":
                falsas += 1
            elif citacao.marca in ("ANCORA", "LINHA"):
                a_corrigir += 1
            else:
                em_prosa += 1
```

7. Rodapé:

```python
    if not alterados and not vizinhos and not em_prosa and not falsas and not a_corrigir:
        print(f"Nenhum comentario, docstring ou prosa a reconferir em relacao a {base}.")
        return 0

    resumo = f"\n{alterados} alterado(s) nesta branch, {vizinhos} vizinho(s) de codigo que mudou"
    if em_prosa or falsas:
        resumo += f", {em_prosa + falsas} em prosa ({falsas} comprovadamente falsa(s))"
    if a_corrigir:
        resumo += f", {a_corrigir} a corrigir (ANCORA/LINHA, reprovam no CI)"
    print(
        f"{resumo}.\n"
        "VIZINHO e o que nao aparece no diff: confira se ainda descreve o codigo.\n"
        "PROSA e suspeita e FALSO e certeza: entre as citacoes por linha a arquivo que a "
        "branch mexeu, FALSO e a que aponta alem do fim dele.\n"
        "NOMEIA e o documento que nomeia um script que a branch alterou.\n"
        "ANCORA e LINHA reprovam no CI (--checar): ancora cujo nome nao existe, e "
        "citacao por numero de linha em linha que a branch acrescentou."
    )
```

8. O comentário do `return 0` final passa a dizer: "Sempre 0 na listagem: ela informa. Quem reprova e `--checar`, e so pelas duas marcas que nao pedem julgamento -- ver a docstring do modulo."

- [ ] **Step 4: Corrigir a prosa que esta task torna falsa**

`FALSO` deixa de ser "a única marca que afirma em vez de suspeitar" — `ANCORA` e `LINHA` também afirmam. Em cada sítio abaixo, reescreva só o bastante para a frase voltar a ser verdadeira (a forma sugerida é "a única das marcas por número de linha que afirma"):

- docstring do módulo, bloco de `FALSO` ("E a unica marca que afirma em vez de suspeitar")
- comentário de `Citacao` ("a evidencia da unica marca que afirma")
- docstring de `classificar` ("porque e a unica marca que AFIRMA algo")
- comentário em `examinar_prosa` ("So FALSO ganha a contagem: e a evidencia da unica marca")
- comentário de `tamanho_de` em `main` ("a unica marca que afirma em vez de suspeitar")
- comentário da impressão de `FALSO` em `main` ("A evidencia da unica marca que afirma")
- `tests/unit/test_comentarios_tocados.py`: docstring do módulo ("as cinco marcas"; acrescente TEC-299 e as duas marcas novas), e as docstrings de `test_faixa_alem_do_fim_do_arquivo_e_falso` e `test_examinar_prosa_preenche_linhas_do_arquivo_so_para_falso`

E na docstring do módulo do script:

- "Cinco marcas." vira "Sete marcas.", com as duas novas depois de `NOMEIA`:

```
  ANCORA    um .md cita `arquivo.py::Nome` e o nome nao existe no arquivo
            (TEC-299). Vale para o repo inteiro, nao so para arquivos que a
            branch mexeu, e reprova em --checar.

  LINHA     uma linha que a branch acrescentou a um .md cita `arquivo.py`
            seguido de numero de linha, fora de bloco cercado (TEC-299).
            Reprova em --checar: citacao nova se faz por ancora.
```

- O segundo parágrafo ("Este script nao vira gate tambem: ele nao valida nada e nao reprova nada") vira: a listagem continua sem reprovar nada, porque decidir se um comentário está certo é julgamento de pessoa; `--checar` reprova, e só por `ANCORA` e `LINHA`, que não pedem julgamento — um nome existe ou não no `ast`, uma linha acrescentada tem o padrão ou não.
- No bloco de uso, acrescente `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar`.
- Docstring de `limitar_citacoes`: "So `PROSA` e cortada. `FALSO` e `NOMEIA` escapam" passa a nomear também `ANCORA` e `LINHA`.

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short -q`
Expected: todos passam, inclusive `test_main_imprime_a_secao_de_prosa` e `test_main_continua_devolvendo_zero_com_prosa_falsa`.

- [ ] **Step 6: Gates e commit**

```bash
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-299): --checar reprova ancora quebrada e citacao nova por linha

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Consertar as citações quebradas de hoje

**Files:**
- Modify: `docs/superpowers/specs/2026-08-24-tec-126-telemetria-mensagens-design.md` (tabela de testes)
- Modify: `docs/superpowers/specs/2026-09-20-tec-222-last-error-so-com-o-nome-da-excecao-design.md` (o parágrafo "O caminho até a coluna é direto…")
- Modify: `docs/superpowers/specs/2026-09-21-tec-295-moderacao-na-rajada-design.md` (o parágrafo "**Isto é mais barato do que parece…**")
- Modify: `docs/superpowers/specs/2026-09-22-tec-130-encerrar-por-inatividade-design.md` (o item "**Há um único motivo e um único escritor.**")

- [ ] **Step 1: Medir o antes**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar`
Expected: saída 1, com **exatamente quatro** `ANCORA`, todas no desenho da TEC-126 (os nomes `test_entrada_persiste_com_papel_e_tipo`, `test_resposta_do_agente_traz_custo`, `test_telefone_sai_mascarado`, `test_falha_de_telemetria_preserva_a_mensagem`) e nenhum `LINHA`. Qualquer outra coisa é defeito das Tasks 1-3 — pare e investigue antes de seguir.

- [ ] **Step 2: TEC-126**

Na tabela `| Cenário Gherkin | Teste |`, troque os quatro testes, na ordem, por:

```
`tests/features/test_telemetria_de_mensagens.py::test_registrar_mensagem_de_entrada_do_lead`
`tests/features/test_telemetria_de_mensagens.py::test_registrar_resposta_do_agente_com_custo`
`tests/features/test_telemetria_de_mensagens.py::test_conteudo_pessoal_nao_vaza_para_o_log`
`tests/features/test_telemetria_de_mensagens.py::test_falha_de_telemetria_nao_derruba_o_atendimento`
```

- [ ] **Step 3: TEC-222**

No parágrafo que começa "O caminho até a coluna é direto", substitua a citação por linha pela âncora, mantendo a frase citada, que é o que localiza dentro de `_executar_turno`. O parágrafo inteiro fica:

```
O caminho até a coluna é direto e está declarado por escrito no código. Na moderação de **saída** não há falha aberta, de propósito (`turno.py::_executar_turno`, no comentário que abre a moderação de saída: *"A excecao propaga: a linha vira FAILED com `attempts` e o sweeper retenta"*). Ela sobe de `turno.py::_executar_turno` ao `except Exception` de `process_message.py::process_message`, e de lá para `_marcar_falha`.
```

Não toque na nota seguinte ("Os números de linha desta seção descrevem a árvore **antes**…"): ela continua valendo para as outras citações da seção, que ficam como estão.

- [ ] **Step 4: TEC-295**

No parágrafo que começa "**Isto é mais barato do que parece", troque exatamente dois trechos:

- `(que apontava para \`turno.py:1364\`, hoje dentro do comentário da R5)` → `(que apontava para a linha 1364 de \`turno.py\`, hoje dentro do comentário da R5)`
- `` `texto_com_oferta(corpo, texto)` (`turno.py:2761`) `` → `` `texto_com_oferta(corpo, texto)` (`turno.py::_executar_turno`) ``

O parágrafo é uma linha física só: depois da edição, confira que ela não tem mais nenhum `turno.py:` seguido de dígito — senão o `--checar` reprova a linha inteira.

- [ ] **Step 5: TEC-130**

No item "**Há um único motivo e um único escritor.**", troque `` `turno.py:3745` `` por `` `turno.py::_executar_turno` `` — só a forma da citação; a afirmação fica. Logo abaixo do item, acrescente o item aninhado:

```
  - **Emenda E-01 (TEC-299, 24/09/2026):** "o único chamador" era verdade no dia deste desenho e deixou de ser pela implementação desta mesma card. Hoje `encerrar_conversa` tem **três** chamadores em produção: dois em `turno.py::_executar_turno` — o fecho da RN-03.5 (`FORA_DE_ESCOPO`) e o opt-out (`OPTOUT`) — e `conversa/repositorio.py::encerrar_inativas`, a varredura por `INATIVIDADE`. O texto acima fica como foi escrito.
```

- [ ] **Step 6: Medir o depois**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar`
Expected: saída 0, "Nenhuma ancora quebrada e nenhuma citacao nova por numero de linha."

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/
git commit -m "docs(TEC-299): as oito citacoes quebradas apontam o codigo de hoje, por ancora

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: O passo no CI e a regra escrita onde se lê

**Files:**
- Modify: `.github/workflows/ci.yml` (job `qualidade`)
- Modify: `CLAUDE.md` (seção "Comentário não mente")
- Modify: `docs/superpowers/specs/2026-09-15-tec-282-prosa-que-descreve-o-codigo-design.md` (D3 e D4)

- [ ] **Step 1: CI**

No job `qualidade`, o checkout passa a ser:

```yaml
      # Historico inteiro: o passo `citacoes em prosa` compara contra a base do
      # PR por merge-base (`base...HEAD`), e o clone raso padrao nao tem os
      # commits para calcula-lo.
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
```

E depois do passo `mypy`:

```yaml
      # TEC-299. So as duas marcas de `comentarios_tocados.py` que nao pedem
      # julgamento: ancora `arquivo.py::Nome` cujo nome nao existe, e citacao
      # por numero de linha em linha de .md que o PR acrescentou. So em PR,
      # porque LINHA precisa de uma base, e num push para a main nao ha uma
      # que faca sentido.
      - name: citacoes em prosa
        if: github.event_name == 'pull_request'
        run: python scripts/comentarios_tocados.py "origin/${{ github.base_ref }}" --checar
```

- [ ] **Step 2: CLAUDE.md**

Na seção "Comentário não mente":

a. "Ela lista os comentários e docstrings que a branch precisa reconferir, em cinco marcas." → "…em sete marcas."

b. No parágrafo "**Desde a TEC-282 a listagem também aponta a prosa.**", "— a única marca que afirma em vez de suspeitar." → "— a única das marcas por número de linha que afirma em vez de suspeitar."

c. "que tem 2706 linhas" → "que tem 2837 linhas (medido por `ast` em 24/09/2026)".

d. O parágrafo "Não é gate e não reprova nada: decidir sozinho se um comentário está certo…" passa a começar por "A listagem não é gate e não reprova nada:" e o resto fica. Logo depois dele, acrescente:

````
**Desde a TEC-299, código se cita por âncora, não por número de linha.** A forma é `arquivo.py::Nome` — ou `arquivo.py::Classe.metodo` —, a mesma do node id do pytest. Número de linha envelhece em silêncio: medido na TEC-299, das 213 citações por linha que resolviam para um arquivo só, **nenhuma** apontava além do fim dele, então `FALSO` nunca disparava — e as que estavam erradas apontavam para *outra* linha, que nenhuma checagem enxerga. Âncora se verifica: o nome existe no `ast` do arquivo ou não existe.

Duas marcas cuidam disso, e são as únicas que **reprovam**, no passo `citacoes em prosa` do job Lint e tipos. `ANCORA` é âncora cujo nome não existe no arquivo, em qualquer `.md` fora de `plans/` — não só nos que a branch mexeu. `LINHA` é citação por número de linha numa linha de `.md` que a branch **acrescentou**, fora de bloco cercado (onde vive traceback). As citações antigas ficam onde estão até alguém editar a linha delas; aí a conversão é obrigatória. Antes do PR:

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar
```

**Dentro de `_executar_turno` a âncora verifica, mas não localiza** — a função tem 2837 linhas. Ali, acompanhe a âncora de uma frase citada do comentário-alvo, que se acha por busca de texto. Só partir a função resolve isso.
````

- [ ] **Step 3: Desenho da TEC-282**

Abaixo do parágrafo "`FALSO` exige resolução inequívoca porque é a única marca que afirma algo…" (D3), acrescente:

```
  - **Emenda E-01 (TEC-299, 24/09/2026):** `FALSO` deixou de ser a única marca que afirma. A TEC-299 acrescentou `ANCORA` (âncora `arquivo.py::Nome` cujo nome não existe) e `LINHA` (citação por número de linha em linha acrescentada), as duas assertivas e as duas reprovando no CI. `ANCORA` dispensa a resolução inequívoca: se o nome não existe em nenhum candidato, a âncora é falsa em qualquer leitura. Ver `docs/superpowers/specs/2026-09-24-tec-299-ancora-de-citacao-design.md`.
```

E no fim da seção D4 ("`FALSO` é condicionado à branch…"), acrescente:

```
  - **Emenda E-02 (TEC-299, 24/09/2026):** `ANCORA` toma a decisão oposta — vale para o repo inteiro — e o argumento deste D4 não se aplica a ela: a TEC-299 conserta todas as âncoras quebradas na mesma branch, então o invariante "toda âncora resolve" nasce verdadeiro, e ruído repo-inteiro só existe enquanto alguém o viola.
```

- [ ] **Step 4: Conferir que a própria branch passa na regra**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar`
Expected: saída 0.

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`
Expected: listagem normal; releia cada `ALTERADO`, `VIZINHO`, `PROSA` e `NOMEIA` e confirme que a prosa apontada continua verdadeira (o `CLAUDE.md` e a spec da TEC-282 vão aparecer como `NOMEIA`, porque nomeiam o script — é o esperado, e é justamente o que as Steps 2-3 reconferem).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml CLAUDE.md docs/superpowers/specs/2026-09-15-tec-282-prosa-que-descreve-o-codigo-design.md
git commit -m "ci(TEC-299): ancora quebrada e citacao nova por linha reprovam o PR

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

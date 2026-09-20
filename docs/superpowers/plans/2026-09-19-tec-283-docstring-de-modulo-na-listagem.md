# TEC-283 — A docstring de módulo entra na listagem: plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development` (recomendada) ou `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam caixa (`- [ ]`) para controle.

**Objetivo:** fazer a docstring de módulo de um arquivo `.py` sair como `VIZINHO` na listagem de `scripts/comentarios_tocados.py` quando o arquivo muda e ela não muda.

**Arquitetura:** a docstring de módulo entra como caso próprio dentro de `examinar`, e **não** como uma faixa nova em `_blocos` — a faixa do módulo contém todas as outras, e acrescentá-la faria todo comentário solto de um arquivo tocado virar `VIZINHO`. A extração da docstring de um nó, hoje embutida no laço de `_docstrings`, vira uma função própria que os dois caminhos usam. O achado cai num balde de teto próprio, `<modulo>`.

**Tecnologias:** Python 3.13, `ast`, `tokenize`, pytest. Nenhuma dependência nova.

**Desenho:** [`docs/superpowers/specs/2026-09-19-tec-283-docstring-de-modulo-na-listagem-design.md`](../specs/2026-09-19-tec-283-docstring-de-modulo-na-listagem-design.md)

## Restrições globais

- Comentários e docstrings em `src/`, `tests/` e `scripts/`: português **sem** acento (exceto valor citado). Prosa em `docs/` e `CLAUDE.md`: **com** acento.
- Os três gates estáticos, no escopo exato do CI, antes de cada commit:
  `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`.
- Mensagem de commit: `tipo(TEC-283): o que passou a ser verdade`, assunto em português sem acento.
- A ferramenta continua **não** reprovando nada: `main` segue devolvendo `0` em qualquer caso.
- O balde do teto tem o nome exato `<modulo>`, com os delimitadores.

---

### Tarefa 1: A docstring de módulo intocada vira VIZINHO

**Arquivos:**
- Modificar: `scripts/comentarios_tocados.py` (`_docstrings`, `examinar`, constante nova)
- Testar: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consome: `Achado`, `examinar(arquivo: Path, alteradas: set[int]) -> list[Achado]`, o auxiliar de teste `_escrever(tmp_path, fonte) -> Path`.
- Produz: `BALDE_DO_MODULO: str` e `_docstring_de(no: ast.AST) -> tuple[int, int, str] | None`, ambos usados pela Tarefa 2.

- [ ] **Passo 1: escrever os testes que falham**

Em `tests/unit/test_comentarios_tocados.py`, logo depois de `test_comentario_fora_de_bloco_nunca_e_vizinho`:

```python
def test_docstring_de_modulo_intocada_e_vizinho(tmp_path: Path) -> None:
    """A lacuna que a TEC-283 fecha, e o caso que a TEC-282 viveu.

    Naquela branch a docstring de topo de um arquivo de teste seguiu dizendo
    "ALTERADO e VIZINHO", duas marcas de cinco, enquanto o arquivo crescia 410
    linhas por baixo dela. A ferramenta rodou contra a propria branch e nao
    apontou nada.
    """
    arquivo = _escrever(
        tmp_path,
        '''
        """Esta docstring descreve o que a funcao abaixo faz."""


        def f():
            return 1
    ''',
    )
    (achado,) = examinar(arquivo, {6})
    assert achado.alterado is False
    assert achado.linha == 2
    assert achado.bloco == BALDE_DO_MODULO


def test_arquivo_sem_docstring_de_modulo_nao_ganha_achado(tmp_path: Path) -> None:
    arquivo = _escrever(
        tmp_path,
        """
        def f():
            return 1
    """,
    )
    assert examinar(arquivo, {3}) == []


def test_docstring_de_modulo_alterada_continua_alterado(tmp_path: Path) -> None:
    """Um achado so: os dois ramos sao mutuamente exclusivos, nao somam."""
    arquivo = _escrever(
        tmp_path,
        '''
        """Esta docstring mudou nesta branch."""


        def f():
            return 1
    ''',
    )
    achados = examinar(arquivo, {2, 6})
    assert len(achados) == 1
    assert achados[0].alterado is True
```

E acrescentar `BALDE_DO_MODULO` à lista de importações vinda de `scripts.comentarios_tocados`. A lista é ordenada pelo isort do ruff, que põe as constantes em maiúsculas primeiro: `BALDE_DO_MODULO` entra **antes** de `MAXIMO_DE_CITACOES_POR_DOCUMENTO`, na primeira posição. Se errar, o `ruff check` do passo 6 reprova e diz onde.

- [ ] **Passo 2: rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "docstring_de_modulo_intocada or sem_docstring_de_modulo or docstring_de_modulo_alterada" --tb=short
```

Esperado: erro de importação de `BALDE_DO_MODULO` (`ImportError`). Depois de a constante existir, os dois primeiros testes falham por achado ausente ou a mais.

- [ ] **Passo 3: a constante e a extração própria**

Em `scripts/comentarios_tocados.py`, logo abaixo de `MAXIMO_DE_CITACOES_POR_DOCUMENTO`:

```python
# O balde de teto da docstring de modulo, que nao pertence a def nem class.
#
# `limitar` agrupa os VIZINHO pelo NOME do bloco, para a linha de resumo poder
# dizer onde ficou o que foi omitido. Os delimitadores nao sao validos em
# identificador Python, entao este nome nunca colide com um def ou class
# homonimo -- que e a ambiguidade que `limitar` ja declara tolerar nos outros
# baldes. Como e no maximo UM achado por arquivo, este balde nunca bate o teto:
# o nome existe para o resumo nao sair com balde vazio, nao porque o corte va
# acontecer.
BALDE_DO_MODULO = "<modulo>"
```

Substituir o corpo de `_docstrings` pelo par abaixo, preservando a docstring existente da função:

```python
def _docstring_de(no: ast.AST) -> tuple[int, int, str] | None:
    """A docstring deste no como (primeira linha, ultima linha, primeira frase).

    Extraida do laco de `_docstrings` porque `examinar` precisa da docstring de
    MODULO sozinha: ela e a unica que nao esta dentro de def nem class, entao e
    a unica que `dentro_de_bloco_mexido` nunca alcanca.
    """
    corpo = getattr(no, "body", None)
    if not corpo:
        return None
    primeiro = corpo[0]
    if not (
        isinstance(primeiro, ast.Expr)
        and isinstance(primeiro.value, ast.Constant)
        and isinstance(primeiro.value.value, str)
    ):
        return None
    texto = primeiro.value.value.strip().splitlines()
    return (
        primeiro.lineno,
        primeiro.end_lineno or primeiro.lineno,
        f'"""{texto[0] if texto else ""}',
    )


def _docstrings(arvore: ast.AST) -> list[tuple[int, int, str]]:
    """Cada docstring como (primeira linha, ultima linha, primeira frase)."""
    achados = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if (achado := _docstring_de(no)) is not None:
            achados.append(achado)
    return achados
```

- [ ] **Passo 4: o caso próprio em `examinar`**

Em `examinar`, logo depois do laço `for inicio, fim, texto in _docstrings(arvore):` e antes do `return`:

```python
    # A docstring de MODULO, o unico achado que nao passa por
    # `dentro_de_bloco_mexido`: ela nao esta dentro de def nem class, e a faixa
    # do modulo nao pode entrar em `_blocos` porque conteria todas as outras --
    # todo comentario solto do arquivo viraria VIZINHO.
    #
    # Os dois ramos sao mutuamente exclusivos: o laco acima ja a emite como
    # ALTERADO quando ela mesma mudou, e este so age quando ela nao mudou.
    doc_do_modulo = _docstring_de(arvore)
    if alteradas and doc_do_modulo is not None:
        inicio, fim, texto = doc_do_modulo
        if not any(n in alteradas for n in range(inicio, fim + 1)):
            achados.append(Achado(inicio, texto, False, distancia(inicio, fim), BALDE_DO_MODULO))
```

A guarda `alteradas` existe porque `distancia` faz `min()` sobre esse conjunto e um conjunto vazio levantaria `ValueError`. `linhas_alteradas` já descarta arquivo sem linha alterada, então em produção nunca é vazio; a guarda é para quem chamar `examinar` direto.

- [ ] **Passo 5: rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py --tb=short
```

Esperado: tudo verde, inclusive `test_comentario_fora_de_bloco_nunca_e_vizinho` e `test_docstring_de_modulo_classe_funcao_e_async`, que cobrem o refactor de `_docstrings`.

- [ ] **Passo 6: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 7: commit**

```bash
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py
git commit -m "feat(TEC-283): a docstring de modulo intocada vira VIZINHO"
```

---

### Tarefa 2: O balde não colide, o teto continua valendo, e o comentário solto continua de fora

**Arquivos:**
- Modificar: `tests/unit/test_comentarios_tocados.py`

**Interfaces:**
- Consome: `BALDE_DO_MODULO`, `limitar`, `MAXIMO_DE_VIZINHOS_POR_BLOCO`, `Achado` da Tarefa 1.
- Produz: nada que tarefa seguinte consuma.

- [ ] **Passo 1: escrever os testes que falham**

Logo depois dos testes da Tarefa 1:

```python
def test_comentario_solto_continua_fora_mesmo_com_docstring_de_modulo(
    tmp_path: Path,
) -> None:
    """A D2 do desenho, travada em teste.

    A implementacao errada e acrescentar a faixa do modulo a `_blocos`: ela
    contem todas as outras, entao todo comentario solto do arquivo viraria
    VIZINHO. Aqui o arquivo tem docstring de modulo E comentario solto, e so a
    docstring pode sair.
    """
    arquivo = _escrever(
        tmp_path,
        '''
        """Docstring de modulo."""

        # comentario solto, fora de qualquer def


        def f():
            return 1
    ''',
    )
    (achado,) = examinar(arquivo, {8})
    assert achado.linha == 2
    assert achado.bloco == BALDE_DO_MODULO


def test_o_balde_do_modulo_nao_colide_com_def_homonimo() -> None:
    """`limitar` chaveia por NOME de bloco: o balde do modulo tem de ser seu.

    Um def nao pode se chamar `<modulo>` -- os delimitadores nao sao validos em
    identificador --, entao a colisao e impossivel por construcao. Este teste
    fixa a consequencia: os dois baldes tem teto proprio.
    """
    vizinhos_do_def = [
        Achado(linha, "# vizinho", False, linha, "f")
        for linha in range(10, 10 + MAXIMO_DE_VIZINHOS_POR_BLOCO + 2)
    ]
    do_modulo = Achado(1, '"""do modulo', False, 9, BALDE_DO_MODULO)
    ficam, omitidos = limitar([do_modulo, *vizinhos_do_def], teto=MAXIMO_DE_VIZINHOS_POR_BLOCO)
    assert do_modulo in ficam
    assert omitidos == {"f": 2}


def test_o_achado_do_modulo_nunca_e_cortado() -> None:
    """E um so por arquivo, entao nunca bate o teto -- consequencia da D3."""
    do_modulo = Achado(1, '"""do modulo', False, 500, BALDE_DO_MODULO)
    ficam, omitidos = limitar([do_modulo], teto=MAXIMO_DE_VIZINHOS_POR_BLOCO)
    assert ficam == [do_modulo]
    assert omitidos == {}
```

- [ ] **Passo 2: rodar e ver o resultado**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_comentarios_tocados.py -k "comentario_solto or balde_do_modulo or nunca_e_cortado" --tb=short
```

Esperado: **passam de primeira**. São testes de caracterização — fixam o que a Tarefa 1 já entregou para que uma "simplificação" futura reprove. Se algum falhar, a Tarefa 1 está errada: pare e corrija lá, não aqui.

- [ ] **Passo 3: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 4: commit**

```bash
git add tests/unit/test_comentarios_tocados.py
git commit -m "test(TEC-283): o balde do modulo tem teto proprio e o comentario solto segue fora"
```

---

### Tarefa 3: A prosa deste repo para de descrever a cegueira que acabou de sumir

**Arquivos:**
- Modificar: `scripts/comentarios_tocados.py` (docstring de módulo)
- Modificar: `tests/unit/test_comentarios_tocados.py` (docstring de módulo)
- Modificar: `CLAUDE.md` (seção "Comentário não mente")

**Interfaces:**
- Consome: o comportamento entregue nas Tarefas 1 e 2.
- Produz: nada.

- [ ] **Passo 1: a docstring do script**

Em `scripts/comentarios_tocados.py`, o parágrafo que hoje começa com "Duas cegueiras conhecidas, nenhuma nova desta card." passa a descrever **uma**. Texto novo (sem acento, como o resto do arquivo):

```
Uma cegueira conhecida, herdada da TEC-277 e ainda aberta na TEC-284: apagar
ou renomear um .py nunca entra no conjunto de alterados -- `linhas_alteradas`
para de acumular em `+++ /dev/null` --, entao toda citacao aquele arquivo
escapa justo quando ficaria FALSO.
```

E a descrição de `VIZINHO`, no bloco das cinco marcas, passa a dizer que a docstring de modulo tambem entra. Texto novo da marca:

```
  VIZINHO   o comentario NAO mudou, mas o codigo dentro do mesmo def/class
            mudou -- ou e a docstring de MODULO de um arquivo que mudou por
            baixo dela (TEC-283). E o caso perigoso: ninguem olha para o que
            nao aparece no diff, e e exatamente assim que um comentario passa
            a mentir. A saida padrao mostra so os VIZINHO mais proximos da
            alteracao em cada bloco e resume o resto numa linha, porque a
            listagem inteira costuma passar de 100 linhas e deixar de caber
            numa leitura.
```

- [ ] **Passo 2: a docstring do arquivo de teste**

Em `tests/unit/test_comentarios_tocados.py`, a docstring de módulo hoje credita "TEC-277 e TEC-282". Passa a creditar a TEC-283 também. Texto novo:

```
"""A ferramenta que lista comentarios, docstrings e prosa a reconferir, testada.

TEC-277, TEC-282 e TEC-283. Pura: as partes que decidem as cinco marcas --
ALTERADO, VIZINHO, PROSA, FALSO e NOMEIA -- nao tocam git nem disco, recebem
texto de diff, fonte, documento e conjuntos de linhas e nomes. Antes da
TEC-277 o script nao tinha teste nenhum.
"""
```

- [ ] **Passo 3: o CLAUDE.md**

Na seção "Comentário não mente", a frase que descreve `VIZINHO` hoje diz:

> **`VIZINHO` é o que não mudou, mas está dentro de um `def`/`class` cujo código mudou**

Passa a (com acento, é prosa de `docs`/raiz):

> **`VIZINHO` é o que não mudou, mas está dentro de um `def`/`class` cujo código mudou — ou é a docstring de módulo de um arquivo que mudou por baixo dela (TEC-283)**

Acrescentar, logo depois do parágrafo que termina em "...e por isso ninguém o relê", um parágrafo novo:

> **Desde a TEC-283 a docstring de módulo entra no mesmo alcance.** Ela é a prosa que mais sobrevive a refatoração, porque não está dentro de nenhum `def` e nenhuma edição a arrasta junto — foi assim que a docstring de `tests/unit/test_comentarios_tocados.py` seguiu creditando só a TEC-277 enquanto aquela branch crescia o arquivo em 410 linhas. Medido sobre os 20 merges mais recentes: o acréscimo é de **32 achados em 131 arquivos tocados**, mediana de 0 por branch e máximo de 11 — 44% dos arquivos tocados não têm docstring de módulo, e entre os que têm, 56% já a editam na mesma branch.

- [ ] **Passo 4: rodar a própria ferramenta**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Esperado: a listagem aponta a si mesma. `scripts/comentarios_tocados.py` e `tests/unit/test_comentarios_tocados.py` saem com a docstring de módulo como `ALTERADO` (foram editadas neste passo), e o `CLAUDE.md` aparece na seção de prosa como `NOMEIA`. Reler cada achado e confirmar que a prosa bate com o código — é a validação mais barata desta card.

- [ ] **Passo 5: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 6: commit**

```bash
git add scripts/comentarios_tocados.py tests/unit/test_comentarios_tocados.py CLAUDE.md
git commit -m "docs(TEC-283): a prosa para de dizer que a docstring de modulo e cega"
```

---

### Tarefa 4: A suíte inteira, uma vez, e o PR

**Arquivos:** nenhum.

- [ ] **Passo 1: a suíte inteira, uma execução**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guardar o hash junto com o resultado. Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando**: é o Postgres sob paralelismo, e a cura é rodar por blocos (`tests/unit`, `tests/integration`, `tests/features`), não insistir no `-n 8`.

Se a primeira execução falhar num teste, repita **uma** vez sobre a mesma árvore antes de culpar esta branch — é a única coisa que separa flake de regressão.

- [ ] **Passo 2: push e PR**

```bash
git push -u origin feat/tec-283-docstring-de-modulo-na-listagem
gh pr create --base main --title "TEC-283: a docstring de modulo entra na listagem" --body "..."
```

O corpo do PR aponta o desenho e traz a medição dos 20 merges.

- [ ] **Passo 3: a card**

Comentar na TEC-283 e mover para "Em análise". O comentário registra, além do link do PR:

- **A divergência em relação à card:** ela supunha que "todo arquivo tocado passaria a render pelo menos um achado" e pedia que se medisse antes de escolher a regra. Medido, são 32 achados em 131 arquivos tocados (mediana 0 por branch), e por isso a regra ficou **sem** o limiar de N linhas que a card mandava considerar — o limiar de 30 cortaria os 32 para 9.
- **O critério de aceite "o volume continua cabendo numa leitura"**, e como foi exercitado: por teste unitário sobre `limitar`, não por execução de ponta a ponta sobre uma branch grande.
- **O que a card não entrega:** a TEC-284 segue aberta, e a docstring do script continua descrevendo aquela cegueira.

# TEC-224 — mypy no `alembic`, com `py.typed` publicado — plano de implementação

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development` (recomendada) ou `superpowers:executing-plans` para executar tarefa a tarefa. Os passos usam checkbox (`- [ ]`).

**Goal:** `alembic/` passa a ser checado pelo mypy, no CI e não só localmente, com `src/mobia/py.typed` publicado no pacote.

**Architecture:** Quatro mudanças pequenas e acopladas: o marcador PEP 561, a declaração de `package-data` que o faz chegar ao wheel, `alembic` no `files` do mypy, e o passo do CI deixando de passar `src` como argumento — porque argumento sobrepõe `files` e sem essa troca o CI não veria a extensão. Mais um erro de tipo a corrigir e duas frases de prosa que a mudança torna falsas.

**Tech Stack:** Python 3.13, mypy, setuptools, SQLAlchemy, Alembic, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-224-mypy-no-alembic-com-py-typed-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento** — exceto valor citado. Nenhum linter checa isto.
- **Prosa em `docs/`, `README.md` e `CLAUDE.md`: COM acento.** O comentário do `.github/workflows/ci.yml` hoje é sem acento; mantenha a convenção do arquivo.
- `ruff` com `line-length = 100`.
- Mensagem de commit em português sem acento no assunto, formato `tipo(TEC-224): o que passou a ser verdade`.
- Os três gates, no escopo do CI: `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, e — **depois desta card** — `mypy` sem argumento.
- Python da venv: `./.venv/Scripts/python.exe`. Nunca `python` nu.

## Estado medido antes da branch, para conferir contra

`./.venv/Scripts/python.exe -m mypy alembic` hoje: **9 erros em 5 arquivos** (8 `import-untyped`, 1 `var-annotated`), 37 arquivos checados. Com `src/mobia/py.typed` presente, sobra **1 erro** (`_COLUNAS` na `0033`). Com a anotação também aplicada, `mypy src alembic` dá **Success: no issues found in 179 source files**. Os três números foram medidos nesta máquina em 20/09/2026 e o plano depende deles.

---

### Task 1: O marcador, o escopo, o CI e o erro que sobra

**Files:**
- Create: `src/mobia/py.typed` (vazio)
- Modify: `pyproject.toml` (`[tool.mypy] files`, e novo `[tool.setuptools.package-data]`)
- Modify: `.github/workflows/ci.yml` (passo `mypy` e o comentário acima dos gates)
- Modify: `alembic/versions/0033_trilha_do_investidor.py` (import de `Any`, anotação de `_COLUNAS`)
- Modify: `CLAUDE.md` (a frase que diz que o mypy fica só em `src`)

**Interfaces:**
- Consumes: nada.
- Produces: `mypy` sem argumento passa a checar `src` e `alembic`. A Task 2 verifica o empacotamento do marcador.

As cinco edições são uma tarefa só porque nenhuma delas é verificável sozinha: o marcador sem o `files` não muda nada, o `files` sem a troca no CI produz o estado que o critério de pronto proíbe, e o `files` sem a anotação deixa o gate vermelho.

- [ ] **Step 1: Confirmar o estado de partida**

```bash
./.venv/Scripts/python.exe -m mypy alembic
```

Esperado: `Found 9 errors in 5 files (checked 37 source files)`. **Se o número for outro, pare e diga** — o plano foi escrito contra 9 e uma divergência significa que a árvore mudou.

- [ ] **Step 2: Criar o marcador**

Arquivo vazio, sem conteúdo nenhum. PEP 561 exige só a presença.

```bash
touch src/mobia/py.typed
```

- [ ] **Step 3: Verificar que o marcador sozinho derruba oito dos nove erros**

```bash
./.venv/Scripts/python.exe -m mypy alembic
```

Esperado, exatamente:

```
alembic\versions\0033_trilha_do_investidor.py:34: error: Need type annotation for "_COLUNAS"  [var-annotated]
Found 1 error in 1 file (checked 37 source files)
```

- [ ] **Step 4: Anotar `_COLUNAS` na 0033**

Em `alembic/versions/0033_trilha_do_investidor.py`, o bloco de imports hoje é:

```python
import sqlalchemy as sa

from alembic import op
```

Passa a ser:

```python
from typing import Any

import sqlalchemy as sa

from alembic import op
```

E a linha 34, hoje `_COLUNAS = (`, passa a ser:

```python
# `Any` por dentro de proposito: a tupla mistura BigInteger, Numeric, String e
# Boolean, entao nao existe parametro de tipo comum mais estreito. Uma uniao
# dos sete nao pagaria o que custa a ler, para uma tupla que so e iterada em
# `op.add_column`.
_COLUNAS: tuple[sa.Column[Any], ...] = (
```

- [ ] **Step 5: Acrescentar `alembic` ao escopo do mypy**

Em `pyproject.toml`, na seção `[tool.mypy]`, a linha `files = ["src"]` passa a ser:

```toml
files = ["src", "alembic"]
```

- [ ] **Step 6: Declarar o `package-data`**

Ainda em `pyproject.toml`, logo depois do bloco `[tool.setuptools.packages.find]` (e do comentário longo que o acompanha), acrescentar:

```toml
# PEP 561 (TEC-224). Sem esta declaracao o marcador fica no repositorio e nao
# chega ao wheel, e o `alembic` -- que importa `mobia` de fora de `src/` --
# volta a ver o pacote como sem tipos. Nao ha MANIFEST.in neste projeto; esta
# e a unica declaracao de package-data.
[tool.setuptools.package-data]
mobia = ["py.typed"]
```

- [ ] **Step 7: Rodar o gate completo**

```bash
./.venv/Scripts/python.exe -m mypy
```

Esperado: `Success: no issues found in 179 source files`.

- [ ] **Step 8: Trocar o passo do CI**

Em `.github/workflows/ci.yml`, o passo hoje é:

```yaml
      - name: mypy
        run: mypy src
```

Passa a ser:

```yaml
      - name: mypy
        run: mypy
```

**Isto não é cosmético.** `src` ali é argumento de linha de comando, e argumento sobrepõe o `files` do `pyproject.toml` — sem esta troca, o Step 5 não teria efeito nenhum no CI.

- [ ] **Step 9: Corrigir o comentário do CI, que a mudança torna falso**

Ainda em `.github/workflows/ci.yml`, o comentário acima dos passos de gate termina hoje com:

```
      # `gerar_base_simulada.py` sem que nada o dissesse. O mypy segue so em
      # `src` -- cobrir alembic exige antes um src/mobia/py.typed, que e outra
      # mudanca.
```

Essas três linhas deixam de ser verdade. Reescreva-as para dizer o que passou a valer: que o `py.typed` foi publicado pela TEC-224, que o mypy agora cobre `src` e `alembic`, e que o escopo dele vive no `pyproject.toml` — por isso o passo roda `mypy` sem argumento, e por isso acrescentar diretório é mexer num lugar só.

Mantenha a convenção do arquivo: o comentário do `ci.yml` é **sem acento**.

Escreva o texto você mesmo. Não troque uma afirmação falsa por outra: confira no `pyproject.toml` o que de fato está no `files` antes de descrevê-lo.

- [ ] **Step 10: Corrigir a frase do `CLAUDE.md`**

Na seção dos três gates, a frase que termina assim:

> O mypy segue só em `src` — cobrir `alembic` exige antes um `src/mobia/py.typed`.

Deixa de ser verdade. Reescreva para registrar: que o mypy passou a cobrir `src` e `alembic` desde a TEC-224 (20/09/2026), que o marcador foi publicado, e que **o comando é `mypy` sem argumento tanto local quanto no CI**, porque o escopo mora no `pyproject.toml`.

**Confira também o bloco de comandos no topo do arquivo.** Ele lista `mypy src` como o comando do CI; depois desta card o CI roda `mypy`. Se o bloco disser `mypy src`, ele precisa mudar junto, ou o `CLAUDE.md` passa a mentir sobre o comando exato do CI — que é justamente o que aquela seção promete entregar.

Prosa do `CLAUDE.md` leva acento.

- [ ] **Step 11: Os três gates, no escopo novo**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Esperado: os três limpos. O `ruff format` é gate separado do `ruff check` — passar num não diz nada sobre o outro.

- [ ] **Step 12: Commit**

```bash
git add src/mobia/py.typed pyproject.toml .github/workflows/ci.yml alembic/versions/0033_trilha_do_investidor.py CLAUDE.md
git commit -m "feat(TEC-224): o mypy cobre alembic, com py.typed publicado"
```

---

### Task 2: Provar que o marcador chega ao pacote construído

**Files:**
- Nenhum arquivo do repositório; a verificação é sobre o artefato de build.

**Interfaces:**
- Consumes: o `[tool.setuptools.package-data]` da Task 1.
- Produces: a evidência que o terceiro critério de pronto da card pede.

**Por que isto é tarefa própria e não um passo da anterior.** O critério de pronto diz *"`pip install -e .` continua funcionando e o marcador chega ao pacote instalado"*. As duas metades não se provam do mesmo jeito, e a segunda **não se prova no editable**: num `pip install -e .` o mypy encontra `src/mobia/py.typed` pelo caminho do próprio repositório, então o gate ficaria verde mesmo com o `package-data` ausente ou errado. Rodar o mypy e declarar o empacotamento verificado seria autoengano.

- [ ] **Step 1: Construir o wheel**

> **`$TMPDIR` é vazio neste Git Bash.** Usá-lo produz caminhos na raiz (`/tec224`) e o comando morre com `Permission denied` — medido nesta sessão. Use o diretório abaixo, literal.

```bash
SAIDA=/c/Users/eduar/AppData/Local/Temp/claude/c--Projetos-mobIA/tec224
mkdir -p "$SAIDA"
./.venv/Scripts/python.exe -m pip wheel --no-deps --wheel-dir "$SAIDA" . 2>&1 | tail -5
```

`pip wheel --no-deps` é o caminho preferido porque **não instala nada de novo na venv** — ao contrário de `python -m build`, que exigiria instalar o pacote `build` e sujaria o ambiente só para uma conferência. Se por algum motivo ele falhar, diga qual foi o erro em vez de trocar de ferramenta por conta própria.

- [ ] **Step 2: Conferir que `py.typed` está dentro do wheel**

```bash
./.venv/Scripts/python.exe -c "
import glob, zipfile
alvo = sorted(glob.glob('/c/Users/eduar/AppData/Local/Temp/claude/c--Projetos-mobIA/tec224/*.whl'))[-1]
nomes = zipfile.ZipFile(alvo).namelist()
achados = [n for n in nomes if n.endswith('py.typed')]
print('wheel:', alvo)
print('py.typed no wheel:', achados)
assert achados == ['mobia/py.typed'], f'esperado mobia/py.typed, veio {achados}'
print('OK')
"
```

Esperado: `py.typed no wheel: ['mobia/py.typed']` e `OK`.

**Se a lista vier vazia**, o `package-data` não está funcionando — pare e diga. Não conserte adivinhando: reporte o conteúdo de `nomes` que começa com `mobia/`, para que a causa seja diagnosticada e não chutada.

- [ ] **Step 3: Conferir que o editable continua funcionando**

```bash
./.venv/Scripts/python.exe -m pip install -e . --quiet --no-deps 2>&1 | tail -3
./.venv/Scripts/python.exe -c "import mobia; print('import ok:', mobia.__file__)"
./.venv/Scripts/python.exe -m mypy
```

Esperado: o `import` funciona e o mypy segue `Success`.

- [ ] **Step 4: Limpar o artefato**

```bash
rm -rf /c/Users/eduar/AppData/Local/Temp/claude/c--Projetos-mobIA/tec224
```

O wheel é artefato de verificação, não entra no repositório. Confirme com `git status --short` que nada novo apareceu — em especial que `build/`, `dist/` ou `*.egg-info` não ficaram na árvore. Se ficaram, remova-os e diga no relatório se algum deles já estava no `.gitignore` ou não.

- [ ] **Step 5: Registrar a evidência**

Não há commit nesta tarefa se nada mudou na árvore. Escreva no relatório: o comando de build usado, o nome do wheel, a saída da conferência e o resultado do editable. **Essa saída é o que prova o terceiro critério de pronto da card** — sem ela, o critério fica por conta da palavra de alguém.

---

### Task 3: Suíte e PR

**Files:** nenhum.

- [ ] **Step 1: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short -q
```

Guardar o hash junto com o resultado. Esta card não muda comportamento de runtime — mas mexe no `pyproject.toml`, que é onde vive a configuração do pytest, então a suíte é a conferência de que nada foi arrastado junto.

Se reprovar, repita sobre a mesma árvore antes de culpar a mudança. Centenas de `ERROR` de setup significam a queda do Postgres sob o `-n 8`: rode por blocos em vez de repetir o mesmo comando.

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Esta branch mexe no `CLAUDE.md` e num script de CI, então a marca `NOMEIA` e a `PROSA` merecem atenção especial.

- [ ] **Step 3: Push e PR contra `main`**

Termina em PR, nunca em merge local. Depois: comentar na card e movê-la para **Em análise**.

O comentário registra, no mínimo:

- **As três divergências medidas em relação ao texto da card:** não eram quatro erros e sim nove; `_em_lotes` na `0004` não é o conserto (o mypy não a flagra, porque não há `disallow_untyped_defs`) e o erro real era `_COLUNAS` na `0033`, arquivo que não existia quando a card foi escrita; e o passo do CI passava `src` como argumento, o que sobrepõe o `files` — sem trocar isso, o critério de pronto sobre o CI ficaria por cumprir sem que nada avisasse.
- **A evidência do empacotamento**, com a saída do wheel — porque é o critério que o editable não prova.
- **O que a card não faz:** estender o mypy a `tests`, `evals` e `scripts`, agora possível e não medido; e aumentar a severidade (`disallow_untyped_defs`), que é o que faria aparecer o erro em `_em_lotes` que a card esperava.

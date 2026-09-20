# TEC-224 — mypy no `alembic`, com `py.typed` publicado

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-224](https://eduardodurieuxlopes.atlassian.net/browse/TEC-224) — épico TEC-208
**Branch:** `feat/tec-224-mypy-no-alembic-com-py-typed`
**Origem:** review final da branch `feat/tec-126-telemetria`.

## Objetivo

Trazer `alembic/` para dentro do gate de tipos, no CI e não só na máquina de quem desenvolve — e publicar `py.typed`, que é o que torna isso possível.

## O que a medição mudou em relação ao texto da card

A card é de 24/08/2026. Três das coisas que ela afirma já não valem.

**1. Não são quatro erros, são nove.** A card diz que *"rodar `mypy alembic` hoje produz quatro erros `import-untyped`"*. Medido em 20/09/2026, com 37 arquivos de migration:

```
alembic\env.py:9,10,11,12,13        import-untyped  (5x, mobia.app.config e quatro models)
alembic\versions\0021_...:37        import-untyped  (mobia.domain.texto)
alembic\versions\0019_...:40        import-untyped  (mobia.domain.texto)
alembic\versions\0004_...:24        import-untyped  (mobia.infra.crypto)
alembic\versions\0033_...:34        var-annotated   (Need type annotation for "_COLUNAS")
Found 9 errors in 5 files (checked 37 source files)
```

Oito são `import-untyped`, que o marcador resolve de uma vez. O nono é de outra natureza.

**2. A card nomeia o conserto errado.** Ela diz *"sabidamente falta anotação de retorno em `_em_lotes` na 0004"*. **O mypy não reclama disso.** A configuração de `[tool.mypy]` não tem `disallow_untyped_defs` nem `strict`, então função sem anotação simplesmente não é checada — não é erro. Com o `py.typed` no lugar, o que sobra é um erro só, e em outro arquivo:

```
alembic/versions/0033_trilha_do_investidor.py:34: error: Need type annotation for "_COLUNAS"
Found 1 error in 1 file (checked 37 source files)
```

A `0033` não existia quando a card foi escrita. O trabalho de correção que a card previa não é o que há para fazer.

**3. O passo do CI não pega a extensão sozinho, e esta é a armadilha da card.** O critério de pronto diz *"o CI roda a checagem estendida — sem isso a mudança regride na primeira migration nova"*, e a card trata isso como consequência automática de mexer no `pyproject.toml`. Não é. O passo do CI é:

```yaml
      - name: mypy
        run: mypy src
```

`src` ali é **argumento de linha de comando**, e argumento sobrepõe o `files` do `pyproject.toml`. Acrescentar `alembic` ao `files` e parar aí produziria exatamente o estado que o critério proíbe: gate local cobrindo `alembic`, CI não.

Vale notar que o comando local que o `CLAUDE.md` manda rodar já é `./.venv/Scripts/python.exe -m mypy`, **sem argumento** — ou seja, hoje o local lê o `pyproject.toml` e o CI não. Os dois coincidem por acidente, porque `files = ["src"]` e o argumento é `src`.

## D1 — O passo do CI passa a ser `mypy` sem argumento

```yaml
      - name: mypy
        run: mypy
```

E não `mypy src alembic`. A razão é ter **uma** lista em vez de duas: com o argumento explícito, o escopo passa a existir no `pyproject.toml` e no YAML, e a próxima extensão tem de lembrar dos dois — que é a forma exata como esta divergência nasceu. Sem argumento, o CI passa a rodar o mesmo comando que o `CLAUDE.md` manda rodar local, e `files` vira fonte única.

O custo é que quem lê o `ci.yml` deixa de ver o escopo ali. Aceito: o comentário logo acima dos passos já explica o escopo de cada gate, e vai continuar explicando — a diferença é que passará a apontar para o `pyproject.toml` em vez de repetir a lista.

## D2 — `py.typed` declarado no `package-data`, e conferido num wheel

O marcador é `src/mobia/py.typed`, arquivo vazio, PEP 561. Ele precisa ser declarado para chegar ao pacote construído:

```toml
[tool.setuptools.package-data]
mobia = ["py.typed"]
```

Não há `MANIFEST.in` no repositório e não há nenhum `package-data` hoje — este é o primeiro.

**A conferência é num wheel de verdade, não no editable.** O critério de pronto da card pede que o marcador chegue ao pacote instalado, e o `pip install -e .` **não** exercita isso: no editable o mypy encontra `src/mobia/py.typed` pelo caminho do próprio repositório, então o gate ficaria verde mesmo que o empacotamento estivesse errado. A verificação honesta é construir o wheel e listar o conteúdo dele.

## D3 — O erro que sobra

`_COLUNAS` na `0033` é uma tupla de `sa.Column` sem anotação. O mypy pede a anotação porque `sa.Column` é genérico e ele não consegue inferir o parâmetro de tipo a partir de `sa.Column("nome", sa.String(16), nullable=True)`.

A anotação é `tuple[sa.Column[Any], ...]`. É `Any` por dentro de propósito: a tupla mistura `BigInteger`, `Numeric`, `String` e `Boolean`, então não existe um parâmetro de tipo comum mais estreito, e inventar uma união de sete tipos para uma tupla que só é iterada em `op.add_column` não paga o que custa a ler.

## D4 — Duas afirmações de prosa morrem nesta branch

As duas dizem que o mypy fica só em `src` porque falta o marcador. As duas passam a ser falsas no momento em que esta branch entra:

- `CLAUDE.md`, na seção dos três gates: *"O mypy segue só em `src` — cobrir `alembic` exige antes um `src/mobia/py.typed`."*
- `.github/workflows/ci.yml`, no comentário acima dos passos de gate: *"O mypy segue so em `src` -- cobrir alembic exige antes um src/mobia/py.typed, que e outra mudanca."*

Mudam na mesma branch, junto com o código que elas descrevem. A do `CLAUDE.md` precisa dizer o que passou a ser verdade: o escopo do mypy vive no `pyproject.toml`, e o comando — local e no CI — é `mypy` sem argumento.

## O que esta card NÃO faz

**Não estende o mypy para `tests`, `evals` ou `scripts`.** O `py.typed` torna isso possível — hoje qualquer um dos três produziria o mesmo `import-untyped` que o `alembic` produzia —, mas cada um tem um custo próprio de erros a corrigir, não medido aqui. A card é sobre `alembic`, que é o diretório com risco real: as migrations importam código de aplicação e a `0004` faz backfill de cifra em Python.

**Não aumenta a severidade do mypy.** `disallow_untyped_defs` faria aparecer o erro que a card esperava em `_em_lotes`, e muitos outros. É outra decisão, com outro tamanho.

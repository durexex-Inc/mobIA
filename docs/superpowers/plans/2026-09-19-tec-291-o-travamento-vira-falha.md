# TEC-291 — Plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-19-tec-291-o-travamento-vira-falha-design.md`
**Branch:** `feat/tec-291-o-travamento-vira-falha`

## Tarefa 0 — Medir os dois tetos antes de escolhê-los

Os números de D1 e D3 não podem ser chutados: um teto apertado demais transforma contenção legítima em falha, que é exatamente o flake que o `CLAUDE.md` já registra.

Uma execução instrumentada de `tests/integration` dá os dois:

- **quanto o `TRUNCATE` de `banco_limpo` leva**, por teste, para escolher o `lock_timeout`;
- **qual é o teste mais lento**, por `--durations=0`, para escolher o teto do `pytest-timeout`.

Saída esperada: dois máximos medidos, com a data e a máquina.

## Tarefa 1 — `pytest-timeout` instalado e declarado

- `pip install pytest-timeout` na venv.
- `pyproject.toml`: acrescentar `pytest-timeout>=2.3` ao extra `dev`, junto de `pytest-xdist`.
- `pyproject.toml`, `[tool.pytest.ini_options]`: `timeout = <medido na tarefa 0>`.

O teto vai no `ini`, e não em `addopts`, porque `addopts` hoje carrega só o filtro de marca e porque `timeout` é opção própria do plugin.

**Comentário obrigatório** ao lado do valor: a assimetria `signal`/`thread` entre CI e Windows (D3 do desenho). Sem ela, quem vir o processo morrer sem teardown nesta máquina vai achar que o teto está quebrado.

## Tarefa 2 — `lock_timeout` e o diagnóstico de quem bloqueia (D1 + D2)

Em `tests/conftest.py`, na fixture `banco_limpo`:

1. `SET lock_timeout = '<medido>'` na sessão antes do `TRUNCATE`.
2. `except` sobre o erro de lock, que consulta `pg_blocking_pids()` e relevanta com pid, estado, idade da transação e início da consulta de cada bloqueador.

A consulta de diagnóstico precisa de **conexão nova** — a sessão que estourou está com transação abortada e não responde mais a nada até o rollback.

Restrições:

- O caminho feliz não paga round-trip a mais. `SET lock_timeout` cabe na mesma ida do `TRUNCATE`; a consulta de diagnóstico só existe dentro do `except`.
- `tests/unit/` continua saindo cedo, antes de qualquer conexão.
- O comentário explica **por que** o teto é por sessão de teste e não no engine (D1), porque é a pergunta que quem ler vai fazer.

## Tarefa 3 — Teste que prova o diagnóstico

Um teste de integração que:

1. abre uma sessão e toma `ACCESS SHARE` numa tabela de `TABELAS`, deixando a transação aberta;
2. de outra conexão, tenta o mesmo `TRUNCATE` com o `lock_timeout` da fixture;
3. afirma que o erro levantado **nomeia o pid bloqueador e o estado dele**.

É o teste que impede a regressão silenciosa: sem ele, alguém pode remover o `except` do diagnóstico e nada reprova — o `lock_timeout` sozinho continua passando.

O teste não pode depender do `banco_limpo` para a parte bloqueadora (seria bloquear o próprio setup); monta as duas conexões por conta própria e limpa as duas no `finally`.

## Tarefa 4 — Prosa

- `CLAUDE.md`, seção "Quando o `-n 8` derruba o Postgres": o que foi medido e o que mudou (D4). Inclui a assimetria do `pytest-timeout`, porque é nessa seção que quem está travado vai procurar.
- `docs/srs/`: nada. Esta card não toca regra de produto.

## Verificação

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

A suíte inteira uma vez, com o hash guardado junto do resultado.

## Risco declarado

O teto do `pytest-timeout` é o item que pode gerar falha nova: um teste legítimo mais lento que o teto em máquina carregada passa a reprovar. O `CLAUDE.md` já registra que carga muda duração **em ordem de grandeza**, não em percentual — então a folga sobre o máximo medido tem de ser generosa, e a escolha da tarefa 0 tem de dizer qual folga adotou e por quê.

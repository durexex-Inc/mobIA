# TEC-368 — plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-24-tec-368-x-request-id-na-entrada-design.md`
**Branch:** `feat/tec-368-x-request-id-na-entrada`

Card de backend: os três gates estáticos e a suíte valem inteiros.

## Nota de ambiente: este checkout não tinha venv nem Python 3.13

Levantado em 24/09/2026, antes de começar. `pyproject.toml` pede `requires-python = ">=3.13"`; a máquina tinha apenas 3.12.7 e um 3.14.6 do `uv`. Não havia `.venv`, e o Docker estava parado — ou seja, nada do que o `CLAUDE.md` documenta rodava.

Montado sem tocar na instalação do sistema:

```bash
uv python install 3.13                                      # 3.13.14, a linha do CI
uv venv --python 3.13 .venv
uv pip install --python ./.venv/Scripts/python.exe -e ".[dev]"
docker compose up -d
./.venv/Scripts/python.exe -m alembic upgrade head
```

**3.13 e não o 3.14 que já estava na máquina**: o CI roda `PYTHON_VERSION: "3.13"`, e um gate verde numa minor diferente da do CI é um gate que mede outra coisa.

Baseline medido nesta árvore, antes de qualquer mudança: os três gates estáticos verdes (`ruff check`, `ruff format --check`, `mypy` — 204 arquivos) e **1664 testes unitários em 13,1s**.

## Fase 1 — a função pura

`_id_de_requisicao(entrada)` em `src/mobia/api/middleware.py`: devolve a entrada quando ela casa `^[A-Za-z0-9._:-]{1,200}$`, senão um `uuid4()`.

A expressão é a mesma do BFF (`idDeRequisicao`, em `frontend/src/lib/servidor/bff.ts`), pela D4 — e o comentário de cada lado nomeia o outro, porque nenhum gate liga os dois através da fronteira de linguagem.

**Verificação:** `tests/unit/` com os mesmos valores de borda que `bff.test.ts` usa — 200 caracteres aceitos, 201 substituídos.

## Fase 2 — o middleware

`CorrelacaoDeRequisicao(BaseHTTPMiddleware)`, ao lado do `RateLimitPorIP` no mesmo módulo:

1. lê `x-request-id`, passa por `_id_de_requisicao`;
2. `token = correlation_id.set(id)`;
3. `try: resposta = await call_next(request)` … `finally: correlation_id.reset(token)`;
4. escreve `X-Request-Id` na resposta antes de devolvê-la.

**Verificação:** `tests/integration/`, com `TestClient`. O ponto a provar de verdade — e não por suposição sobre biblioteca de terceiro — é que o `set()` feito **antes** de `call_next` é visto **dentro** do handler, apesar de o `BaseHTTPMiddleware` rodar o app de baixo numa task separada.

## Fase 3 — a ordem na pilha, que é onde mora o risco

Em `create_app`:

```python
app.add_middleware(RateLimitPorIP)
app.add_middleware(CorrelacaoDeRequisicao)   # DEPOIS no codigo => por FORA na pilha
```

Verificado na fonte do Starlette (`applications.py:107` e `:81`), não de memória: `add_middleware` insere no índice 0 e a pilha é construída em `reversed`, então o último adicionado fica por fora.

**Verificação, e é o teste mais importante desta branch:** com o limite estourado, o 429 do `RateLimitPorIP` tem de carregar `X-Request-Id`, e o evento `ratelimit.blocked` tem de carregar `correlation_id`. Esse caminho **não chama `call_next`** — se a correlação estiver por dentro, ela não roda, e a requisição que mais interessa correlacionar é a única sem correlação.

Trocar as duas linhas de lugar não reprova em nenhum dos três gates estáticos. Este teste é o único que reprova.

## Fase 4 — os dois `set()` dos handlers

- `whatsapp.py`: o `correlation_id.set(str(uuid.uuid4()))` **sai**, com o `import uuid` se ele ficar sem uso.
- `widget.py`: **fica**, e ganha o comentário dizendo que é WebSocket e por isso nenhum `BaseHTTPMiddleware` o alcança — senão a próxima pessoa apaga por simetria.

**Verificação:** a suíte de integração do webhook e a do widget continuam passando sem edição. Se alguma precisar mudar, a premissa da D3 está errada.

## Fase 5 — a prosa

`main.py` tem um bloco de comentário sobre o `RateLimitPorIP` ser "o primeiro middleware do projeto". Deixa de ser verdade nesta branch. A docstring de `middleware.py` diz a mesma coisa. As duas mudam junto.

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Esta branch mexe em `middleware.py`, `main.py`, `whatsapp.py` e `widget.py` — arquivos antigos e muito comentados, então a marca `VIZINHO` deve render, e é justamente a que existe para pegar comentário que ninguém editou.

## Ordem de verificação, no fim

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Os três estáticos primeiro porque são segundos, a suíte depois. **Uma execução da suíte basta**, e o hash vai guardado junto do resultado; segunda execução só se a primeira falhar, que é quando ela separa flake de regressão.

Se voltarem centenas de `CannotConnectNowError`, não repetir o mesmo comando: é o banco caído, e o caminho é `docker compose restart postgres` mais execução por blocos.

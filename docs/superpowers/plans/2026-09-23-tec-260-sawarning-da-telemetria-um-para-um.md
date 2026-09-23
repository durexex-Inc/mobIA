# TEC-260 — Plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-23-tec-260-sawarning-da-telemetria-um-para-um-design.md`
**Branch:** `feat/tec-260-sawarning-da-telemetria-um-para-um`

Um arquivo de teste muda. Nada em `src/`, nada no `pyproject.toml`.

## Tarefa 0 — A sonda, antes de escolher a correção (executada)

A card condiciona tudo a uma medição. Feita com um arquivo temporário em `tests/integration/`, apagado depois, em três variantes — a diferença entre elas é o que revelou o mecanismo real:

1. sem referência viva à primeira instância → **sem** SAWarning;
2. com `session.get()` (o teste de hoje) → **com**;
3. com referência forte e sem `session.get()` → **com**.

Resultado nas duas tabelas do desenho. Conclusão dupla: o `IntegrityError` vem do Postgres (`23505`, `message_telemetry_pkey`), e o warning depende de haver referência forte viva, não do `get`.

A sonda **não** entra no commit. Ela existiu para responder à pergunta da card; o que fica no repositório é a resposta, na asserção da tarefa 2 e no comentário da tarefa 1.

## Tarefa 1 — `expunge` e o comentário que explica (D1)

Arquivo: `tests/integration/test_message_model.py`, `test_telemetria_e_um_para_um_com_a_mensagem`.

`session.expunge(linha)` entre as asserções sobre `cost_usd` e o `session.add` da colidente.

O comentário é obrigatório e tem de dizer três coisas, porque são as três que custam meia hora a quem reencontrar isto:

- o identity map guarda referência **fraca**, e por isso o aviso depende de `linha` estar viva;
- o `INSERT` continua indo ao banco — `expunge` não enfraquece o que o teste prova;
- por que o vizinho `test_provider_message_id_e_unico_por_canal` não precisa do mesmo: lá os dois objetos têm `id` diferente, e a colisão é na UNIQUE composta, nunca no identity map.

Sem o terceiro item, o `expunge` parece arbitrário ao lado de um teste quase idêntico que não o tem.

## Tarefa 2 — A origem vira asserção (D2)

No mesmo teste, depois do `rollback`:

```python
causa = capturado.value.orig.__cause__
assert causa.sqlstate == "23505"
assert causa.constraint_name == "message_telemetry_pkey"
```

Exige trocar `pytest.raises(IntegrityError)` por `pytest.raises(IntegrityError) as capturado`.

## Tarefa 3 — O que NÃO se faz

- **Nenhum filtro de warning**, nem global no `pyproject.toml` nem por marcador no teste. A card proíbe o global; o desenho descarta o escopado, porque não há mais o que filtrar.
- **Nenhum `pytest.warns(SAWarning)`** — afirmaria como esperado um aviso que depende de coleta de lixo.
- **Nada no `pyproject.toml`.** `pytest-timeout>=2.3` já está declarado; faltava só instalar na venv local (D3).
- **Nada em `src/`.** O modelo e a PK não mudam.

## Verificação

```bash
./.venv/Scripts/python.exe -m pip install "pytest-timeout>=2.3"   # so a venv local
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/integration/test_message_model.py --tb=short
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

O critério da card é **zero warnings** na execução completa, e é o único que exige a suíte inteira: um warning de outro arquivo continuaria reprovando o critério mesmo com este teste limpo.

A suíte inteira uma vez, com o hash guardado. Se ela voltar com centenas de `CannotConnectNowError`, é a queda do Postgres que o CLAUDE.md descreve — rodar por blocos, não repetir o `-n 8`.

## Risco declarado

**O `expunge` poderia mascarar a regressão que o teste existe para pegar** — é a objeção óbvia, e a asserção da tarefa 2 é a resposta a ela. Sem a asserção, alguém poderia trocar `expunge` por algo que impedisse o `INSERT` de chegar ao banco e o teste continuaria verde. Com ela, qualquer caminho que não termine em violação de `message_telemetry_pkey` reprova.

**Segundo risco, menor:** instalar o `pytest-timeout` liga um teto de 120s por teste que nesta máquina não estava ligado, e no Windows o plugin mata o processo sem sumário ao estourar (CLAUDE.md). Se a suíte morrer sem sumário, é isso, e não esta card.

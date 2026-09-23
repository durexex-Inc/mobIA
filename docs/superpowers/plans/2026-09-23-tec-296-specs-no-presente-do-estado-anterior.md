# TEC-296 — Plano de implementação

**Desenho:** `docs/superpowers/specs/2026-09-23-tec-296-specs-no-presente-do-estado-anterior-design.md`
**Branch:** `feat/tec-296-specs-no-presente-do-estado-anterior`

Card de prosa: nenhum arquivo de `src/` ou `tests/` muda. O que muda são dois documentos em `docs/superpowers/specs/`, ambos de cards já mergeadas.

## Tarefa 0 — A conferência, feita antes de escrever (já executada no desenho)

Os quatro sítios do inventário conferidos contra o arquivo, por nome de evento e não por número de linha. Resultado na tabela do desenho, e ele muda o enunciado da card: **três dos quatro ganharam `motivo=str(falha)`; `catalogo.importacao_interrompida` não.**

Registrado aqui porque é a entrada das tarefas 1 e 2 — sem ela, o pretérito seria chute.

## Tarefa 1 — D1: a D4 da TEC-293

Arquivo: `docs/superpowers/specs/2026-09-20-tec-293-traceback-sem-mensagem-de-excecao-design.md`, seção `### D4`.

- `hoje têm **só** `exc_info=True`` → pretérito explícito, marcando que é o estado de antes da implementação **desta mesma card**.
- Cada um dos três sítios passa a levar o nome do evento ao lado do número.

O número de linha **permanece** (D4 do desenho). O que se acrescenta é a âncora que não deriva.

## Tarefa 2 — D2: a frase de inventário da TEC-292

Arquivo: `docs/superpowers/specs/2026-09-20-tec-292-log-sem-texto-de-excecao-de-terceiro-design.md`, seção `## O que o levantamento corrigiu no enunciado da card`.

- `que só têm` → `que então só tinham`.
- Os quatro eventos nomeados.

`Faltavam` já está no pretérito e fica como está.

## Tarefa 3 — D3: o cabeçalho da TEC-292

Mesmo arquivo, o bloco `> **Sobre os números de linha deste documento.**`

Ele promete uma única época e o `fba9f37` misturou duas. Passa a dizer o que é verdade: números de épocas diferentes, que derivam a cada merge, com o nome do evento como âncora confiável. A frase *"a conferência foi feita"* precisa dizer **quando**, senão reproduz o mesmo defeito num nível acima.

## Tarefa 4 — O que NÃO se faz

- **Não** atualizar os números para a árvore de hoje (D4 do desenho — já caducaram duas vezes em dois dias).
- **Não** tocar as specs da TEC-187 e da TEC-223, que o `fba9f37` também alterou. Fora do escopo desta card; declarado no desenho e no comentário da card.
- **Não** mexer em `src/`, `tests/`, `CLAUDE.md` ou `docs/srs/`. Nenhuma regra de produto muda.

## Verificação

Os três gates rodam mesmo sem mudança em código — o escopo deles não muda por causa do tipo da card, e uma execução limpa é o que prova que nada em `src/` foi tocado por acidente:

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

`comentarios_tocados.py` é o que mais importa aqui: a branch mexe em `.md` versionado que cita `arquivo.py:linha`, que é exatamente o insumo das marcas `PROSA`, `FALSO` e `NOMEIA`. Espera-se `PROSA` nas citações mantidas e **nenhum** `FALSO` — se aparecer `FALSO`, alguma citação aponta além do fim do arquivo e tem de ser resolvida antes do PR.

A suíte: `tests/unit` basta, e mesmo ela é formalidade. Nenhum arquivo importável muda.

## Risco declarado

Baixo, e de um tipo só: **apagar contexto histórico ao converter o tempo verbal**. O levantamento das duas specs é o que explica por que a TEC-293 decidiu o que decidiu — uma frase que vire "isso já não vale" sem dizer o que valia destrói a razão da decisão. O critério de pronto da card é explícito nisso, e cada edição tem de deixar o parágrafo legível como registro do que foi medido em 20/09.

# mobIA — instruções para agentes

Agente SDR imobiliário. FastAPI + SQLAlchemy async + ARQ, Postgres e Redis via `docker compose`.

## Os três gates estáticos, com os comandos exatos do CI

O job **Lint e tipos** (`.github/workflows/ci.yml`) roda estes três, nesta ordem. Rode os três antes de qualquer commit — **o formatador é um gate separado do linter, e passar num não diz nada sobre o outro**:

```bash
ruff check src tests alembic evals
ruff format --check src tests alembic evals
mypy src
```

**O escopo é `src tests alembic evals`, não `src tests`.** `alembic` entra porque as migrations importam código da aplicação (a `0004` chama `mobia.infra.crypto`); `evals` entra porque de outra forma ficaria fora de todo gate. O mypy segue só em `src` — cobrir `alembic` exige antes um `src/mobia/py.typed`.

Local, com a venv do projeto:

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals
./.venv/Scripts/python.exe -m mypy
```

> Histórico: a TEC-146 rodou 17 commits com `ruff check` limpo e nunca rodou `ruff format`. A `main` ficou vermelha depois do merge e precisou de um PR só para formatação. O linter passar não é evidência sobre o formatador.

## Testes

```bash
./.venv/Scripts/python.exe -m pytest          # suíte inteira
```

**A suíte é lenta, e lentidão aqui parece travamento.** Números medidos em 07/09/2026 (TEC-156): a suíte completa leva **~22 minutos e 1236 testes** em máquina ociosa. Com `-q` o pytest só imprime no fim, então um arquivo de saída vazio depois de dez minutos é normal, não deadlock. Para ver progresso, use `python -u -m pytest -v`.

**A suíte cresce rápido — confira a data antes de confiar no número.** Em 02/09/2026 eram 857 testes em ~7,5 minutos; em 04/09, 1140 em ~22 minutos. Quem lê um número velho como se fosse o de hoje mata execuções boas achando que travaram.

**Carga muda a duração em ordem de grandeza, não em percentual.** A mesma árvore que roda em 22 minutos levou **1h12** numa sessão em que onze subagentes já haviam rodado. Não compare durações entre execuções sem saber o que mais estava na máquina.

**Use `-q` só quando não for precisar do diagnóstico.** `-q` imprime apenas o `short test summary info` — o nome do teste que falhou, sem uma linha de traceback. Numa suíte de vinte minutos, descobrir a causa exige rodar tudo de novo. Se você vai ter de diagnosticar o resultado, peça `--tb=short` desde o início.

`addopts = "-m 'not perf'"` no `pyproject.toml` já exclui os testes de latência — medir p95 em runner compartilhado seria flake, não sinal.

## O banco demora mais que o healthcheck diz

Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` na negociação SSL — **com o container já marcado `healthy`**. Isso derruba a fixture de sessão `migrar_banco` e produz centenas de `ERROR` de setup que parecem catástrofe de código.

Não é. O socket cru já responde `N` ao SSLRequest e o `psql` interno funciona. Espere e retente antes de diagnosticar qualquer coisa.

**Testes de integração flakeiam sob carga, não isolados.** `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` falham com `ConnectionResetError` ou erro de Redis quando a suíte inteira roda junta, e passam 100% em isolamento. Antes de atribuir uma falha dessas a uma mudança sua, rode o arquivo sozinho.

**A evidência que fecha o argumento é a mesma árvore duas vezes.** Rodar isolado ajuda, mas não prova: um teste pode passar sozinho e falhar junto por um defeito real de isolamento. O que descarta regressão é o mesmo commit dando dois resultados — na TEC-156, `b35069d` passou 1236/1236 e, na execução seguinte sobre árvore idêntica e limpa, falhou 1. Guarde o hash junto com o resultado de cada execução.

**Cada tabela nova em `TABELAS` (`tests/conftest.py`) custa um `TRUNCATE ... CASCADE` por teste.** A fixture `banco_limpo` é autouse, então acrescentar duas tabelas numa suíte de 1200 testes são ~2.400 TRUNCATEs a mais. Não introduz incorreção, mas aumenta a contenção de lock que produz os flakes acima.

## Acentos: onde sim, onde não

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter nenhum — é responsabilidade de quem escreve.
- **Prosa em `docs/`, `README.md` e este arquivo: com acento**, normalmente.
- **Acento DENTRO de padrão regex é correto e intencional** — `milhões|milhão` em `domain/agente/dinheiro.py` existe porque leads digitam acento. Não "corrija".

## O orçamento do prompt é apertado e tem ritual

`SISTEMA_DO_AGENTE` (`domain/agente/classificador.py`) vai como bloco `system` com `cache_control` e é medido contra um teto **fixo** de 655 por `test_a_margem_do_orcamento_do_prompt_e_deliberada`. A margem se mede em unidades de token.

Antes de alongar o prompt ou mexer no schema compilado:

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

Quando ele reprova, a pergunta é **"o que sai do prompt para o novo texto entrar?"**, não "quanto subo o número?". Subir é resposta legítima, mas só depois da primeira pergunta. A docstring do teste guarda o histórico de cada vez que o teto se mexeu.

## Comentário não mente

Este repo comenta o **porquê**, não o quê, e trata comentário desatualizado como defeito, não como sujeira.

Não é retórica. Na TEC-146, um comentário em `_faixa_de` justificava a ordem de duas checagens com um perigo que não existia; ele escondeu um bug que gravava orçamento 40% abaixo do que o lead dissera, e sobreviveu a duas rodadas de revisão porque quem lia acreditava nele. Se você mudar código que um comentário descreve, o comentário muda junto ou some.

Mesma regra para a spec: emendas ao SRS (`docs/srs/`) entram como item aninhado **`Emenda E-nn (TEC-nnn, data)`** abaixo da regra que alteram, **nunca** reescrevendo o texto de 22/08/2026.

## Fluxo de trabalho

Card no Jira (projeto TEC) → desenho em `docs/superpowers/specs/` → plano em `docs/superpowers/plans/` → branch `feat/tec-nnn-<slug>` → PR contra `main`.

As cards são escritas antes da implementação e são a fonte de requisitos — **nunca chute número de card**. O SRS v1.0 está em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`; cite o arquivo, não a lembrança, porque as emendas mudam o que a regra diz sem mudar o número dela.

Mensagens de commit em português sem acento no assunto, no formato `tipo(TEC-nnn): o que passou a ser verdade`.

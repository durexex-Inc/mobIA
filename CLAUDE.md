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

**Números medidos em 12/09/2026, Python 3.13.15, máquina ociosa: a suíte completa leva ~2,5 minutos e são 1540 testes.** O número de 07/09/2026 (TEC-156), **~22 minutos**, está velho.

A referência menos ruidosa não é esta máquina, é o CI: o passo `Rodar a suite`, mesmo runner e mesmo Python, levava **168s** em `53f7e55` e passou a levar **71s** em `2e87349`. Localmente, no mesmo dia e no mesmo interpretador, a suíte inteira foi de **413,1s para 153,8s** e `tests/unit` de **227,0s para 5,7s**.

Nada disso explica sozinho a distância até os 22 minutos de setembro: parte veio das fixtures, parte do ambiente. Desconfie de qualquer número aqui que não diga em que máquina e em que Python foi medido — e prefira comparar durações de CI, que é o único lugar onde as duas pontas rodam igual.

Se ainda assim parecer travado: com `-q` o pytest só imprime no fim, então saída vazia por um tempo é normal, não deadlock. Para ver progresso, use `python -u -m pytest -v`.

**Rodar só a parte unitária não precisa de `docker compose` de pé.** `./.venv/Scripts/python.exe -m pytest tests/unit` roda os 988 testes em ~6s sem Postgres e sem Redis — é o loop certo enquanto se escreve código. `tests/integration` e `tests/features` continuam exigindo os containers.

**A suíte cresce rápido — confira a data antes de confiar no número.** Em 02/09/2026 eram 857 testes em ~7,5 minutos; em 04/09, 1140 em ~22 minutos. Quem lê um número velho como se fosse o de hoje mata execuções boas achando que travaram.

**Carga muda a duração em ordem de grandeza, não em percentual.** Quando a suíte levava 22 minutos ociosa, a mesma árvore levou **1h12** numa sessão em que onze subagentes já haviam rodado. O fator não some porque a suíte ficou mais rápida: ele multiplica o número de hoje do mesmo jeito. Não compare durações entre execuções sem saber o que mais estava na máquina.

**Use `-q` só quando não for precisar do diagnóstico.** `-q` imprime apenas o `short test summary info` — o nome do teste que falhou, sem uma linha de traceback. Descobrir a causa passa a exigir rodar tudo de novo, e agora que a regra é uma execução só (ver abaixo), jogar fora o traceback da única que você fez é o desperdício caro, não os minutos. Peça `--tb=short` desde o início.

`addopts = "-m 'not perf'"` no `pyproject.toml` já exclui os testes de latência — medir p95 em runner compartilhado seria flake, não sinal.

## O banco demora mais que o healthcheck diz

Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` na negociação SSL — **com o container já marcado `healthy`**. Isso derruba a fixture de sessão `migrar_banco` e produz centenas de `ERROR` de setup que parecem catástrofe de código.

Não é. O socket cru já responde `N` ao SSLRequest e o `psql` interno funciona. Espere e retente antes de diagnosticar qualquer coisa.

**E o `[WinError 64]` não é só do pós-restart.** Medido na TEC-263, com os containers de pé havia horas e a máquina ociosa: **5 falhas em ~100 iterações** do mesmo teste de integração — ~5% dos connects —, sempre na negociação SSL do `asyncpg` dentro da fixture, nunca numa asserção. Ele vem em rajada e depois desaparece: quatro de seis execuções falharam no começo da sessão e as 60 iterações seguintes passaram limpas. Uma suíte completa no mesmo dia deu 1313 passed e **1 `ERROR` de setup** com esse traceback, num arquivo unitário sem relação com a mudança, que passou 80/80 isolado.

Duas consequências práticas. Uma falha isolada com esse traceback **não autoriza conclusão nenhuma** — nem a favor nem contra a sua mudança. E um critério de aceite do tipo "passa nas 20 seguidas" pode ser inalcançável nesta máquina sem que nada esteja errado com o código: antes de culpar o que você escreveu, rode a versão ANTIGA o mesmo número de vezes.

**Testes de integração flakeiam sob carga, não isolados.** `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` falham com `ConnectionResetError` ou erro de Redis quando a suíte inteira roda junta, e passam 100% em isolamento. Antes de atribuir uma falha dessas a uma mudança sua, rode o arquivo sozinho.

**Rode a suíte inteira UMA vez.** Uma execução verde é o suficiente para seguir. Guarde o hash junto com o resultado.

A segunda execução não é ritual de rotina — é ferramenta de diagnóstico, e só quando a primeira **falha**. Aí ela é a única coisa que separa flake de regressão: rodar isolado ajuda mas não prova, porque um teste pode passar sozinho e falhar junto por um defeito real de isolamento. O precedente é a TEC-156, em que `b35069d` passou 1236/1236 e, na execução seguinte sobre árvore idêntica e limpa, falhou 1 — mesmo commit, dois resultados. Se a sua primeira execução falhou, repita sobre a mesma árvore antes de culpar a sua mudança.

**Cada tabela nova em `TABELAS` (`tests/conftest.py`) entra no `TRUNCATE ... CASCADE` de todo teste que toca banco.** Desde 12/09/2026 são duas coisas que já não valem do jeito antigo: `banco_limpo` sai cedo para `tests/unit/`, então os testes unitários não pagam nada; e a limpeza é **um** `TRUNCATE a, b, c CASCADE`, não um por tabela. Acrescentar uma tabela não custa mais um statement por teste — custa uma tabela a mais no mesmo statement, e mais um lock tomado junto com os outros. Continua valendo que isso aumenta a contenção que produz os flakes acima, só que numa escala bem menor.

## Acentos: onde sim, onde não

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter nenhum — é responsabilidade de quem escreve.
- **Prosa em `docs/`, `README.md` e este arquivo: com acento**, normalmente.
- **Acento DENTRO de padrão regex é correto e intencional** — `milhões|milhão` em `domain/agente/dinheiro.py` existe porque leads digitam acento. Não "corrija".

## O orçamento do prompt é apertado e tem ritual

`SISTEMA_DO_AGENTE` (`domain/agente/classificador.py`) vai como bloco `system` com `cache_control` e é medido contra um teto **fixo** por `test_a_margem_do_orcamento_do_prompt_e_deliberada`. A margem se mede em unidades de token.

**O teto não está escrito aqui de propósito.** Ele vive uma única vez, no corpo daquele teste, e a docstring de lá afirma ser "o unico numero desta conta escrito a mao em qualquer lugar" — uma segunda cópia neste arquivo tornaria essa frase falsa e envelheceria sozinha. Foi o que aconteceu: este parágrafo dizia 655 desde a TEC-257 e continuou dizendo depois que a TEC-265 gastou os 6,2 de folga restantes com a definição da ferramenta de busca em `tools=` (131,2 tokens), levando o teto a 786. Quem lesse 655 e medisse 780 concluiria que alguém estourou o orçamento em 125 tokens e iria procurar um problema que não existe. **Rode o comando abaixo para saber o teto de hoje; não confie em número transcrito em prosa.**

Antes de alongar o prompt ou mexer no schema compilado:

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

Quando ele reprova, a pergunta é **"o que sai do prompt para o novo texto entrar?"**, não "quanto subo o número?". Subir é resposta legítima, mas só depois da primeira pergunta. A docstring do teste guarda o histórico de cada vez que o teto se mexeu.

**São dois tetos, e eles são acoplados.** Além do fixo, `test_diferenca_entre_o_contado_e_o_enviado` afirma `subcontagem < contexto_headroom_de_tokens * 0,75`. O fixo é o deliberadamente mais apertado dos dois; **passá-lo do derivado o torna decorativo**, porque quem passa a prender é o outro — e aí a folga real não é a que o teste do teto fixo imprime. Antes de subir o fixo, calcule o derivado e confira que ele continua maior.

Subir `contexto_headroom_de_tokens` para abrir espaço **não é de graça**: a reserva sai do mesmo contexto que guarda a conversa do lead, e o comentário daquele campo em `app/config.py` registra que a última subida custou 180 tokens de literais e resumo **por turno**. Na TEC-141 a alternativa mais barata foi encurtar a frase até caber sob o derivado — e a versão curta acabou sendo a certa também pelo argumento semântico, não só pelo preço.

## Comentário não mente

Este repo comenta o **porquê**, não o quê, e trata comentário desatualizado como defeito, não como sujeira.

Não é retórica. Na TEC-146, um comentário em `_faixa_de` justificava a ordem de duas checagens com um perigo que não existia; ele escondeu um bug que gravava orçamento 40% abaixo do que o lead dissera, e sobreviveu a duas rodadas de revisão porque quem lia acreditava nele. Se você mudar código que um comentário descreve, o comentário muda junto ou some.

Mesma regra para a spec: emendas ao SRS (`docs/srs/`) entram como item aninhado **`Emenda E-nn (TEC-nnn, data)`** abaixo da regra que alteram, **nunca** reescrevendo o texto de 22/08/2026.

## Fluxo de trabalho

Card no Jira (projeto TEC) → desenho em `docs/superpowers/specs/` → plano em `docs/superpowers/plans/` → branch `feat/tec-nnn-<slug>` → PR contra `main`.

As cards são escritas antes da implementação e são a fonte de requisitos — **nunca chute número de card**. O SRS v1.0 está em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`; cite o arquivo, não a lembrança, porque as emendas mudam o que a regra diz sem mudar o número dela.

Mensagens de commit em português sem acento no assunto, no formato `tipo(TEC-nnn): o que passou a ser verdade`.

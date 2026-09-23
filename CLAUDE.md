# mobIA — instruções para agentes

Agente SDR imobiliário. FastAPI + SQLAlchemy async + ARQ, Postgres e Redis via `docker compose`.

## Os três gates estáticos, com os comandos exatos do CI

O job **Lint e tipos** (`.github/workflows/ci.yml`) roda estes três, nesta ordem. Rode os três antes de qualquer commit — **o formatador é um gate separado do linter, e passar num não diz nada sobre o outro**:

```bash
ruff check src tests alembic evals scripts
ruff format --check src tests alembic evals scripts
mypy
```

**O escopo é `src tests alembic evals scripts`, não `src tests`.** `alembic` entra porque as migrations importam código da aplicação (a `0004` chama `mobia.infra.crypto`); `evals` e `scripts` entram porque de outra forma ficariam fora de todo gate — e `scripts` de fato ficou, até 12/09/2026: quando entrou, o `ruff format --check` reprovou `gerar_base_simulada.py` de primeira. Desde a TEC-224 (20/09/2026) o mypy também cobre `alembic` — não porque o `py.typed` foi publicado, mas porque `[tool.mypy].files`, no `pyproject.toml`, lista `src` junto com `alembic`: com isso `mobia.*` resolve para os próprios arquivos-fonte e o PEP 561 nunca entra na conta. O `py.typed` (`src/mobia/py.typed`) continua valendo por outro motivo — limpa um `mypy alembic` isolado (sem ele, `import-untyped`) e publica a tipagem para quem consumir o wheel —, mas apagá-lo não tira `alembic` deste gate; apagar `src` do `files`, sim. Por isso o comando é `mypy` sem argumento, tanto local quanto no CI — argumento de linha de comando sobrepõe o `files` do `pyproject.toml`.

Local, com a venv do projeto:

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

> Histórico: a TEC-146 rodou 17 commits com `ruff check` limpo e nunca rodou `ruff format`. A `main` ficou vermelha depois do merge e precisou de um PR só para formatação. O linter passar não é evidência sobre o formatador.

## Testes

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile   # suíte inteira
./.venv/Scripts/python.exe -m pytest tests/unit             # só os unitários
./.venv/Scripts/python.exe -m pytest                        # serial, quando precisar
```

**Para a suíte inteira, use `-n 8 --dist loadfile`.** Medido em 12/09/2026, Python 3.13.15, máquina ociosa, 1614 testes: serial são **170,9s**, com `-n 8` são **~49s** (cinco execuções entre 48,7s e 51,1s). `-n 12` quase não melhora sobre o 8. O número de 07/09/2026 (TEC-156), ~22 minutos, está velho. Remedido em 19/09/2026, mesma máquina e mesmo Python, já com **2513 testes**: **67,0s** com `-n 8 --dist loadfile` — a suíte cresceu 56% e continuou abaixo de 70 segundos.

**Só que há dias em que `-n 8` não é executável aqui — ver "Quando o `-n 8` derruba o Postgres", abaixo.** Se a execução voltar com centenas de `ERROR` de setup, não repita o mesmo comando: o problema não é o código nem a sua branch, e insistir no mesmo `-n` só reproduz a queda.

`--dist loadfile` não é enfeite: mantém cada arquivo inteiro num worker só, preservando qualquer ordem interna de que um arquivo dependa. E cada worker roda contra uma base Postgres e um índice de Redis só dele — ver `_isolar_por_worker` em `tests/conftest.py`. Sem esse isolamento o paralelismo não é "mais rápido com algum flake", é vermelho: `banco_limpo` faz `TRUNCATE` e `redis_pool` faz `flushdb()`, e cada worker apagaria o estado dos outros.

**O `-n` não está no `addopts`, e não o ponha lá.** Paralelizar só compensa na suíte inteira: medido, `tests/unit` sozinho PIORA de 4,4s para 8,6s, porque a partida dos workers custa mais que os testes.

O teto é 16 workers — é quantos bancos lógicos um Redis serve por padrão, e cada worker precisa do seu. Acima disso o conftest reprova na hora, com a razão escrita.

A referência menos ruidosa não é esta máquina, é o CI: o passo `Rodar a suite`, mesmo runner e mesmo Python, levava **168s** antes das mudanças de fixture e passou a levar **71s** depois. O paralelismo rende bem menos lá que aqui — ~85s serial contra ~73s com `-n auto`, duas amostras de cada lado — porque o runner tem poucos cores e cada worker ainda paga um `alembic upgrade head` próprio. **O ganho do `-n` é da máquina de quem desenvolve, não do CI.**

Nada disso explica sozinho a distância até os 22 minutos de setembro: parte veio das fixtures, parte do ambiente. Desconfie de qualquer número aqui que não diga em que máquina e em que Python foi medido — e, ao comparar durações de CI, colha mais de uma amostra: uma execução da `main` marcou 29s num dia em que as vizinhas marcaram 80 e 89.

Se ainda assim parecer travado: com `-q` o pytest só imprime no fim, então saída vazia por um tempo é normal, não deadlock. Para ver progresso, use `python -u -m pytest -v`.

**Rodar só a parte unitária não precisa de `docker compose` de pé.** `./.venv/Scripts/python.exe -m pytest tests/unit` roda os 1027 testes em ~4,4s sem Postgres e sem Redis — é o loop certo enquanto se escreve código, e sem `-n`. `tests/integration` e `tests/features` continuam exigindo os containers.

**A suíte cresce rápido — confira a data antes de confiar no número.** Em 02/09/2026 eram 857 testes em ~7,5 minutos; em 04/09, 1140 em ~22 minutos. Quem lê um número velho como se fosse o de hoje mata execuções boas achando que travaram.

**Carga muda a duração em ordem de grandeza, não em percentual.** Quando a suíte levava 22 minutos ociosa, a mesma árvore levou **1h12** numa sessão em que onze subagentes já haviam rodado. O fator não some porque a suíte ficou mais rápida: ele multiplica o número de hoje do mesmo jeito. Não compare durações entre execuções sem saber o que mais estava na máquina.

**Use `-q` só quando não for precisar do diagnóstico.** `-q` imprime apenas o `short test summary info` — o nome do teste que falhou, sem uma linha de traceback. Descobrir a causa passa a exigir rodar tudo de novo, e agora que a regra é uma execução só (ver abaixo), jogar fora o traceback da única que você fez é o desperdício caro, não os minutos. Peça `--tb=short` desde o início.

`addopts = "-m 'not perf'"` no `pyproject.toml` já exclui os testes de latência — medir p95 em runner compartilhado seria flake, não sinal.

## O banco demora mais que o healthcheck diz

Depois de `docker compose restart`, o `alembic upgrade head` reprova por vários segundos com `ConnectionResetError [WinError 64]` na negociação SSL — **com o container já marcado `healthy`**. Isso derruba a fixture de sessão `migrar_banco` e produz centenas de `ERROR` de setup que parecem catástrofe de código.

Não é. O socket cru já responde `N` ao SSLRequest e o `psql` interno funciona. Espere e retente antes de diagnosticar qualquer coisa.

**E o `[WinError 64]` não é só do pós-restart.** Medido na TEC-263, com os containers de pé havia horas e a máquina ociosa: **5 falhas em ~100 iterações** do mesmo teste de integração — ~5% dos connects —, sempre na negociação SSL do `asyncpg` dentro da fixture, nunca numa asserção. Ele vem em rajada e depois desaparece: quatro de seis execuções falharam no começo da sessão e as 60 iterações seguintes passaram limpas. Uma suíte completa no mesmo dia deu 1313 passed e **1 `ERROR` de setup** com esse traceback, num arquivo unitário sem relação com a mudança, que passou 80/80 isolado.

**E ele tem um irmão do lado do servidor, que é o mesmo evento (TEC-130, 23/09/2026).** Quando o socket some, o backend do Postgres morre com `signal 13: Broken pipe`, o postmaster derruba todos os outros e entra em crash recovery — e aí o sintoma deixa de ser um `ERROR` isolado e passa a ser `CannotConnectNowError` em centenas de testes seguidos. Ver a emenda na seção "Quando o `-n 8` derruba o Postgres", que tem o método de diagnóstico e a armadilha do `pg_postmaster_start_time()`. **A regra prática**: `[WinError 64]` avulso é ruído e se ignora; dezenas de `CannotConnectNowError` de uma vez é o banco caído, e insistir na mesma execução não adianta.

Duas consequências práticas. Uma falha isolada com esse traceback **não autoriza conclusão nenhuma** — nem a favor nem contra a sua mudança. E um critério de aceite do tipo "passa nas 20 seguidas" pode ser inalcançável nesta máquina sem que nada esteja errado com o código: antes de culpar o que você escreveu, rode a versão ANTIGA o mesmo número de vezes.

**Testes de integração flakeiam sob carga, e rodar o arquivo sozinho é o primeiro diagnóstico — mas isso depende da máquina.** `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` falham com `ConnectionResetError` ou erro de Redis quando a suíte inteira roda junta. Em isolamento, as duas medições que existem discordam, e as duas estão certas:

| quando | onde | resultado |
| --- | --- | --- |
| 09/09/2026 (TEC-268) | máquina anterior | `test_dedup_por_message_id.py` sozinho reprovou **3 de 5**, com `redis.exceptions.ConnectionError` em `localhost:6380` — WinError 64 no **Redis**, não no Postgres |
| 20/09/2026 (TEC-268) | máquina atual | **75 execuções isoladas** dos quatro arquivos, **0 falhas** (30 do dedup, 15 de cada um dos outros) |

**Então "passa isolado" é evidência forte, não prova** — e "reprova isolado" não é prova de regressão sua. Antes de atribuir a falha à sua mudança, rode o arquivo sozinho; se ele reprovar, rode a versão ANTIGA o mesmo número de vezes antes de concluir qualquer coisa. Foi por isso que a TEC-162 e a TEC-159 usaram comparação contra **baseline numerado** em vez de "suíte verde" como critério de aceite.

Para saber se a propriedade vale na SUA máquina, não confie nesta tabela — refaça a conta em ~13 minutos:

```bash
./.venv/Scripts/python.exe scripts/taxa_de_flake.py
```

## Quando o `-n 8` derruba o Postgres

Medido na TEC-229, 17-18/09/2026. O banco **crasha** sob o paralelismo e entra em recovery, rejeitando todo connect por dezenas de minutos — com o compose reportando `unhealthy`, não `healthy`. Não é o falso-alarme da seção acima, que passa em segundos: aqui o container ficou **37 minutos** inacessível.

A correlação com o `-n` é direta, e é o que identifica o caso:

| execução | passed | errors | causa dominante |
| --- | --- | --- | --- |
| `-n 8` | 1391 | 967 | banco em recovery 37 min |
| `-n 8`, depois de `restart` | 1820 | 535 | 532 × `CannotConnectNowError` |
| `-n 4` | 2089 | 267 | 223 × `CannotConnectNowError` |
| serial, por blocos | 2358 | 0 | — |

**A cura é baixar o paralelismo, não esperar.** `docker compose restart postgres` devolve o banco, e ele torna a cair na execução seguinte se o `-n` continuar alto — foi o que aconteceu duas vezes seguidas. O que fecha verde é rodar **por blocos**, que ainda tem a vantagem de um travamento não custar o resultado dos outros:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short -q
./.venv/Scripts/python.exe -m pytest tests/features --tb=short -q
```

**O `pytest` serial pode travar de vez, e isso não é a lentidão conhecida.** Na mesma sessão, uma execução serial congelou logo depois de uma falha em `test_reserva_liberada.py` e ficou **~10 horas** parada; dois processos Python vivos, um com **CPU zerada**, e o banco `healthy` o tempo todo. O aviso do `-q` (saída vazia é normal) **não cobre este caso**: o log tinha avançado até 31% e simplesmente parou.

Distinguir travamento de lentidão é barato e leva dois comandos — compare o mtime do log com o relógio e olhe o CPU acumulado:

```bash
stat -c '%y' /tmp/suite.log; date
```
```powershell
Get-Process python* | Select-Object Id, StartTime, CPU
```

Log parado há horas **mais** CPU parada é deadlock: mate os processos e rode por blocos.

**Desde a TEC-291 um travamento à espera de lock se denuncia sozinho, em segundos, e diz quem o causou.** O `TRUNCATE` de `banco_limpo` era o ponto onde qualquer contenção virava espera infinita — ele pede `ACCESS EXCLUSIVE` nas 19 tabelas de `TABELAS` antes de cada teste que toca banco, e basta um backend com um `SELECT` de transação aberta, um `ACCESS SHARE`, para pendurar a suíte. Agora ele tem `lock_timeout` e, ao estourar, consulta `pg_locks` e reprova nomeando o bloqueador:

```
RuntimeError: o TRUNCATE de `banco_limpo` esperou mais de 10s por lock, no setup de
tests/integration/test_health.py::test_health_responde_ok.
Quem segura:
  pid 1686082  idle in transaction  transacao aberta ha 00:00:18  SELECT count(*) FROM imoveis
```

Medido em 19/09/2026: essa condição, que antes esperava para sempre, passou a reprovar em **11,4s**. Se você vir essa mensagem, o diagnóstico já está feito — não rode nada de novo, leia a consulta do bloqueador e ache o teste que a emite.

**E há um teto por teste: `timeout = 120` no `pyproject.toml`** — **quando o `pytest-timeout` está instalado, e em 23/09/2026 ele não estava.** Confira antes de contar com o teto: sem o plugin, o pytest emite `PytestConfigWarning: Unknown config option: timeout` em toda execução e **nenhum teste tem teto nenhum**. O aviso passa despercebido no meio do resumo, e a consequência é a que este parágrafo descreve ao contrário — a execução não morre, ela pendura. `pip install pytest-timeout` resolve; é o mesmo padrão do `pytest-xdist` logo abaixo e do `aiosmtplib` da TEC-298. Com o plugin instalado, o teto cobre setup, teste e teardown, e vale para o travamento que não é espera de lock. **O comportamento difere entre esta máquina e o CI, e a diferença engana**: no CI (`ubuntu-latest`) o método é `signal`, o teste falha e a execução continua; **no Windows é `thread`, e o plugin despeja a pilha de todas as threads em stderr e mata o processo com `os._exit()`** — sem teardown e sem sumário final. Execução que morre sem sumário aqui é o teto funcionando, e a pilha despejada é o diagnóstico.

Os dois comandos acima continuam valendo para o que nenhum teto cobre: o processo parado sem esperar lock e sem estourar o teto por teste.

**O que a TEC-291 mediu e NÃO encontrou, para não se procurar de novo** — sobre `c9541d8`, 19/09/2026, nesta máquina:

- `tests/integration` inteiro fechou em **943 passed / 229s**, com `pg_blocking_pids` amostrado a cada 10s: **nenhum bloqueio**. O travamento é intermitente, não permanente.
- **Esgotamento de pool está descartado**: o `pool_timeout` do SQLAlchemy é 30s e **levanta** `TimeoutError`. Pool cheio não produz espera infinita, produz traceback em 30s.
- **Tarefa abandonada segurando transação não vaza conexão.** Quatro formas exercitadas — `cancel()` sem `await` com a tarefa dormindo, o mesmo com consulta em voo, tarefa nunca cancelada, e cancelamento esperando lock de linha repetido 40 vezes — todas passam. No fim de cada teste o `pytest-asyncio` drena as tarefas pendentes e o SQLAlchemy chama `asyncpg.terminate()`, que fecha o socket: o backend morre e solta os locks.
- **A causa das duas ocorrências de 17-18/09 continua desconhecida.** Não reproduziu. O que mudou é que a próxima se explica sozinha.
  - **Emenda (TEC-130, 23/09/2026): a causa da QUEDA tem nome, e está no log do container.** `docker logs mobia-postgres-1` mostra `server process (PID nnnn) was terminated by signal 13: Broken pipe`, seguido de `all server processes terminated; reinitializing` e `database system was not properly shut down; automatic recovery in progress`. Um backend morre com SIGPIPE — o socket do cliente some no meio de uma escrita —, o postmaster derruba todos os outros e entra em crash recovery, e a partir daí **toda** conexão leva `CannotConnectNowError` por minutos. **É o mesmo evento que o `[WinError 64]`, visto da outra ponta do socket**: o cliente vê a rede sumir, o servidor leva SIGPIPE. As duas seções deste arquivo descrevem um fenômeno só.
  - **`pg_postmaster_start_time()` NÃO muda nisso, e isso engana.** O reset é dos backends, não do postmaster, então o horário de início continua o mesmo depois da queda — e quem o usa para testar a hipótese conclui que o banco nunca caiu. Foi o que aconteceu na TEC-130: a hipótese ambiental foi descartada cedo demais por causa desse sinal. Para detectar, olhe o log do container ou `pg_is_in_recovery()` **durante** a queda.
  - **Aconteceu seis vezes em 23/09, sem `-n` nenhum**, sempre em execução serial longa. Três execuções de `tests/integration` voltaram com **453, 569 e 573 erros**, quase todos `CannotConnectNowError`, e nenhum deles de domínio. O mesmo commit, rodado em **sete fatias** de ~15 arquivos com o banco reiniciado entre elas, deu **1118 passed e zero falhas**. Uma queda no meio de uma execução única envenena tudo o que vem depois; em fatias, ela custa uma fatia.

**`pytest-xdist` pode não estar instalado, apesar de declarado no `pyproject.toml`.** Se `-n 8` reprovar com `unrecognized arguments`, é isso — `pip install pytest-xdist` resolve. Não conclua que o comando desta seção está errado.

**`relation ... does not exist` em dezenas de testes quase nunca é a sua migration — são os bancos dos workers com o carimbo adiantado.** Cada worker tem o seu (`mobia_gw0` … `mobia_gw7`), e eles **persistem entre sessões**. Se um `alembic upgrade` for interrompido no meio — uma queda de conexão, um `[WinError 64]` na hora errada, uma troca de branch entre execuções —, o banco fica com `alembic_version` já no head e **sem o DDL correspondente**. A fixture `migrar_banco` não pega isso: para ela, carimbo no head significa nada a fazer.

O sintoma engana de propósito: dezenas de falhas, todas dizendo que uma tabela recém-criada não existe, exatamente na branch que a criou. Em 12/09/2026 foram 34 falhas que se repetiram idênticas numa segunda execução — ou seja, **nem a regra do "rode de novo antes de culpar sua mudança" separa este caso**, porque ele não é flake: é estado errado e determinístico.

Confirme antes de mexer em código: conecte num banco de worker e compare `SELECT version_num FROM alembic_version` com a existência da tabela que falta. Batendo a suspeita, o conserto é por banco — `alembic stamp` para a revisão anterior e `upgrade head` de novo, nos oito. Um `-n 2` reproduz em dois bancos e é bem mais barato para diagnosticar que a suíte inteira.

**Rode a suíte inteira UMA vez.** Uma execução verde é o suficiente para seguir. Guarde o hash junto com o resultado.

A segunda execução não é ritual de rotina — é ferramenta de diagnóstico, e só quando a primeira **falha**. Aí ela é a única coisa que separa flake de regressão: rodar isolado ajuda mas não prova, porque um teste pode passar sozinho e falhar junto por um defeito real de isolamento. O precedente é a TEC-156, em que `b35069d` passou 1236/1236 e, na execução seguinte sobre árvore idêntica e limpa, falhou 1 — mesmo commit, dois resultados. Se a sua primeira execução falhou, repita sobre a mesma árvore antes de culpar a sua mudança.

**Cada tabela nova em `TABELAS` (`tests/conftest.py`) entra no `TRUNCATE ... CASCADE` de todo teste que toca banco.** Desde 12/09/2026 são duas coisas que já não valem do jeito antigo: `banco_limpo` sai cedo para `tests/unit/`, então os testes unitários não pagam nada; e a limpeza é **um** `TRUNCATE a, b, c CASCADE`, não um por tabela. Acrescentar uma tabela não custa mais um statement por teste — custa uma tabela a mais no mesmo statement, e mais um lock tomado junto com os outros. Continua valendo que isso aumenta a contenção que produz os flakes acima, só que numa escala bem menor.

## Acentos: onde sim, onde não

- **Texto que o lead recebe: português COM acento** (TEC-267). Vale para todo literal que chega ao lead — a ficha de imóvel, os avisos, os fallbacks. A razão é que o modelo já escreve acentuado e nada normaliza a saída dele: manter os literais sem acento não produzia uniformidade, produzia metade da conversa com cara de descuido. **Prompt de sistema não conta** — é instrução para o modelo, não texto de produto, e continua sem acento.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento** (exceto valor citado — ver abaixo). Convenção do repo, não checada por linter nenhum — é responsabilidade de quem escreve. Nenhum linter checa esta fronteira nem a de cima.
- **Prosa em `docs/`, `README.md` e este arquivo: com acento**, normalmente.
- **Acento DENTRO de padrão regex é correto e intencional** — `milhões|milhão` em `domain/agente/dinheiro.py` existe porque leads digitam acento. Não "corrija".
- **Valor citado dentro de comentário não segue a convenção do comentário — segue o valor, qualquer que seja o delimitador.** Uma docstring pode citar o que o lead vê entre crases (`` `Condomínio` ``), entre aspas duplas ("Condomínio") ou sem delimitador nenhum — o delimitador é irrelevante, o que importa é estar citando um valor real. A citação tem de bater com o literal, mesmo estando num comentário que por convenção não leva acento: a regra sem acento é sobre a **prosa**; a citação é sobre o **produto**, e uma citação que não bate mente sobre o que o usuário recebe. A TEC-267 achou mais de dez sítios assim, espalhados pelas três convenções, depois de já ter varrido o repo três vezes.

## O orçamento do prompt é apertado e tem ritual

`SISTEMA_DO_AGENTE` (`domain/agente/classificador.py`) vai como bloco `system` com `cache_control` e é medido contra um teto **fixo** por `test_a_margem_do_orcamento_do_prompt_e_deliberada`. A margem se mede em unidades de token.

**O teto não está escrito aqui de propósito.** Ele vive uma única vez, no corpo daquele teste, e a docstring de lá afirma ser "o unico numero desta conta escrito a mao em qualquer lugar" — uma segunda cópia neste arquivo tornaria essa frase falsa e envelheceria sozinha. Foi o que aconteceu: este parágrafo dizia 655 desde a TEC-257 e continuou dizendo depois que a TEC-265 gastou os 6,2 de folga restantes com a definição da ferramenta de busca em `tools=` (131,2 tokens), levando o teto a 786. Quem lesse 655 e medisse 780 concluiria que alguém estourou o orçamento em 125 tokens e iria procurar um problema que não existe. **Rode o comando abaixo para saber o teto de hoje; não confie em número transcrito em prosa.**

Antes de alongar o prompt ou mexer no schema compilado:

```bash
./.venv/Scripts/python.exe -m pytest -q -k margem_do_orcamento -s
```

Quando ele reprova, a pergunta é **"o que sai do prompt para o novo texto entrar?"**, não "quanto subo o número?". Subir é resposta legítima, mas só depois da primeira pergunta. A docstring do teste guarda o histórico de cada vez que o teto se mexeu.

**São dois tetos, e eles são acoplados.** Além do fixo, `test_diferenca_entre_o_contado_e_o_enviado` afirma `subcontagem < contexto_headroom_de_tokens * 0,75`. O fixo é o deliberadamente mais apertado dos dois; **passá-lo do derivado o torna decorativo**, porque quem passa a prender é o outro — e aí a folga real não é a que o teste do teto fixo imprime. Antes de subir o fixo, calcule o derivado e confira que ele continua maior.

Subir `contexto_headroom_de_tokens` para abrir espaço **não é de graça**: a reserva sai do mesmo contexto que guarda a conversa do lead, e o comentário daquele campo em `app/config.py` registra que a última subida custou 640 tokens de literais e resumo **por turno** (TEC-225, a primeira derivada de medição contra o contador real, não de aritmética sobre o proxy `len/4`). Na TEC-141 a alternativa mais barata foi encurtar a frase até caber sob o derivado — e a versão curta acabou sendo a certa também pelo argumento semântico, não só pelo preço.

## Comentário não mente

Este repo comenta o **porquê**, não o quê, e trata comentário desatualizado como defeito, não como sujeira.

Não é retórica. Na TEC-146, um comentário em `_faixa_de` justificava a ordem de duas checagens com um perigo que não existia; ele escondeu um bug que gravava orçamento 40% abaixo do que o lead dissera, e sobreviveu a duas rodadas de revisão porque quem lia acreditava nele. Se você mudar código que um comentário descreve, o comentário muda junto ou some.

**Antes do PR, rode a listagem:**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --tudo   # sem o teto
```

Ela lista os comentários e docstrings que a branch precisa reconferir, em cinco marcas. As duas primeiras são sobre comentário dentro do código: `ALTERADO` é o que mudou no diff. **`VIZINHO` é o que não mudou, mas está dentro de um `def`/`class` cujo código mudou — ou é a docstring de módulo de um arquivo que mudou por baixo dela (TEC-283)** — e é essa a categoria que pega o defeito da TEC-146, porque um comentário que ninguém editou não aparece no diff e por isso ninguém o relê.

**Desde a TEC-283 a docstring de módulo entra no mesmo alcance.** Ela é a prosa que mais sobrevive a refatoração, porque não está dentro de nenhum `def` e nenhuma edição a arrasta junto — foi assim que a docstring de `tests/unit/test_comentarios_tocados.py` seguiu creditando só a TEC-277 enquanto aquela branch crescia o arquivo em 410 linhas. Medido sobre os 20 merges mais recentes: o acréscimo é de **32 achados em 131 arquivos tocados**, mediana de 0 por branch e máximo de 11 — 44% dos arquivos tocados não têm docstring de módulo, e entre os que têm, 56% já a editam na mesma branch.

**Desde a TEC-282 a listagem também aponta a prosa.** `PROSA` é um `.md` versionado que cita `arquivo.py:linha` de um arquivo que a branch mexeu — suspeita, não veredito. `FALSO` é, entre essas citações que já apontam arquivo que a branch mexeu, a que aponta além do fim dele — a única marca que afirma em vez de suspeitar. `NOMEIA` é o documento que nomeia um script que a branch alterou, e existe por um caso concreto: o merge da TEC-277 (`a66de07`, 14/09 21:29:10) tornou este arquivo falso, e nada apontou — o conserto (`a3db8c2`) veio três minutos e quinze segundos depois, e só porque alguém ainda estava relendo a seção.

**Planos de implementação ficam de fora, de propósito.** Um plano registra o que se fez num dia; envelhecer é o esperado dele. Medido na TEC-282, incluí-los levaria a mediana por branch de 9 para 39 citações — sem apontar nada que ainda afirme algo sobre o código de hoje.

**A saída padrão não é completa, e isso é deliberado (TEC-277).** Ela mostra os cinco `VIZINHO` mais próximos do que mudou em cada bloco e resume o resto numa linha que nomeia o bloco e conta o que omitiu; `--tudo` devolve a listagem inteira. O motivo é medido: sem teto, a saída tinha mediana de **890 linhas** e chegava a 1928 — volume que treina quem lê a ignorar, que é o oposto do que a ferramenta existe para fazer. Com o teto, a mediana é **188**.

A seção de prosa que a TEC-282 acrescentou tem o próprio teto, pela mesma razão: corta em cinco `PROSA` por documento e resume o resto como `... +N citação(ões) omitida(s) -- use --tudo`. `FALSO` e `NOMEIA` escapam desse corte pela mesma razão que `ALTERADO` escapa do teto de `VIZINHO` acima — nenhuma das três é ruído de vizinhança.

`ALTERADO` nunca é cortado, então numa branch que reescreve muito é ele que domina o que resta. E a contagem do rodapé conta o que **existe**, não o que coube na tela: se ela disser 715 e você tiver lido 12, os outros 703 estão atrás do `--tudo`.

O teto existe porque não há regra melhor, e isso também foi medido: **75,9% do ruído vem de `executar_turno`**, que tem 2706 linhas, e dentro dela todo comentário está longe de toda edição. Uma regra de vizinhança por distância deixa 65,9% de pé num raio de 50 linhas. Enquanto aquela função não for partida, esta listagem vive de teto.

Não é gate e não reprova nada: decidir sozinho se um comentário está certo é justamente o julgamento que ele existe para devolver a uma pessoa. Medido no histórico: **~51 commits** existem só para corrigir afirmação que o próprio repo escreveu errado antes — a regra acima já existia e mesmo assim não pegava, porque nenhum dos três gates olha para comentário.

Mesma regra para a spec: emendas ao SRS (`docs/srs/`) entram como item aninhado **`Emenda E-nn (TEC-nnn, data)`** abaixo da regra que alteram, **nunca** reescrevendo o texto de 22/08/2026.

## Fluxo de trabalho

Card no Jira (projeto TEC) → **mover para Fazendo e pôr Eduardo como responsável** → desenho em `docs/superpowers/specs/` → plano em `docs/superpowers/plans/` → branch `feat/tec-nnn-<slug>` → PR contra `main` → **comentar na card e mover para Em análise**.

**Antes de começar, mova a card para "Fazendo" e ponha Eduardo como responsável.** Antes do desenho, não depois de escrever código: enquanto a card não se mexe, o quadro diz que ninguém pegou o trabalho, e quem olha não consegue distinguir uma card parada de uma card em curso. É a primeira ação da sequência acima, não um acerto de contas no fim.

O responsável é **`eduardodurieuxlopes@gmail.com`** — a conta do Jira, que não é a mesma identidade do git (`eduardo.lopes@instivo.com.br`). Resolva o account ID por `lookupJiraAccountId` a partir desse e-mail em vez de guardar o ID aqui: ID copiado para prosa é o tipo de dado que ninguém revalida quando muda.

**Trabalho de card termina SEMPRE em `git push` e PR. Nunca em merge local, e nunca numa pergunta sobre o que fazer com a branch.** Não há opção "mergear direto na `main`", não há opção "deixo a branch e você resolve": terminou a implementação e a suíte fechou, faz o push e abre o PR. Perguntar qual das três o Eduardo prefere é devolver a ele uma decisão que este arquivo já tomou.

A razão é o que o PR carrega e o merge local joga fora: o diff revisável, o comentário da card apontando para ele, e o CI rodando contra o mesmo commit que vai entrar. Uma branch mergeada localmente chega na `main` sem nada disso — e uma branch que fica parada na máquina de quem escreveu não existe para mais ninguém.

Quem mergeia o PR é o Eduardo. **Depois do merge, a limpeza local é sua**: confirme com `git merge-base --is-ancestor <hash> origin/main` antes de relatar qualquer coisa — o PR pode ter sido mergeado antes do seu último push —, volte para a `main`, dê `pull`, e apague a branch local.

**Ao abrir o PR, a card recebe um comentário e vai para "Em análise".** Não para "Feito": quem mergeia é que fecha. Uma card em "Fazendo" com PR aberto mente sobre onde o trabalho está — e quem olha o quadro não tem como saber que já existe algo para revisar.

O comentário não é um "pronto, segue o PR". Ele existe para registrar o que **some se ficar só no PR**, porque a card é o que alguém vai reler daqui a seis meses:

- **Toda divergência em relação ao texto da card**, com o porquê. Se a implementação separou em dois o que a card juntava, ou escolheu outra chave, ou decidiu uma regra que a card não decidia, está aí.
- **Critério de aceite que não foi exercitado**, e a razão. Melhor a card dizer que o critério ficou sem teste do que o revisor descobrir sozinho — ou, pior, do que um teste inventar a entidade que falta só para se auto-satisfazer.
- **Lacuna que é decisão de produto, não de código.** Comportamento que decorre do desenho aprovado e que talvez não seja o desejado. Quem decide isso não lê `docs/superpowers/specs/`.
- **O que a card não entrega**, com a consequência prática dita sem rodeio. Na TEC-174, "a notificação é outra card" significa que *nada notifica ninguém ainda* — e foi por isso que o texto que o lead recebe teve de ser reescrito, porque a primeira versão dizia "já avisei um corretor".

As emendas ao SRS entram no comentário também, nomeadas: quem revisa precisa saber que a spec mudou.

As cards são escritas antes da implementação e são a fonte de requisitos — **nunca chute número de card**. O SRS v1.0 está em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`; cite o arquivo, não a lembrança, porque as emendas mudam o que a regra diz sem mudar o número dela.

Mensagens de commit em português sem acento no assunto, no formato `tipo(TEC-nnn): o que passou a ser verdade`.

# TEC-229 — O pior turno derivado da configuração: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer `_PIOR_TURNO` derivar a contagem de chamadas de `contexto_max_iteracoes` e `contexto_gatilho_de_regeneracao`, remover a asserção falsa de `test_job_timeout_cabe_dentro_da_janela_do_sweeper`, e registrar com `xfail(strict=True)` que o orçamento resultante não cabe no `job_timeout`.

**Architecture:** Três mudanças independentes, cada uma com commit próprio. A primeira troca a tupla de constantes `_PIOR_TURNO` por uma função que lê `get_settings()`, o que eleva a parcela da Anthropic de 162s para 287s e obriga os dois testes de soma a virarem `xfail`. A segunda limpa o teste de integração que afirma o modelo antigo do turno. A terceira corrige toda a prosa que afirma que a conta fecha.

**Tech Stack:** Python 3.13, pytest, pydantic-settings, ARQ.

**Spec:** `docs/superpowers/specs/2026-09-17-tec-229-pior-turno-derivado-da-configuracao-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceção: valor citado que o lead recebe segue o literal, com acento.
- **Prosa em `docs/`: com acento.**
- Os três gates estáticos rodam no escopo `src tests alembic evals scripts`:
  `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`.
  Localmente: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, idem `ruff format --check`, e `./.venv/Scripts/python.exe -m mypy`.
- Mensagens de commit: `tipo(TEC-229): o que passou a ser verdade`, assunto em português sem acento.
- Rodar `tests/unit` não precisa de `docker compose`. `tests/integration` precisa.
- **Nenhum número de teto ou de soma é escrito à mão em teste.** Tudo é importado de quem define ou derivado da configuração. É o defeito que esta card existe para matar.

---

### Task 1: `_PIOR_TURNO` lê a configuração, e os dois testes de soma viram `xfail`

**Files:**
- Modify: `src/mobia/infra/anthropic.py:93-116` (a tupla `_PIOR_TURNO` e `segundos_do_modelo_no_pior_turno`)
- Test: `tests/unit/test_orcamento_do_turno.py`

**Interfaces:**
- Consumes: `get_settings()` de `mobia.app.config`, campos `contexto_max_iteracoes: int` e `contexto_gatilho_de_regeneracao: int`.
- Produces: `_pior_turno() -> tuple[tuple[float, int], ...]` (privada, substitui a constante `_PIOR_TURNO`). A assinatura pública `segundos_do_modelo_no_pior_turno() -> float` **não muda** — todos os consumidores atuais seguem válidos.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `tests/unit/test_orcamento_do_turno.py`. Os imports novos (`pytest`, `TETO_DO_COUNT_TOKENS`, `TETO_DO_RESUMO`, `MAX_TENTATIVAS`, `get_settings`) entram no bloco de imports do topo do arquivo.

```python
def test_o_pior_turno_segue_contexto_max_iteracoes(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Subir o teto de iteracoes da montagem tem de mover o pior caso.

    E o criterio de pronto que a TEC-229 existe para fechar. Ate ela,
    `_PIOR_TURNO` contava `resumir` e `count_tokens` uma vez cada: dobrar
    `contexto_max_iteracoes` nao mexia em numero nenhum, e o laco de
    `montar_contexto` -- que roda ate esse teto, com um `resumir` e uma
    contagem por volta -- ficava fora da conta.

    **Enquanto a TEC-290 nao fechar o orcamento, este e o unico teste verde
    que guarda a derivacao.** Os dois que somam estao `xfail`, entao subir um
    teto ou uma iteracao nao os torna vermelhos -- eles ja sao. Se este aqui
    for apagado junto com aquela card, a derivacao volta a poder ser trocada
    por constantes sem nada perceber.

    O delta e afirmado exato, e nao so "maior": uma iteracao a mais custa
    UMA dobra e UMA contagem. Afirmar `>` passaria tambem se a implementacao
    multiplicasse a fatia errada.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv("CONTEXTO_MAX_ITERACOES", str(get_settings().contexto_max_iteracoes + 1))
    get_settings.cache_clear()

    uma_volta_a_mais = (TETO_DO_RESUMO + TETO_DO_COUNT_TOKENS) * (MAX_TENTATIVAS + 1)
    assert segundos_do_modelo_no_pior_turno() - antes == uma_volta_a_mais


def test_o_pior_turno_segue_o_gatilho_de_regeneracao(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O termo do truncamento tambem e derivado, e cresce em log.

    `_truncar_ate_caber` corta a janela pela metade a cada volta, entao
    dobrar o gatilho acrescenta UMA contagem, nao o dobro delas. O teste
    afirma essa forma: se alguem trocar o `log2` por multiplicacao, a
    igualdade quebra.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv(
        "CONTEXTO_GATILHO_DE_REGENERACAO",
        str(get_settings().contexto_gatilho_de_regeneracao * 2),
    )
    get_settings.cache_clear()

    um_corte_a_mais = TETO_DO_COUNT_TOKENS * (MAX_TENTATIVAS + 1)
    assert segundos_do_modelo_no_pior_turno() - antes == um_corte_a_mais
```

- [ ] **Step 2: Rodar para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_orcamento_do_turno.py -v --tb=short
```

Esperado: os dois testes novos FALHAM com `assert 0.0 == 30.0` e `assert 0.0 == 5.0` — o pior turno não se move porque `_PIOR_TURNO` é constante. Os três antigos continuam PASSANDO.

- [ ] **Step 3: Trocar a tupla por função derivada**

Em `src/mobia/infra/anthropic.py`, acrescentar `import math` no topo (antes de `from functools import lru_cache`; `ruff` ordena a stdlib junta) e substituir o bloco `_PIOR_TURNO = (...)` inteiro, comentário incluso, por:

```python
# O pior turno, fatia a fatia, com quantas REQUISICOES cada uma pode fazer.
#
# Sao cinco fatias: `count_tokens` e `resumir` em `montar_contexto`, `reagir`,
# a chamada 1 (`classificar` ou `qualificar_investidor`, conforme o lead ja
# seja investidor) e a chamada 2 (`desambiguar`, ou `qualificar_investidor` na
# virada). Todas em `turno.py`, citadas pelo nome e nao pela linha: este bloco
# ja nasceu de um comentario que envelheceu, e numero de linha e a parte que
# envelhece primeiro.
#
# **Duas fatias custam DUAS requisicoes.** O laco `for tentativa in (1, 2)` de
# `_chamar` bate no provedor de novo quando o modelo pede a ferramenta de
# busca. Contar uma requisicao por fatia subconta o pior caso pela metade nas
# duas fatias mais caras -- foi assim que o comentario anterior deste arquivo
# chegou a 360s quando o numero real era 840s.
#
# As duas chamadas de investidor sao exclusivas entre si: a da virada so
# dispara quando a chamada 1 NAO foi a do investidor. Por isso o pior par e
# `classificar` com busca seguido de `qualificar_investidor` com busca, e nao
# investidor duas vezes.
#
# **E duas fatias custam N requisicoes, derivadas da configuracao (TEC-229).**
# A versao anterior contava `resumir` e `count_tokens` uma vez cada, e era a
# mesma classe de erro do paragrafo acima, uma camada abaixo: `montar_contexto`
# nao chama nenhum dos dois uma vez so.
def _pior_turno() -> tuple[tuple[float, int], ...]:
    """As fatias do turno e quantas requisicoes cada uma faz no pior caso.

    Funcao e nao constante porque duas fatias dependem de `Settings`, e
    `get_settings()` no import seria pior que a constante que isto substitui.
    """
    settings = get_settings()

    # `resumir`: a dobra do gatilho de acumulacao (`deve_regenerar`), mais uma
    # por volta do laco `while tokens > teto`, que para em
    # `contexto_max_iteracoes`.
    resumos = 1 + settings.contexto_max_iteracoes

    # `count_tokens`: a contagem antes do laco, uma por volta, e as de
    # `_truncar_ate_caber` -- que corta a janela pela metade a cada passo,
    # chegando a uma literal em log2(N), mais uma contagem se ainda precisar
    # descartar o resumo.
    #
    # **N vem do gatilho, e isso e suposicao e nao teorema.** O gatilho dobra
    # em 40 literais, entao em regime normal a janela que chega ao truncamento
    # tem essa ordem de grandeza; se a dobra falhar, `literais` passa disso. O
    # `max(..., 1)` existe para que um gatilho mal configurado em 0 nao leve
    # `log2` a `-inf` -- o teto fica errado, mas a funcao nao explode.
    #
    # **O termo e pessimista de proposito.** `_contar_se_valer` so paga o
    # round trip acima do limiar, e cortar pela metade derruba a contagem
    # rapido: na pratica o truncamento nao paga todas estas. Um teto nao pode
    # depender de quao rapido o texto encolhe, e subcontar aqui e o defeito
    # que a TEC-229 veio matar.
    cortes = math.ceil(math.log2(max(settings.contexto_gatilho_de_regeneracao, 1))) + 1
    contagens = 1 + settings.contexto_max_iteracoes + cortes

    return (
        (TETO_DO_COUNT_TOKENS, contagens),
        (TETO_DO_RESUMO, resumos),
        (TETO_DA_REACAO, 1),
        (TETO_DA_CLASSIFICACAO, 2),
        (TETO_DO_INVESTIDOR, 2),
    )
```

E na última linha de `segundos_do_modelo_no_pior_turno`, trocar `_PIOR_TURNO` pela chamada:

```python
    return sum(teto * requisicoes for teto, requisicoes in _pior_turno()) * (MAX_TENTATIVAS + 1)
```

- [ ] **Step 4: Rodar e ver os novos passarem e os antigos quebrarem**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_orcamento_do_turno.py -v --tb=short
```

Esperado: `test_o_pior_turno_segue_contexto_max_iteracoes` e `test_o_pior_turno_segue_o_gatilho_de_regeneracao` PASSAM. `test_o_pior_turno_cabe_no_job_timeout` e `test_a_folga_paga_o_banco` agora FALHAM, com a mensagem do primeiro dizendo `o pior turno soma 327.0s contra um job_timeout de 240s`. **Essa falha é o entregável da card** — confirmar o número antes de seguir.

- [ ] **Step 5: Marcar os dois como `xfail` estrito**

Acrescentar `import pytest` ao topo de `tests/unit/test_orcamento_do_turno.py` (se o Step 1 ainda não o pôs) e a marca sobre os dois testes:

```python
@pytest.mark.xfail(
    strict=True,
    reason=(
        "TEC-229 corrigiu o grafo de chamadas e a conta deixou de fechar: 327s "
        "contra um job_timeout de 240. Fechar exige mexer na janela do sweeper, "
        "que e decisao de produto -- ver TEC-290. Estrito de proposito: quem "
        "fechar o orcamento ve isto virar XPASS e e obrigado a tirar a marca."
    ),
)
def test_o_pior_turno_cabe_no_job_timeout() -> None:
```

A mesma marca, com o mesmo `reason`, sobre `test_a_folga_paga_o_banco`.

- [ ] **Step 6: Rodar e confirmar verde**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_orcamento_do_turno.py -v --tb=short
```

Esperado: 3 passed, 2 xfailed. Nenhum failed, nenhum xpassed.

- [ ] **Step 7: Rodar os gates estáticos**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Esperado: os três limpos. `ruff format --check` é gate separado do `ruff check` — passar num não diz nada sobre o outro.

- [ ] **Step 8: Commit**

```bash
git add src/mobia/infra/anthropic.py tests/unit/test_orcamento_do_turno.py
git commit -F - <<'EOF'
feat(TEC-229): o pior turno conta as voltas do laco de montagem, e nao cabe

`_PIOR_TURNO` contava `resumir` e `count_tokens` uma vez cada. `montar_contexto`
chama os dois no laco `while tokens > teto`, que roda ate
`contexto_max_iteracoes`, e `_truncar_ate_caber` acrescenta contagens. Derivado
da configuracao, o pior caso vai de 7 para 20 requisicoes e a parcela da
Anthropic de 162s para 287s.

Com isso a soma dos quatro clientes externos passa a 327s contra um
`job_timeout` de 240, e `test_o_pior_turno_cabe_no_job_timeout` e
`test_a_folga_paga_o_banco` viram `xfail(strict=True)` apontando para a
TEC-290. Estrito para que fechar o orcamento obrigue a remover a marca.

Os dois testes novos sao o que sobra guardando a derivacao enquanto aqueles
dois estao xfail.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: O teste do sweeper fica só com a invariante do nome dele

**Files:**
- Modify: `tests/integration/test_worker_startup.py:150-166`

**Interfaces:**
- Consumes: nada da Task 1. Esta task é independente e pode ser revisada sozinha.
- Produces: nada. `test_job_timeout_cabe_dentro_da_janela_do_sweeper` continua existindo com o mesmo nome.

- [ ] **Step 1: Substituir o teste inteiro**

Trocar o corpo e o docstring de `test_job_timeout_cabe_dentro_da_janela_do_sweeper` por:

```python
def test_job_timeout_cabe_dentro_da_janela_do_sweeper() -> None:
    """Os dois numeros sao acoplados e moram em arquivos diferentes.

    `job_timeout` >= `sweep_inflight_after_seconds` faria o sweeper
    reenfileirar um turno ainda em voo: a mesma conversa rodaria duas vezes em
    paralelo, pagando duas classificacoes.

    **A outra metade desta invariante -- o turno real caber no `job_timeout` --
    NAO esta aqui**, e ja esteve. Ate a TEC-229 este teste tambem afirmava
    `TIMEOUT_SEGUNDOS * 2 <= job_timeout`, supondo duas chamadas ao provedor
    por turno. O turno faz cinco fatias, duas delas com duas requisicoes e
    duas com um numero derivado de `contexto_max_iteracoes` -- e
    `TIMEOUT_SEGUNDOS` nem governa chamada do turno, e o piso de quem nao pede
    teto proprio (`followup/prosa.py`, `handoff/resumo.py`). A assercao passava
    por empate exato quando foi escrita e, depois que a TEC-228 zerou
    `MAX_TENTATIVAS`, passou a passar com folga de 2x sobre um numero que nao
    mede nada do turno.

    A conta do turno mora em `tests/unit/test_orcamento_do_turno.py`, que soma
    os quatro clientes externos importando cada teto de quem o define. Nao
    reconstrua o grafo de chamadas aqui.
    """
    from mobia.app.config import get_settings
    from mobia.workers.main import WorkerSettings

    assert WorkerSettings.job_timeout < get_settings().sweep_inflight_after_seconds
```

Some o `assert WorkerSettings.job_timeout >= 180`: é piso escrito à mão, e `test_a_folga_paga_o_banco` cobre a mesma direção derivando o número da soma real. Somem também os imports de `MAX_TENTATIVAS` e `TIMEOUT_SEGUNDOS`, que ficam sem uso.

- [ ] **Step 2: Rodar o arquivo**

Precisa de `docker compose` de pé. Se o `alembic upgrade head` reprovar com `ConnectionResetError [WinError 64]`, espere e repita — o container mente sobre estar pronto.

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_worker_startup.py -v --tb=short
```

Esperado: todos PASSAM. Uma falha isolada com `ConnectionResetError` na negociação SSL não autoriza conclusão nenhuma — rode de novo antes de culpar a mudança.

- [ ] **Step 3: Gates estáticos**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

Esperado: limpos. `ruff check` acusaria os imports órfãos se o Step 1 tivesse esquecido algum.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_worker_startup.py
git commit -F - <<'EOF'
test(TEC-229): o teste do sweeper para de afirmar um turno de duas chamadas

A assercao `TIMEOUT_SEGUNDOS * (1 + MAX_TENTATIVAS) * 2 <= job_timeout` media
uma constante que nao governa chamada nenhuma do turno -- desde a TEC-228
`TIMEOUT_SEGUNDOS` e o piso de quem nao pede teto proprio, que sao as duas
chamadas de FORA do turno. Escrita como empate exato, virou folga de 2x quando
`MAX_TENTATIVAS` foi a zero, o que a deixou mais tranquilizadora e igualmente
falsa.

Sai junto o `job_timeout >= 180`: piso escrito a mao, dominado por
`test_a_folga_paga_o_banco`, que deriva o mesmo limite da soma real.

Fica a invariante que o nome do teste promete e que nenhum outro cobre.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: A prosa que afirma que a conta fecha

**Files:**
- Modify: `src/mobia/workers/main.py:218-240` (o bloco "Hoje a conta fecha" do comentário de `job_timeout`)
- Modify: `src/mobia/infra/anthropic.py` (docstring de `segundos_do_modelo_no_pior_turno`)
- Modify: `tests/unit/test_orcamento_do_turno.py` (o docstring de módulo, no topo)

**Interfaces:**
- Consumes: os números que a Task 1 produziu — 287s (Anthropic) e 327s (soma).
- Produces: nada executável.

Isto não é higiene. O comentário de `job_timeout` já mentiu uma vez — a TEC-228 encontrou lá um `360s` onde o real era `840s` — e deixá-lo afirmando `202s contra estes 240 — 38s de folga` seria a segunda mentira no mesmo lugar, agora com número novo.

- [ ] **Step 1: Corrigir o comentário de `job_timeout`**

Em `src/mobia/workers/main.py`, substituir o trecho que começa em `# Hoje a conta fecha, com os quatro clientes externos contados:` e vai até o parágrafo que termina em `era o todo que produziu o 360s desta versao anterior.` por:

```python
    # **Hoje a conta NAO fecha, e este numero e o que nao cabe.** A TEC-229
    # corrigiu o grafo: `montar_contexto` chama `resumir` e `count_tokens`
    # dentro do laco `while tokens > teto`, que roda ate
    # `contexto_max_iteracoes`, e `_truncar_ate_caber` acrescenta contagens.
    # Contadas as voltas, com os valores de hoje:
    #
    #   287s  Anthropic (`segundos_do_modelo_no_pior_turno`)
    #    20s  embed da busca, 2 buscas x 10s, sem retentativa
    #    10s  moderacao das duas pontas
    #    10s  POST para a Meta
    #   ----
    #   327s  contra estes 240 -- deficit de 87s, e a reserva de banco some
    #
    # Por isso `test_o_pior_turno_cabe_no_job_timeout` e
    # `test_a_folga_paga_o_banco` estao `xfail(strict=True)`. Eles montam essa
    # soma importando cada termo do modulo dele; e onde a conta INTEIRA esta
    # escrita -- cada modulo so conhece a propria parcela, e foi somar uma
    # parcela achando que era o todo que produziu o 360s de duas versoes atras
    # deste comentario.
    #
    # **Subir este numero nao e o conserto obvio.** Ele tem de ficar
    # estritamente abaixo de `sweep_inflight_after_seconds` (300), entao cabem
    # no maximo mais 59s -- menos que o deficit. Fechar a conta exige a janela
    # do sweeper, os tetos, ou um orcamento agregado na montagem: e a TEC-290,
    # que lista as tres sem escolher.
```

Some junto o parágrafo `# Continua valendo o que a "Lacunas conhecidas" ... So que agora nao ha por que subir.` — a última frase dele passa a ser falsa.

- [ ] **Step 2: Corrigir o docstring de `segundos_do_modelo_no_pior_turno`**

Em `src/mobia/infra/anthropic.py`, o docstring afirma ser *"a unica coisa que torna vermelha a mudanca de um teto que nao cabe mais no orcamento"*. Com o `xfail` isso deixou de ser verdade. Substituir esse parágrafo por:

```
    Existe para entrar na soma de `tests/unit/test_orcamento_do_turno.py`, que
    a compara com o `job_timeout` do worker.

    **Esse teste esta `xfail` desde a TEC-229 e nao guarda mais nada sozinho.**
    Quem guarda a derivacao sao os dois testes irmaos de la, que afirmam que
    subir `contexto_max_iteracoes` ou o gatilho move este numero. Enquanto a
    TEC-290 nao fechar o orcamento, apagar aqueles dois deixa esta funcao livre
    para voltar a ser constante sem nada perceber.
```

- [ ] **Step 3: Corrigir o cabeçalho de `tests/unit/test_orcamento_do_turno.py`**

Acrescentar ao fim do docstring de módulo, antes das aspas de fechamento:

```
A TEC-229 acrescentou as voltas do laco de `montar_contexto` a conta, e com
elas a soma passou de 202s para 327s contra um `job_timeout` de 240: os dois
testes que somam estao `xfail(strict=True)` ate a TEC-290 decidir como fechar.
Os dois que afirmam a derivacao continuam verdes, e sao o que impede este
arquivo de virar decoracao no meio-tempo.
```

- [ ] **Step 4: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reler cada `ALTERADO` e `VIZINHO` de `anthropic.py`, `main.py` e dos dois arquivos de teste, e cada `PROSA`/`FALSO`/`NOMEIA`. Dois pontos já conhecidos a conferir, que podem ou não precisar de mudança:

- `src/mobia/domain/agente/classificador.py:904` — *"busca custa ate `2 * timeout`, e e assim que `_PIOR_TURNO` a conta"*. Continua verdade (as duas fatias com busca seguem em 2×), mas o nome `_PIOR_TURNO` virou `_pior_turno()`; ajustar a citação.
- `tests/unit/test_classificador.py:1605` — *"quem afirma os numeros e `test_o_pior_turno_cabe_no_job_timeout`"*. Continua verdade, e agora aquele teste afirma que os números **não** fecham; se a frase induzir a erro, dizer isso.

Se o footer contar mais do que coube na tela, rodar `--tudo`.

- [ ] **Step 5: Gates estáticos e a suíte unitária**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
```

Esperado: gates limpos; unitários verdes com 2 xfailed.

- [ ] **Step 6: Commit**

```bash
git add src/mobia/workers/main.py src/mobia/infra/anthropic.py tests/unit/test_orcamento_do_turno.py
git commit -F - <<'EOF'
docs(TEC-229): o comentario do job_timeout para de afirmar que a conta fecha

Ele dizia "Hoje a conta fecha" com a tabela 162/202 contra 240 e 38s de folga
para o banco. Com as voltas do laco de montagem contadas, sao 287/327 e um
deficit de 87s. Mesmo comentario que a TEC-228 ja encontrou afirmando 360s
quando o real era 840s -- deixa-lo mentir de novo, com numero novo, seria pior
que nao ter comentario.

Registra tambem o que fecha a porta do conserto obvio: `job_timeout` tem de
ficar abaixo de `sweep_inflight_after_seconds`, entao cabem no maximo mais 59s,
menos que o deficit.

O docstring de `segundos_do_modelo_no_pior_turno` deixa de se dizer o que torna
vermelha a mudanca de um teto: com o xfail, quem faz isso sao os dois testes de
derivacao.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Verificação final, antes do PR

- [ ] **Suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Esperado: verde, com 2 xfailed e 0 xpassed. Guardar o hash junto com o resultado.

Se falhar, a segunda execução sobre a mesma árvore é o que separa flake de regressão — não é ritual de rotina. `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados. E `relation ... does not exist` em dezenas de testes é banco de worker com carimbo adiantado, não a sua mudança.

- [ ] **Abrir o PR contra `main`**, e na card TEC-229: comentar e mover para "Em análise" (não "Feito" — quem mergeia é que fecha).

O comentário da card precisa registrar, no mínimo:

- **Divergência:** a card pedia consertar o teste de `test_worker_startup.py`; a TEC-228 já havia movido a conta para `tests/unit/test_orcamento_do_turno.py`, então a correção real foi em `_PIOR_TURNO`, e o teste de integração só perdeu a asserção falsa.
- **Divergência:** a card descreve a asserção passando por empate exato (`120 × 2 = 240`); desde a TEC-228 ela passa com folga de 2x, o que é pior.
- **Critério de aceite não exercitado:** *"o teste falha se o teto por chamada subir, ou se `job_timeout` descer"* — com os dois testes de soma em `xfail`, isso deixa de valer até a TEC-290. Os dois testes de derivação cobrem só a parte de `contexto_max_iteracoes` e do gatilho.
- **O que a card não entrega:** o orçamento continua estourado em produção. Nada fica mais rápido; um turno patológico segue podendo ser cancelado pelo ARQ. O que mudou é a suíte parar de afirmar o contrário.
- **Lacuna que é decisão de produto:** fechar a conta exige a janela do sweeper — TEC-290.
- **Emendas ao SRS:** nenhuma.

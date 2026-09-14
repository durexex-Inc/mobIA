# TEC-261 — Varrer importações travadas: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uma importação que parou de andar deixa de dizer `PROCESSANDO` para sempre — a varredura a encerra em `FALHOU`, com motivo legível e `concluida_em` preenchido.

**Architecture:** Um job ARQ novo (`sweep_importacoes_travadas`) executa **um único** `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING id`. Um statement, e não as duas fases da `sweep_stalled`, porque não há I/O de rede entre ler e escrever — e é isso que resolve a concorrência por construção. O limite vem de `Settings` e é derivado do orçamento de retentativa do worker.

**Tech Stack:** Python 3.13, SQLAlchemy async (`text()` cru), Postgres, ARQ, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-tec-261-varrer-importacoes-travadas-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Prosa em `docs/`: com acento.
- **Os três gates, nesta ordem, antes de cada commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  O formatador é gate separado do linter; passar num não diz nada sobre o outro.
- Testes de integração exigem `docker compose` de pé.
- Commit: `tipo(TEC-261): o que passou a ser verdade`, português sem acento no assunto.
- **Nenhuma migration.** `importacoes` já tem todas as colunas que esta card usa (`status`, `criada_em`, `concluida_em`, `erros`).
- Branch já existe: `feat/tec-261-varrer-importacoes-travadas`, a partir de `970e1dd`.

## Estado de partida

Suíte inteira: **1903 passed / 0 failed**. Os três gates verdes.

## Dois fatos que este plano já verificou, para ninguém refazer

**1. A convenção de encerrar já existe.** `_marcar_falha`, em `src/mobia/api/routes/imoveis.py`, grava exatamente:

```python
importacao.status = str(StatusImportacao.FALHOU)
importacao.erros = [{"linha": 0, "motivo": motivo}]
importacao.concluida_em = datetime.now(UTC)
```

A card pede para "preencher `concluida_em`" como se fosse novidade — não é, desde `35ec649` (07/09/2026). **Siga o formato acima**, não invente.

**2. Substituir `erros` é seguro.** `src/mobia/domain/catalogo/importacao.py` grava o relatório de uma vez só, no fim (`erros`, `status` e `concluida_em` juntos). Uma linha travada nunca chegou lá, então `erros` está `[]`. Substituir e anexar dão o mesmo resultado, e substituir é o que o precedente faz.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/workers/jobs/sweep_importacoes_travadas.py` | **Criar.** O job e o SQL. |
| `src/mobia/app/config.py` | `sweep_importacao_travada_after_seconds`, com a derivação no comentário |
| `src/mobia/workers/main.py` | registro em `functions` e em `cron_jobs` |
| `tests/integration/test_sweep_importacoes_travadas.py` | **Criar.** Os quatro cenários. |

**O SQL mora no job, e não num módulo de domínio.** `sweep_stalled` e `sweep_followups` fazem assim. A `sweep_sla` delega para `domain/handoff/`, mas por outra razão: as duas funções que ela compõe já existiam para outros chamadores. Aqui é uma consulta com um consumidor só — criar um módulo de domínio para ela seria estrutura sem demanda.

---

### Task 1: O limite, o job e os três cenários simples

**Files:**
- Create: `src/mobia/workers/jobs/sweep_importacoes_travadas.py`
- Create: `tests/integration/test_sweep_importacoes_travadas.py`
- Modify: `src/mobia/app/config.py:259-261` (o bloco dos três `sweep_*`)

**Interfaces:**
- Consumes: nada.
- Produces:
  - `sweep_importacoes_travadas(ctx: dict[str, Any], limite: int = 100) -> int` — devolve quantas linhas encerrou.
  - `MOTIVO_DA_VARREDURA: str` — o texto gravado em `erros[0]["motivo"]`.
  - `Settings.sweep_importacao_travada_after_seconds: int = 1800`

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_sweep_importacoes_travadas.py`:

```python
"""A varredura que encerra importacao parada em PROCESSANDO. TEC-261."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
from mobia.domain.catalogo.models import Importacao
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_importacoes_travadas import (
    MOTIVO_DA_VARREDURA,
    sweep_importacoes_travadas,
)


def _ctx() -> dict[str, Any]:
    """Molde do ctx que os testes de `sweep_stalled` montam."""
    return {"session_factory": get_sessionmaker()}


async def _importacao(
    session: Any,
    *,
    status: StatusImportacao,
    idade_segundos: int,
    processados: int = 0,
) -> uuid.UUID:
    """Uma linha com idade controlada.

    `criada_em` tem `server_default=clock_timestamp()`, entao envelhecer a
    linha exige passar o valor explicitamente -- sem isso toda linha nasce
    recente e nenhum cenario de limite e exercitado.
    """
    identificador = uuid.uuid4()
    session.add(
        Importacao(
            id=identificador,
            origem=str(OrigemImportacao.HTTP),
            nome_arquivo="catalogo.csv",
            arquivo=b"codigo,titulo\n",
            status=str(status),
            processados=processados,
            criada_em=datetime.now(UTC) - timedelta(seconds=idade_segundos),
        )
    )
    await session.commit()
    return identificador


async def test_importacao_parada_alem_do_limite_e_encerrada(session: Any) -> None:
    """Cenario 1. O relatorio passa a dizer "nao terminou" em vez de "processando".

    Sem isto, `PROCESSANDO` significa duas coisas -- "o worker esta
    trabalhando" e "o worker morreu" -- e quem consulta nao sabe se espera ou
    reimporta.
    """
    importacao_id = await _importacao(
        session, status=StatusImportacao.PROCESSANDO, idade_segundos=3600
    )

    assert await sweep_importacoes_travadas(_ctx()) == 1

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.status == str(StatusImportacao.FALHOU)
    assert lida.concluida_em is not None, (
        "uma linha FALHOU sem timestamp de fim nao diz quando parou"
    )
    assert lida.erros == [{"linha": 0, "motivo": MOTIVO_DA_VARREDURA}], (
        "mesma forma que `_marcar_falha` grava -- linha 0 e a convencao da "
        "TEC-156 para falha de arquivo inteiro"
    )


async def test_importacao_recente_nao_e_tocada(session: Any) -> None:
    """Cenario 2. O limite existe para nao matar trabalho vivo.

    Uma importacao pode legitimamente levar ate 20 minutos de processamento
    (5 tentativas de `job_timeout=240`), e fechar uma que ainda esta rodando e
    a mentira que esta card existe para acabar.
    """
    importacao_id = await _importacao(
        session, status=StatusImportacao.PROCESSANDO, idade_segundos=60
    )

    assert await sweep_importacoes_travadas(_ctx()) == 0

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.status == str(StatusImportacao.PROCESSANDO)
    assert lida.concluida_em is None


async def test_importacao_concluida_nao_e_tocada(session: Any) -> None:
    """Cenario 3. So `PROCESSANDO` entra na varredura.

    Uma linha CONCLUIDO velha e o caso NORMAL -- toda importacao bem-sucedida
    vira uma. Se o filtro fosse so pela idade, a varredura reescreveria o
    relatorio de toda importacao antiga do sistema.
    """
    importacao_id = await _importacao(
        session, status=StatusImportacao.CONCLUIDO, idade_segundos=3600, processados=42
    )

    assert await sweep_importacoes_travadas(_ctx()) == 0

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.status == str(StatusImportacao.CONCLUIDO)
    assert lida.processados == 42
    assert lida.erros == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_importacoes_travadas.py --tb=short
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'mobia.workers.jobs.sweep_importacoes_travadas'`.

- [ ] **Step 3: Acrescentar o setting**

Em `src/mobia/app/config.py`, logo depois de `sweep_max_attempts`:

```python
    # TEC-261. O piso deste numero nao e gosto: e o orcamento de retentativa do
    # worker. `job_timeout = 240` e `max_tries = 5` (`workers/main.py`), e um
    # `job_timeout` do ARQ vira `CancelledError` -- uma das tres excecoes que
    # ele REAGENDA. Entao uma importacao que estoura o tempo pode ser
    # legitimamente retentada cinco vezes: 20 minutos de processamento no pior
    # caso, mais a espera na fila e o backoff entre tentativas.
    #
    # 30 minutos ficam ~50% acima disso, cobrindo fila e backoff sem precisar
    # calcula-los. Importacao e rara: uma linha travada esperar meia hora antes
    # de ser fechada nao custa nada, e o custo do outro lado -- fechar uma que
    # ainda esta viva -- e a mentira de relatorio que esta card existe para
    # acabar.
    #
    # **Quem subir `job_timeout` ou `max_tries` tem de reconferir este numero.**
    # Ele nao se move sozinho, e nada acusa quando o piso cresce.
    sweep_importacao_travada_after_seconds: int = 1800
```

- [ ] **Step 4: Criar o job**

`src/mobia/workers/jobs/sweep_importacoes_travadas.py`:

```python
"""A varredura que encerra importacao de catalogo parada em PROCESSANDO. TEC-261."""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text

from mobia.app.config import Settings, get_settings

log = structlog.get_logger(__name__)

# Nao nomeia a causa -- worker caido, fila perdida, tempo estourado sao
# indistinguiveis daqui, e afirmar uma seria inventar. Diz o que aconteceu e o
# que fazer, porque quem le o relatorio e o administrador, nao quem opera.
MOTIVO_DA_VARREDURA = (
    "O processamento nao terminou e a importacao foi encerrada pela varredura. "
    "Reimporte o arquivo."
)

# **Um statement, e nao as duas fases da `sweep_stalled`.** La o SELECT e
# commitado antes do enqueue porque ha I/O de rede no meio, e o docstring dela
# explica o preco de segurar lock de linha enquanto se fala com o Redis. Aqui
# nao ha I/O nenhum: le e escreve a mesma tabela.
#
# Com um statement, o quarto cenario do Gherkin -- duas varreduras concorrentes
# nao encerram a mesma linha duas vezes -- sai por construcao. Copiar as duas
# fases faria o oposto: abriria uma janela entre o commit do SELECT e o UPDATE
# em que a segunda varredura ainda leria `PROCESSANDO`.
#
# `CAST(:erro AS jsonb)` e nao o parametro cru: `erros` e JSONB, e um `text()`
# com parametro nao converte lista Python por este caminho.
_ENCERRAR_TRAVADAS = text(
    """
    UPDATE importacoes
       SET status = 'FALHOU',
           concluida_em = now(),
           erros = CAST(:erro AS jsonb)
     WHERE id IN (
             SELECT id
               FROM importacoes
              WHERE status = 'PROCESSANDO'
                AND criada_em < now() - make_interval(secs => :travada_after)
              ORDER BY criada_em
              LIMIT :limite
                FOR UPDATE SKIP LOCKED
           )
    RETURNING id
    """
)


async def sweep_importacoes_travadas(ctx: dict[str, Any], limite: int = 100) -> int:
    """Encerra em FALHOU a importacao que parou de andar. Devolve quantas.

    `PROCESSANDO` tem dois significados e nada os distingue: "o worker esta
    trabalhando nisso" e "o worker morreu e ninguem vai voltar". A TEC-156
    fechou o caso do enqueue que FALHA (`_marcar_falha`, em
    `api/routes/imoveis.py`); fica este, o do enqueue que deu certo e do
    processamento que nao terminou -- worker caido, fila perdida, tempo
    estourado sem retry.

    **Marca FALHOU, nao reenfileira.** Reenfileirar exigiria uma coluna de
    tentativas que `importacoes` nao tem: a `sweep_stalled` depende de
    `messages.attempts` para nao entrar em laco, e aqui nao ha equivalente.
    Marcar e mais honesto -- o relatorio passa a dizer "nao terminou" em vez de
    mentir "processando".

    **Grava o mesmo formato de `_marcar_falha`**: `FALHOU`, `concluida_em` e um
    erro na linha 0. A convencao da linha 0 e da TEC-156, para falha de arquivo
    inteiro, e ja existia antes desta card.

    **Substituir `erros` em vez de anexar e seguro**, e a razao e verificavel:
    `catalogo/importacao.py` grava o relatorio de uma vez so, no fim. Uma linha
    travada nunca chegou la, entao `erros` esta vazio.

    **A corrida que fica.** Se algo exceder o limite e o job ainda estiver vivo
    quando esta varredura fechar a linha, o job sobrescreve com o resultado
    verdadeiro no fim -- `catalogo/importacao.py` grava sem olhar o estado atual
    da linha. O sistema se cura e o desfecho final e o certo; esta escrito aqui
    para ninguem descobrir isso num incidente e achar que e defeito.

    **NAO limpa `importacoes.arquivo`.** A retencao dos bytes esta fora do
    escopo da card, entao a linha encerrada continua segurando ate 10 MB. E
    lacuna conhecida, nao esquecimento.
    """
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()

    async with session_factory() as session:
        resultado = await session.execute(
            _ENCERRAR_TRAVADAS,
            {
                "erro": json.dumps([{"linha": 0, "motivo": MOTIVO_DA_VARREDURA}]),
                "travada_after": settings.sweep_importacao_travada_after_seconds,
                "limite": limite,
            },
        )
        ids: list[uuid.UUID] = [linha[0] for linha in resultado.fetchall()]
        await session.commit()

    if ids:
        # `error`, e nao `info` como o `sweep.requeued` da `sweep_stalled`: la o
        # desfecho e recuperacao (a mensagem volta para a fila), aqui e
        # terminal. O administrador perdeu o trabalho e vai precisar reimportar.
        # Mesmo nivel que `catalogo.importacao_nao_enfileirada`, que e o irmao
        # deste caso na TEC-156.
        log.error(
            "catalogo.importacoes_travadas_encerradas",
            count=len(ids),
            importacao_ids=[str(i) for i in ids],
        )
    return len(ids)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_importacoes_travadas.py --tb=short
```

Esperado: PASS nos três.

Se o primeiro falhar comparando `erros`, confira o que o banco devolveu: o `CAST(:erro AS jsonb)` com `json.dumps` deve produzir exatamente `[{"linha": 0, "motivo": "..."}]`. Uma lista Python passada crua daria erro de adaptação, não um valor errado.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "feat(TEC-261): a importacao travada passa a ser encerrada em FALHOU"
```

---

### Task 2: O cenário de concorrência

**Files:**
- Modify: `tests/integration/test_sweep_importacoes_travadas.py` (acrescentar)

**Interfaces:**
- Consumes: `sweep_importacoes_travadas` da Task 1.
- Produces: nada — é teste.

**Por que este cenário merece task própria:** ele é o único que prova o `FOR UPDATE SKIP LOCKED`. Um teste que apenas chame a varredura duas vezes em sequência passaria mesmo sem `SKIP LOCKED` — a segunda passagem não acha nada porque a primeira já mudou o status, e o `SKIP LOCKED` nunca é exercitado. **Provar o lock exige uma sessão de verdade segurando a linha enquanto a varredura roda.**

- [ ] **Step 1: Write the test**

```python
async def test_duas_varreduras_nao_encerram_a_mesma_linha_duas_vezes(session: Any) -> None:
    """Cenario 4. `FOR UPDATE SKIP LOCKED`, provado com lock de verdade.

    **Chamar a varredura duas vezes em sequencia NAO prova nada**: a segunda
    passagem nao acha a linha porque a primeira ja mudou o status, e o
    `SKIP LOCKED` nunca e exercitado -- o teste passaria identico sem ele.

    Aqui uma sessao segura a linha com `FOR UPDATE` enquanto a varredura roda.
    Com `SKIP LOCKED` ela pula e devolve zero; sem ele, ela BLOQUEIA esperando
    o lock e o teste trava ate o timeout -- que e o comportamento que a
    clausula existe para evitar, com um sweeper concorrente segurando o outro.
    """
    from sqlalchemy import text as sql

    importacao_id = await _importacao(
        session, status=StatusImportacao.PROCESSANDO, idade_segundos=3600
    )

    async with get_sessionmaker()() as bloqueadora:
        await bloqueadora.execute(
            sql("SELECT id FROM importacoes WHERE id = :i FOR UPDATE"),
            {"i": importacao_id},
        )
        assert await sweep_importacoes_travadas(_ctx()) == 0, (
            "com a linha travada por outra sessao, a varredura tem de PULAR -- "
            "sem SKIP LOCKED ela ficaria bloqueada esperando"
        )
        await bloqueadora.rollback()

    # Solto o lock, a linha e encerrada -- uma vez, e so uma.
    assert await sweep_importacoes_travadas(_ctx()) == 1
    assert await sweep_importacoes_travadas(_ctx()) == 0, (
        "a segunda passagem nao acha mais nada: o status ja nao e PROCESSANDO"
    )

    async with get_sessionmaker()() as outra:
        lida = await outra.get(Importacao, importacao_id)
    assert lida is not None
    assert lida.erros == [{"linha": 0, "motivo": MOTIVO_DA_VARREDURA}], (
        "encerrada uma unica vez -- dois encerramentos deixariam dois erros "
        "ou sobrescreveriam o timestamp"
    )
```

- [ ] **Step 2: Run it**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_importacoes_travadas.py -k concorrentes --tb=short
```

Esperado: PASS.

**Se ele travar em vez de passar**, isso é informação, não flake: significa que o `SKIP LOCKED` não está no SQL e a varredura está bloqueando no lock. Confira o statement antes de culpar o ambiente.

- [ ] **Step 3: Provar que ele morde**

Sonda temporária: tire ` SKIP LOCKED` do `_ENCERRAR_TRAVADAS` (deixando só `FOR UPDATE`) e rode de novo com timeout curto:

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_sweep_importacoes_travadas.py -k concorrentes --tb=short --timeout=30
```

Esperado: o teste **trava e estoura o timeout** em vez de passar. Reverta a sonda e confirme `git diff --stat src/` vazio.

Se o `pytest-timeout` não estiver instalado, rode sem ele e interrompa manualmente depois de ~20 segundos — o que importa registrar no report é que a varredura **bloqueou** em vez de devolver zero.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "test(TEC-261): o SKIP LOCKED provado com lock de verdade"
```

---

### Task 3: O registro no worker

**Files:**
- Modify: `src/mobia/workers/main.py` (import, `functions`, `cron_jobs`)

**Interfaces:**
- Consumes: `sweep_importacoes_travadas` da Task 1.
- Produces: o job passa a rodar de 5 em 5 minutos.

**Por que é task separada:** até aqui o job existe e funciona, mas **nada o chama**. Um revisor pode aprovar o SQL e rejeitar a cadência, ou vice-versa.

- [ ] **Step 1: Acrescentar o import**

Junto aos outros imports de sweep, em ordem alfabética:

```python
from mobia.workers.jobs.sweep_importacoes_travadas import sweep_importacoes_travadas
```

- [ ] **Step 2: Registrar em `functions`**

Na lista `functions`, junto dos outros sweeps:

```python
        sweep_importacoes_travadas,
```

**Sem `func(..., keep_result=0)`**: os que recebem esse tratamento na lista têm razão escrita para isso (o `_job_id` fixo da dedup, ou o resultado que o GET lê). Um cron job do ARQ gera id novo a cada disparo e ninguém lê o resultado desta varredura — o padrão aqui é o de `sweep_stalled` e `sweep_followups`, que entram crus.

- [ ] **Step 3: Registrar em `cron_jobs`**

Depois do bloco do `sweep_sla`, no mesmo formato:

```python
        # De 5 em 5 minutos, como o `sweep_followups` e o `sweep_sla` acima, e
        # nao de 30 em 30 segundos como a `sweep_stalled`. O limite desta
        # varredura e de TRINTA MINUTOS
        # (`sweep_importacao_travada_after_seconds`), entao precisao de
        # segundos nao compra nada e custaria uma varredura a cada passagem.
        # O erro maximo de disparo fica em cinco minutos sobre uma janela de
        # trinta.
        cron(
            sweep_importacoes_travadas,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
```

- [ ] **Step 4: Conferir que o worker ainda monta**

```bash
./.venv/Scripts/python.exe -c "
from mobia.workers.main import WorkerSettings
nomes = [getattr(f, '__name__', getattr(f, 'name', str(f))) for f in WorkerSettings.functions]
crons = [c.name for c in WorkerSettings.cron_jobs]
print('functions:', nomes)
print('crons:', crons)
assert 'sweep_importacoes_travadas' in nomes, 'faltou em functions'
assert any('importacoes_travadas' in c for c in crons), 'faltou em cron_jobs'
print('OK')
"
```

Esperado: `OK`. **Este passo é o teste desta task** — ele prova que o ARQ resolve o job nas duas listas, que é o que "registrado" significa. Um teste de integração que rodasse a varredura não provaria isso: ela já roda sem estar registrada.

- [ ] **Step 5: Rodar os testes do worker, se houver**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -k "worker or main" --tb=short
```

Se não houver nenhum, diga isso no report — é informação sobre a cobertura, não um passo pulado.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "feat(TEC-261): a varredura de importacao entra no relogio do worker"
```

---

### Task 4: Comentários tocados, e o PR

**Files:**
- Modify: os que a listagem apontar

- [ ] **Step 1: A listagem obrigatória**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO`. Este repo comenta o **porquê** e **trata comentário desatualizado como defeito, não como sujeira** — precedente TEC-146, em que um comentário falso escondeu um bug por duas rodadas de revisão. A categoria `VIZINHO` é a que pega esse caso, porque um comentário que ninguém editou não aparece no diff.

**Um ponto que este plano já sabe estar em risco:** `_marcar_falha`, em `src/mobia/api/routes/imoveis.py`, tem um docstring que afirma:

> "Quando o enqueue nao acontece, ninguem mais vai tocar nessa linha: nao ha job para roda-la **e nao ha sweep que varra importacao parada**."

A segunda metade **deixa de ser verdade com esta card.** Corrija — e note que o argumento do parágrafo continua válido para o caso dele (o enqueue que falha deixa a linha sem job), só a afirmação sobre a inexistência da varredura é que morreu.

**Atenção à ferramenta:** ela não lista comentário em função cujo corpo não mudou. `_marcar_falha` **não** aparecerá na listagem, porque esta card não toca `imoveis.py` — foi por isso que este plano o nomeou à mão. Procure irmãos dele: qualquer texto que afirme que importação parada não tem varredura.

```bash
grep -rn "sweep que varra\|varredura de importacao\|importacao parada" src/ docs/
```

- [ ] **Step 2: Emenda ao SRS, se houver**

Se o que a RN-08.5 afirma sobre o ciclo de vida de uma importação mudar, entre com item aninhado `Emenda E-nn (TEC-261, 2026-09-13)` **abaixo** da regra, em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, sem reescrever o texto de 22/08/2026.

Se concluir que nenhuma regra mudou, **diga isso no report com o raciocínio** — não invente emenda. Ponto de partida para a decisão: a RN-08.5 fala do relatório e do que ele contém; esta card não muda o conteúdo do relatório, muda **quando** ele para de dizer `PROCESSANDO`.

- [ ] **Step 3: A suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado. Se falhar, repita sobre a mesma árvore antes de culpar a mudança — e lembre que `test_montagem.py`, `test_sweep_stalled.py`, `test_dedup_por_message_id.py` e `test_optout_repositorio.py` flakeiam sob carga e passam isolados.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A && git commit -m "docs(TEC-261): o docstring de _marcar_falha para de dizer que nao ha varredura"
```

- [ ] **Step 5: PR e card — PARAR e pedir autorização**

Push, PR e comentário na card são efeito fora da árvore. **Pare aqui.** O comentário da card precisa registrar:

- **A divergência:** a card manda seguir o molde da `sweep_stalled` com suas duas fases; a implementação usa **um statement**, porque não há I/O entre ler e escrever e as duas fases abririam a janela de concorrência que o quarto cenário existe para fechar.
- **A afirmação desatualizada da card:** `concluida_em` já era preenchido pelo `_marcar_falha` desde `35ec649`, do mesmo dia em que a card foi escrita. A varredura segue a convenção existente em vez de criar uma.
- **O limite e sua derivação:** 30 minutos, com piso de 20 vindo de `job_timeout × max_tries`. **E a L3:** se alguém subir qualquer um dos dois, o piso cresce e nada acusa.
- **A L1, que é decisão de produto:** a linha encerrada continua segurando até 10 MB em `importacoes.arquivo`. A card põe a retenção fora de escopo, mas o problema que ela mesma descreve continua de pé depois do encerramento.
- **A L2:** nada avisa o administrador. Ele só descobre se voltar a consultar.

---

## Auto-revisão deste plano

**Cobertura da spec:** D1 → Task 1, Step 3. D2 → Task 1, Step 4. D3 → Task 1 (Steps 1 e 4). D4 → Task 3. D5 → Task 1 (o docstring registra). A corrida aceitável → Task 1, no docstring. Testes 1-3 → Task 1. Teste 4 → Task 2. L1/L2/L3 → Task 4, no comentário da card.

**Consistência de tipos:** `sweep_importacoes_travadas(ctx, limite=100) -> int` é criada na Task 1 e consumida com a mesma assinatura nas Tasks 2 e 3. `MOTIVO_DA_VARREDURA` é usada nos testes das Tasks 1 e 2 com o mesmo nome. `sweep_importacao_travada_after_seconds` (singular em "importacao") é o nome do campo em todos os pontos.

**Um ponto em que este plano é deliberadamente firme:** a Task 2, Step 3 manda provar o teste por sonda, e o resultado esperado é um **travamento**, não uma falha de asserta. Isso é incomum o bastante para alguém achar que errou — daí o passo dizer com todas as letras que travar é o resultado certo.

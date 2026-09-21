# TEC-128 — Debounce de rajada: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a rajada de mensagens do lead render uma resposta só, atrasando cada mensagem por uma janela e deixando que apenas a última da rajada execute o turno.

**Architecture:** Cada mensagem é enfileirada com `_defer_by` igual à janela. Ao acordar, o job pergunta ao Postgres se chegou INBOUND mais nova para o mesmo `(channel, conversation_key)`; se chegou, fecha como `PROCESSED` com desfecho `"agrupado"` e não responde. O reinício da contagem é aritmético — cada mensagem carrega o próprio relógio, e nada cancela nem reprograma job. Mensagem de opt-out não espera e nunca é descartada por superação.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, ARQ 0.28 sobre Redis, Postgres, pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-09-21-tec-128-debounce-de-rajada-design.md`](../specs/2026-09-21-tec-128-debounce-de-rajada-design.md)

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado — uma citação de texto que o lead recebe mantém o acento do literal.
- **Texto que o lead recebe: português COM acento.** Esta card não cria nenhum texto novo para o lead.
- **Prosa em `docs/` e `.md`: com acento.**
- **Os três gates, nesta ordem, antes de cada commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  `ruff check` passar não diz nada sobre `ruff format`. O `mypy` roda **sem argumento** — argumento de linha de comando sobrepõe o `files` do `pyproject.toml`.
- **Loop rápido:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4,4s, não precisa de `docker compose`). `tests/integration` e `tests/features` exigem os containers de pé.
- **Nenhum teste espera segundos reais.** Toda janela em teste vem de `monkeypatch.setenv(...)` mais `get_settings.cache_clear()`, com centésimos de segundo.
- **Commits:** `tipo(TEC-128): o que passou a ser verdade`, assunto em português sem acento.

---

### Task 1: A janela é configuração, e o enqueue sabe atrasar

**Files:**
- Modify: `src/mobia/app/config.py` (logo após `indicador_de_digitacao_apos_segundos`, linha 164)
- Modify: `src/mobia/infra/queue.py:19-32`
- Test: `tests/integration/test_queue.py`

**Interfaces:**
- Produces: `Settings.debounce_de_rajada_segundos: float = 6.0`
- Produces: `enqueue_process_message(pool: ArqRedis, message_id: uuid.UUID, *, atraso_segundos: float = 0.0) -> bool` — o parâmetro é keyword-only e tem default zero, então todas as chamadas de hoje (`sweep_stalled.py:113`, `messages/service.py:123`) continuam compilando e continuam enfileirando sem atraso.

- [ ] **Step 1: Write the failing tests**

Em `tests/integration/test_queue.py`, acrescente ao topo o import `from datetime import UTC, datetime` e, ao fim do arquivo, os três testes:

```python
async def test_atraso_vira_job_diferido(redis_pool) -> None:
    """O atraso vira score futuro no zset da fila, que e como o ARQ difere."""
    message_id = uuid.uuid4()
    antes_ms = datetime.now(UTC).timestamp() * 1000

    assert await enqueue_process_message(redis_pool, message_id, atraso_segundos=6.0) is True

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1
    assert jobs[0].score is not None
    # Folga generosa dos dois lados: o que se prova e que o job nao esta
    # pronto para rodar agora, nao a precisao do relogio.
    assert 5_000 < jobs[0].score - antes_ms < 7_000


async def test_sem_atraso_o_job_nasce_pronto(redis_pool) -> None:
    """O default preserva o comportamento de hoje: sweeper e opt-out contam com ele."""
    message_id = uuid.uuid4()
    antes_ms = datetime.now(UTC).timestamp() * 1000

    assert await enqueue_process_message(redis_pool, message_id) is True

    jobs = await redis_pool.queued_jobs()
    assert jobs[0].score is not None
    assert jobs[0].score - antes_ms < 1_000


async def test_atraso_zero_e_o_mesmo_que_nenhum(redis_pool) -> None:
    """Janela zero desliga o debounce -- o caminho de fuga da D8 do desenho."""
    message_id = uuid.uuid4()
    antes_ms = datetime.now(UTC).timestamp() * 1000

    assert await enqueue_process_message(redis_pool, message_id, atraso_segundos=0.0) is True

    jobs = await redis_pool.queued_jobs()
    assert jobs[0].score is not None
    assert jobs[0].score - antes_ms < 1_000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_queue.py -v --tb=short
```

Esperado: os três novos FALHAM com `TypeError: enqueue_process_message() got an unexpected keyword argument 'atraso_segundos'` (os dois primeiros) — `test_sem_atraso_o_job_nasce_pronto` pode passar de imediato, e tudo bem: ele é teste de regressão do default.

- [ ] **Step 3: Implement**

Em `src/mobia/infra/queue.py`, troque a assinatura e a chamada, mantendo a docstring existente e acrescentando o parágrafo novo:

```python
async def enqueue_process_message(
    pool: ArqRedis, message_id: uuid.UUID, *, atraso_segundos: float = 0.0
) -> bool:
    """Enfileira o processamento de uma mensagem.

    Usa `_job_id` derivado do message_id: o ARQ recusa o segundo enqueue enquanto
    o job estiver pendente, entao o sweeper nao multiplica trabalho. Devolve False
    quando o job ja estava na fila.

    O ARQ tambem recusa o enqueue quando a chave de *resultado* do mesmo job id
    existe. Por isso `process_message` e registrado com `keep_result=0` em
    `workers/main.py`: sem isso, o resultado de um job que terminou bloquearia
    todo re-enqueue do sweeper pela hora seguinte.

    `atraso_segundos` e a janela de debounce da RN-01.6 (TEC-128). O default e
    zero e nao a janela configurada de proposito: quem atrasa e a ingestao, que
    e o unico ponto onde uma rajada pode estar se formando. O sweeper -- um
    caminho de RECUPERACAO, onde a janela se fechou ha minutos -- e o opt-out
    continuam chamando sem argumento e continuam enfileirando para agora.
    """
    job = await pool.enqueue_job(
        PROCESS_MESSAGE_JOB,
        str(message_id),
        _job_id=f"msg:{message_id}",
        # `or None` e nao o valor cru: `_defer_by=0.0` faria o ARQ somar zero ao
        # score, que da no mesmo -- mas passar None deixa explicito no codigo
        # que "sem atraso" e ausencia de defer, nao defer de duracao nula.
        _defer_by=atraso_segundos or None,
    )
    return job is not None
```

Em `src/mobia/app/config.py`, logo depois de `indicador_de_digitacao_apos_segundos: float = 4.0`:

```python
    # RN-01.6 (TEC-128), com a emenda E-01: a janela vale para TODA mensagem
    # recebida, e nao so para a que integra uma rajada de tres em oito
    # segundos. A condicao original nao e implementavel -- a rajada so e
    # reconhecivel depois de terminada, e a essa altura a resposta a primeira
    # mensagem ja teria saido e a reserva dela em `outbound_dispatches` ja
    # estaria commitada.
    #
    # `float` e nao `int`, pela mesma razao do vizinho acima: o teste precisa
    # de centesimos de segundo, e um `int` os arredondaria para zero.
    #
    # Zero desliga o debounce. E o caminho de fuga se os seis segundos de
    # espera no caso comum -- mensagem isolada, que tambem espera -- pesarem
    # demais no piloto.
    debounce_de_rajada_segundos: float = 6.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_queue.py -v --tb=short
```

Esperado: PASS em todos, inclusive os que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/app/config.py src/mobia/infra/queue.py tests/integration/test_queue.py
git commit -m "feat(TEC-128): a fila sabe atrasar e a janela vira configuracao"
```

---

### Task 2: Quem é o turno se decide por uma consulta

**Files:**
- Create: `src/mobia/domain/messages/rajada.py`
- Test: `tests/integration/test_rajada.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `async def superada_por_mais_nova(session: AsyncSession, message: Message) -> bool`

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_rajada.py`:

```python
"""A pergunta que decide quem, na rajada, e o turno (TEC-128, D3)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.rajada import superada_por_mais_nova
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

LEAD = "5511911112222"
CANAL = "whatsapp"


async def gravar(
    session,
    *,
    created_at: datetime,
    direction: str = MessageDirection.INBOUND,
    role: str = MessageRole.LEAD,
    conversation_key: str = LEAD,
    texto: str = "ainda tem o 2 quartos?",
) -> Message:
    """Grava uma linha com `created_at` EXPLICITO.

    Explicito e nao `server_default`: estes testes precisam controlar a ordem e
    o empate, que e justamente o que o default esconde.
    """
    identificador = uuid.uuid4()
    await session.execute(
        insert(Message).values(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador}",
            sender_external_id=conversation_key,
            recipient_external_id="222222222",
            conversation_key=conversation_key,
            role=role,
            direction=direction,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(texto, aad_de(identificador, "text_body")),
            status=MessageStatus.RECEIVED,
            created_at=created_at,
        )
    )
    await session.commit()
    linha = await session.get(Message, identificador)
    assert linha is not None
    return linha


async def test_mensagem_sozinha_nao_esta_superada(session) -> None:
    agora = datetime.now(UTC)
    unica = await gravar(session, created_at=agora)

    assert await superada_por_mais_nova(session, unica) is False


async def test_mensagem_antiga_esta_superada_pela_nova(session) -> None:
    agora = datetime.now(UTC)
    primeira = await gravar(session, created_at=agora)
    await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await superada_por_mais_nova(session, primeira) is True


async def test_a_mais_nova_nao_esta_superada(session) -> None:
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora)
    ultima = await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await superada_por_mais_nova(session, ultima) is False


async def test_irmas_do_mesmo_envelope_desempatam_por_id(session) -> None:
    """O caso que uma comparacao so por `created_at` perde inteiro.

    Um envelope da Meta com duas mensagens vira um `INSERT` so, numa transacao
    so, e `created_at` e o `now()` da TRANSACAO -- as duas nascem com o mesmo
    instante. Sem o desempate por `id`, cada uma se veria superada pela outra e
    NENHUMA responderia: o lead ficaria sem resposta, nao com duas.
    """
    mesmo_instante = datetime.now(UTC)
    a = await gravar(session, created_at=mesmo_instante)
    b = await gravar(session, created_at=mesmo_instante)

    menor, maior = sorted([a, b], key=lambda linha: linha.id)

    assert await superada_por_mais_nova(session, menor) is True
    assert await superada_por_mais_nova(session, maior) is False


async def test_fala_do_agente_nao_supera_o_lead(session) -> None:
    """A resposta do agente entra na mesma tabela, com o mesmo conversation_key."""
    agora = datetime.now(UTC)
    do_lead = await gravar(session, created_at=agora)
    await gravar(
        session,
        created_at=agora + timedelta(seconds=2),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="Temos sim! Posso te mandar as opcoes?",
    )

    assert await superada_por_mais_nova(session, do_lead) is False


async def test_mensagem_de_outro_lead_nao_supera(session) -> None:
    agora = datetime.now(UTC)
    minha = await gravar(session, created_at=agora)
    await gravar(
        session,
        created_at=agora + timedelta(seconds=2),
        conversation_key="5511999998888",
    )

    assert await superada_por_mais_nova(session, minha) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rajada.py -v --tb=short
```

Esperado: todos FALHAM no import — `ModuleNotFoundError: No module named 'mobia.domain.messages.rajada'`.

- [ ] **Step 3: Implement**

Crie `src/mobia/domain/messages/rajada.py`:

```python
"""Quem, na rajada, e o turno.

A RN-01.6 com a emenda E-01: a ultima mensagem do lead responde por todas. Este
modulo responde a unica pergunta que essa regra exige -- "chegou algo mais novo
deste lead?" -- e nao guarda estado nenhum. "A janela ainda esta aberta" nao e
gravado em lugar nenhum: e recomputado de `messages`, que e onde ja esta.
"""

from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message


async def superada_por_mais_nova(session: AsyncSession, message: Message) -> bool:
    """Chegou INBOUND mais nova deste lead depois de `message`?

    **O desempate por `id` nao e zelo, e obrigatorio.** Um envelope da Meta pode
    trazer varias mensagens, e `IngestionService._persist` as insere num `INSERT`
    so, numa transacao so. Como `created_at` e `server_default=func.now()` e o
    `now()` do Postgres e o instante da TRANSACAO, as irmas do mesmo envelope
    nascem com `created_at` identico. Comparar so por `created_at` faria cada uma
    se considerar superada pelas outras, e NENHUMA responderia -- o lead ficaria
    sem resposta, que e pior que as tres respostas que esta card veio corrigir.

    O par ordenado e o mesmo de `literais_apos` (`context/janela.py`), e pela
    mesma razao; casa com `ix_messages_timeline (channel, conversation_key,
    created_at DESC)`.

    O filtro de direcao existe porque a fala do proprio agente vai para esta
    tabela com o mesmo `conversation_key` da conversa. Sem ele, a resposta de um
    turno superaria a mensagem seguinte do lead e ela nunca seria respondida.
    """
    mais_nova = await session.scalar(
        select(Message.id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.INBOUND,
            tuple_(Message.created_at, Message.id)
            > tuple_(literal(message.created_at), literal(message.id)),
        )
        .limit(1)
    )
    return mais_nova is not None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rajada.py -v --tb=short
```

Esperado: 6 passed.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/rajada.py tests/integration/test_rajada.py
git commit -m "feat(TEC-128): a consulta que diz quem da rajada e o turno"
```

---

### Task 3: A ingestão atrasa, e o job superado sai como `agrupado`

**Files:**
- Modify: `src/mobia/domain/messages/service.py:118-123` (`_try_enqueue`)
- Modify: `src/mobia/workers/jobs/process_message.py:41-43` (o `Literal`) e `:294-300` (depois do `session.get`)
- Test: `tests/integration/test_ingestion_service.py`, `tests/integration/test_process_message_agrupado.py`

**Interfaces:**
- Consumes: `enqueue_process_message(..., atraso_segundos=...)` da Task 1; `superada_por_mais_nova` da Task 2; `Settings.debounce_de_rajada_segundos` da Task 1.
- Produces: `ResultadoDoProcessamento` passa a incluir o literal `"agrupado"`.

- [ ] **Step 1: Write the failing tests**

Acrescente a `tests/integration/test_ingestion_service.py`:

```python
async def test_ingestao_atrasa_o_job_pela_janela(session, redis_pool, monkeypatch) -> None:
    """A ingestao e o unico ponto que atrasa: e onde a rajada pode estar se formando."""
    from datetime import UTC, datetime

    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed()])

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
        assert 5_000 < jobs[0].score - antes_ms < 7_000
    finally:
        get_settings.cache_clear()


async def test_janela_zero_enfileira_para_agora(session, redis_pool, monkeypatch) -> None:
    from datetime import UTC, datetime

    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "0")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed()])

        jobs = await redis_pool.queued_jobs()
        assert jobs[0].score is not None
        assert jobs[0].score - antes_ms < 1_000
    finally:
        get_settings.cache_clear()
```

Crie `tests/integration/test_process_message_agrupado.py`:

```python
"""A mensagem superada fecha sem responder (TEC-128, D4)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

from .test_rajada import gravar  # type: ignore[import-not-found]


class TurnoQueNaoDeviaRodar:
    """Duble que transforma em falha o turno rodar para uma mensagem superada."""

    def __init__(self) -> None:
        self.chamou = False

    async def __call__(self, *args, **kwargs):
        self.chamou = True
        raise AssertionError("executar_turno rodou para uma mensagem superada")


async def test_superada_fecha_como_processed_sem_rodar_o_turno(
    session, redis_pool, monkeypatch
) -> None:
    agora = datetime.now(UTC)
    primeira = await gravar(session, created_at=agora)
    await gravar(session, created_at=agora + timedelta(seconds=2))

    espiao = TurnoQueNaoDeviaRodar()
    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", espiao)

    ctx = {"session_factory": get_sessionmaker()}
    resultado = await process_message(ctx, str(primeira.id))

    assert resultado == "agrupado"
    assert espiao.chamou is False

    await session.commit()
    estado = await session.scalar(select(Message.status).where(Message.id == primeira.id))
    assert estado == MessageStatus.PROCESSED


async def test_superada_registra_processed_at(session, redis_pool, monkeypatch) -> None:
    agora = datetime.now(UTC)
    primeira = await gravar(session, created_at=agora)
    await gravar(session, created_at=agora + timedelta(seconds=2))

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", TurnoQueNaoDeviaRodar()
    )

    await process_message({"session_factory": get_sessionmaker()}, str(primeira.id))

    await session.commit()
    carimbo = await session.scalar(select(Message.processed_at).where(Message.id == primeira.id))
    assert carimbo is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_process_message_agrupado.py tests/integration/test_ingestion_service.py -v --tb=short
```

Esperado: `test_superada_*` FALHAM com `AssertionError: executar_turno rodou para uma mensagem superada` (o job ainda não sabe desviar), e os dois de ingestão FALHAM na comparação de score.

- [ ] **Step 3: Implement**

Em `src/mobia/domain/messages/service.py`, dentro de `_try_enqueue`, troque a chamada:

```python
        try:
            # A janela da RN-01.6 entra AQUI e nao no default da fila: a
            # ingestao e o unico ponto onde uma rajada pode estar se formando.
            # O sweeper, que e recuperacao, e o opt-out, que fura a janela de
            # proposito, chamam sem atraso e continuam enfileirando para agora.
            await enqueue_process_message(
                self._queue,
                message_id,
                atraso_segundos=get_settings().debounce_de_rajada_segundos,
            )
```

Acrescente ao topo do arquivo, junto dos outros imports de `mobia`:

```python
from mobia.app.config import get_settings
```

Em `src/mobia/workers/jobs/process_message.py`, troque o comentário e o `Literal`:

```python
# "skipped" e "agrupado" sao deste modulo; os outros nove vem do turno (Task 6,
# Literal de proposito: ver `ResultadoDoTurno`).
#
# Os dois sao distintos de proposito. "skipped" e anomalia -- claim recusado ou
# a mensagem sumiu entre o claim e a busca. "agrupado" e o caminho FELIZ da
# RN-01.6: a mensagem foi pega, e o certo era nao responder porque outra mais
# nova do mesmo lead assumiu o turno. Colapsar os dois tornaria ilegivel
# qualquer contagem de anomalia no log.
ResultadoDoProcessamento = Literal["skipped", "agrupado"] | ResultadoDoTurno
```

Acrescente o import:

```python
from mobia.domain.messages.rajada import superada_por_mais_nova
```

E, logo depois da guarda `if linha is None:` (por volta da linha 298), antes do bloco do indicador:

```python
        async with session_factory() as session:
            if await superada_por_mais_nova(session, linha):
                await session.execute(
                    update(Message)
                    .where(Message.id == identifier)
                    .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
                )
                await session.commit()
                log.info("message.agrupado", message_id=message_id)
                return "agrupado"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_process_message_agrupado.py tests/integration/test_ingestion_service.py tests/integration/test_rajada.py -v --tb=short
```

Esperado: PASS em todos.

- [ ] **Step 5: Rode a vizinhança que este desvio pode ter quebrado**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_recepcao_de_mensagem.py tests/features/test_reprocessamento_apos_falha.py tests/integration/test_sweep_stalled.py --tb=short
```

Esperado: PASS. Se algum teste de feature falhar por *timeout esperando resposta*, é a janela de 6s entrando onde o teste não a esperava — a correção é o teste fixar `DEBOUNCE_DE_RAJADA_SEGUNDOS=0`, não baixar o default.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A
git commit -m "feat(TEC-128): so a ultima da rajada roda o turno"
```

---

### Task 4: O opt-out fura a janela pelos dois lados

**Files:**
- Modify: `src/mobia/domain/messages/service.py` (`_persist` devolve o par, `ingest` decide o atraso, `_try_enqueue` recebe o atraso)
- Modify: `src/mobia/workers/jobs/process_message.py` (a guarda da Task 3 ganha exceção)
- Test: `tests/integration/test_optout_fura_a_janela.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-3.
- Produces: `IngestionService._persist` passa a devolver `list[tuple[uuid.UUID, str]]` — `(id, provider_message_id)` — em vez de `list[uuid.UUID]`. `ingest()` continua devolvendo `list[uuid.UUID]`, então nada fora da classe muda.

**Por que os dois furos, e não um:** sem **(a)**, a confirmação de opt-out chega 6 segundos depois. Sem **(b)**, um opt-out seguido de outra mensagem nos milissegundos seguintes é declarado superado e **nunca é registrado** — o lead pediu para parar e o sistema não gravou. É este segundo caso que a TEC-182 previu por escrito.

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_optout_fura_a_janela.py`:

```python
"""O opt-out nao espera a janela, e a janela nao pode engoli-lo (TEC-128, D5)."""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker

from .test_rajada import gravar  # type: ignore[import-not-found]

PEDIDO = "nao quero mais receber mensagens"


def parsed_com(texto: str, sufixo: str = "") -> ParsedMessage:
    identificador = sufixo or uuid.uuid4().hex
    return ParsedMessage(
        provider_message_id=f"wamid.{identificador}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body=texto,
        raw_payload={"id": f"wamid.{identificador}", "type": "text"},
    )


async def test_optout_nao_espera_a_janela(session, redis_pool, monkeypatch) -> None:
    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed_com(PEDIDO)])

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
        assert jobs[0].score - antes_ms < 1_000
    finally:
        get_settings.cache_clear()


async def test_mensagem_comum_no_mesmo_lote_continua_esperando(
    session, redis_pool, monkeypatch
) -> None:
    """Um envelope com as duas: cada uma recebe o seu proprio tratamento."""
    from mobia.app.config import get_settings

    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "6")
    get_settings.cache_clear()
    try:
        service = IngestionService(get_sessionmaker(), redis_pool)
        antes_ms = datetime.now(UTC).timestamp() * 1000

        await service.ingest([parsed_com("ainda tem o 2 quartos?", "A"), parsed_com(PEDIDO, "B")])

        jobs = {job.job_id: job for job in await redis_pool.queued_jobs()}
        assert len(jobs) == 2
        atrasos = sorted(job.score - antes_ms for job in jobs.values() if job.score is not None)
        assert atrasos[0] < 1_000
        assert 5_000 < atrasos[1] < 7_000
    finally:
        get_settings.cache_clear()


async def test_optout_superado_ainda_roda_o_turno(session, redis_pool, monkeypatch) -> None:
    """O defeito que a TEC-182 previu: sem esta excecao, o opt-out sumiria.

    O lead pede para parar e, nos milissegundos seguintes, manda outra coisa. A
    checagem de superacao declararia o opt-out superado e ele nunca seria
    registrado -- em silencio, sem log de erro e sem nada no banco.
    """
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    pedido = await gravar(session, created_at=agora, texto=PEDIDO)
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="ou melhor, me liga")

    rodou = {"turno": False}

    async def turno_espiao(*args, **kwargs):
        rodou["turno"] = True
        return "opt_out"

    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", turno_espiao)

    resultado = await process_message({"session_factory": get_sessionmaker()}, str(pedido.id))

    assert rodou["turno"] is True
    assert resultado != "agrupado"


async def test_superada_que_nao_pediu_optout_continua_agrupando(
    session, redis_pool, monkeypatch
) -> None:
    """A excecao da D5 nao pode virar um furo geral na D3."""
    from mobia.workers.jobs.process_message import process_message

    agora = datetime.now(UTC)
    comum = await gravar(session, created_at=agora, texto="ainda tem o 2 quartos?")
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="ou de 3?")

    async def turno_que_nao_devia_rodar(*args, **kwargs):
        raise AssertionError("executar_turno rodou para uma mensagem superada comum")

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", turno_que_nao_devia_rodar
    )

    resultado = await process_message({"session_factory": get_sessionmaker()}, str(comum.id))

    assert resultado == "agrupado"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_optout_fura_a_janela.py -v --tb=short
```

Esperado: os três primeiros FALHAM (score atrasado onde devia ser imediato; `"agrupado"` onde o turno devia rodar). `test_superada_que_nao_pediu_optout_continua_agrupando` já passa — é o teste de não-regressão da Task 3.

- [ ] **Step 3: Implement o furo (a) — a ingestão não atrasa opt-out**

Em `src/mobia/domain/messages/service.py`:

Troque a última linha de `_persist` para devolver o par que o `RETURNING` **já traz**:

```python
        # O `RETURNING` ja trazia `provider_message_id` para a contagem de
        # descartes do TEC-125; agora ele tambem e a unica forma de casar cada
        # id gravado com o texto em claro do `ParsedMessage` que o originou --
        # `inseridas` pode ser subconjunto de `parsed`, sem garantia de ordem.
        return [(linha.id, linha.provider_message_id) for linha in inseridas]
```

Ajuste a anotação de retorno e a linha do log dentro de `_persist`:

```python
    async def _persist(
        self, parsed: list[ParsedMessage], channel: str
    ) -> list[tuple[uuid.UUID, str]]:
```

```python
        message_ids = [linha.id for linha in inseridas]
```
(essa linha continua como está, só deixa de ser o valor de retorno)

Troque `ingest`:

```python
    async def ingest(
        self, parsed: list[ParsedMessage], channel: str = "whatsapp"
    ) -> list[uuid.UUID]:
        if not parsed:
            return []

        gravadas = await self._persist(parsed, channel)
        texto_de = {item.provider_message_id: item.text_body for item in parsed}
        janela = get_settings().debounce_de_rajada_segundos
        for message_id, provider_message_id in gravadas:
            # O opt-out nao espera a janela (RN-01.6 + RN-14). `pediu_optout` e
            # puro e determinístico, sem chamada paga, e aqui o texto ainda
            # esta em claro -- e o unico ponto do fluxo onde ele esta.
            pediu = pediu_optout(texto_de.get(provider_message_id) or "")
            await self._try_enqueue(message_id, atraso_segundos=0.0 if pediu else janela)
        return [message_id for message_id, _ in gravadas]
```

Troque a assinatura de `_try_enqueue` e a chamada dentro dela:

```python
    async def _try_enqueue(self, message_id: uuid.UUID, *, atraso_segundos: float = 0.0) -> None:
```
```python
            await enqueue_process_message(
                self._queue, message_id, atraso_segundos=atraso_segundos
            )
```

E acrescente o import:

```python
from mobia.domain.optout.deteccao import pediu_optout
```

- [ ] **Step 4: Implement o furo (b) — a superação não engole opt-out**

Em `src/mobia/workers/jobs/process_message.py`, troque a guarda da Task 3:

```python
        async with session_factory() as session:
            if await superada_por_mais_nova(session, linha):
                # A excecao existe por um defeito que a TEC-182 previu por
                # escrito. Sem ela: o lead pede para parar e, nos milissegundos
                # seguintes, manda outra coisa; esta mensagem sai como
                # "agrupado", `pediu_optout` nunca roda sobre ela, e o opt-out
                # NUNCA e registrado -- em silencio, sem log de erro.
                #
                # O enqueue sem atraso de `IngestionService.ingest` nao basta:
                # ele vence a corrida no caso comum, nao em todos.
                #
                # Nao ha decisao duplicada com o turno: e a mesma funcao pura
                # sobre o mesmo texto da mesma mensagem, entao os dois sitios
                # nao tem como divergir sem que `pediu_optout` mude para ambos.
                corpo = decrypt(linha.text_body, aad_de(linha.id, "text_body"))
                if not pediu_optout(corpo):
                    await session.execute(
                        update(Message)
                        .where(Message.id == identifier)
                        .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
                    )
                    await session.commit()
                    log.info("message.agrupado", message_id=message_id)
                    return "agrupado"
                log.info("message.optout_fura_a_janela", message_id=message_id)
```

Acrescente os imports:

```python
from mobia.domain.optout.deteccao import pediu_optout
from mobia.infra.crypto import aad_de, decrypt
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_optout_fura_a_janela.py tests/integration/test_process_message_agrupado.py tests/integration/test_ingestion_service.py -v --tb=short
```

Esperado: PASS em todos.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A
git commit -m "feat(TEC-128): o opt-out nao espera a janela nem e engolido por ela"
```

---

### Task 5: O indicador de digitação passa a contar do recebimento

**Files:**
- Modify: `src/mobia/workers/jobs/process_message.py:311-316` (o argumento `apos_segundos`)
- Test: `tests/integration/test_indicador_de_digitacao.py`

**Interfaces:**
- Consumes: nada novo. `indicador_de_digitacao(...)` mantém a assinatura de hoje — muda só o valor que o job calcula e passa.

**Por que está nesta card:** a TEC-274 promete avisar quando a resposta passa de 4 segundos, e mede isso do início do job. Com o defer, o job começa 6 segundos depois de o lead apertar enviar, então o indicador sairia em `última + 10s` e o lead ficaria 6 segundos em silêncio absoluto. Não é feature nova — é reparar dano que esta card causa. A docstring da própria TEC-274 já diz qual é o relógio certo: *"o silencio que o lead percebe"*.

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/integration/test_indicador_de_digitacao.py`:

```python
async def test_mensagem_que_ja_esperou_a_janela_indica_na_hora(
    session, monkeypatch, redis_pool
) -> None:
    """O relogio do indicador conta do recebimento, nao do inicio do job.

    Com o debounce, o job so comeca uma janela depois de o lead apertar enviar.
    Medir do inicio do job somaria as duas esperas e deixaria o lead em silencio
    absoluto durante a janela inteira -- que e o oposto do que a TEC-274 quis.
    """
    from datetime import UTC, datetime, timedelta

    from mobia.app.config import get_settings
    from mobia.infra.db import get_sessionmaker
    from mobia.workers.jobs.process_message import process_message

    from .test_rajada import gravar  # type: ignore[import-not-found]

    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "4")
    get_settings.cache_clear()
    try:
        # Recebida ha oito segundos: mais velha que o limiar de quatro.
        antiga = await gravar(
            session, created_at=datetime.now(UTC) - timedelta(seconds=8)
        )
        esperas: list[float] = []

        async def registrar_espera(segundos: float) -> None:
            esperas.append(segundos)

        monkeypatch.setattr("mobia.domain.outbound.presenca.asyncio.sleep", registrar_espera)

        async def turno_instantaneo(*args, **kwargs):
            return "respondido"

        monkeypatch.setattr(
            "mobia.workers.jobs.process_message.executar_turno", turno_instantaneo
        )

        class IndicadorDeTeste:
            async def indicar_digitacao(self, **kwargs) -> None:
                return None

        await process_message(
            {"session_factory": get_sessionmaker(), "indicador": IndicadorDeTeste()},
            str(antiga.id),
        )

        assert esperas == [0.0]
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_de_digitacao.py::test_mensagem_que_ja_esperou_a_janela_indica_na_hora -v --tb=short
```

Esperado: FAIL com `assert [4.0] == [0.0]` — hoje o job passa o valor configurado cru.

- [ ] **Step 3: Implement**

Em `src/mobia/workers/jobs/process_message.py`, logo antes do `async with indicador_de_digitacao(`:

```python
        # TEC-128: o relogio conta do RECEBIMENTO, nao do inicio do job. Com o
        # debounce da RN-01.6 o job so comeca uma janela depois de o lead
        # apertar enviar; somar as duas esperas deixaria o lead em silencio
        # absoluto durante a janela inteira -- o oposto do que a TEC-274 quis
        # quando escreveu que o relogio mede "o silencio que o lead percebe".
        idade = (datetime.now(UTC) - linha.created_at).total_seconds()
        apos_segundos = max(0.0, get_settings().indicador_de_digitacao_apos_segundos - idade)
```

E troque o argumento:

```python
        async with indicador_de_digitacao(
            session_factory,
            message=linha,
            indicador=ctx["indicador"],
            apos_segundos=apos_segundos,
        ):
```

Substitua o parágrafo final do comentário que está logo acima do `async with` (o que começa em "Mora AQUI e nao dentro de `executar_turno`") mantendo-o intacto — ele continua verdadeiro e não deve ser apagado.

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_de_digitacao.py -v --tb=short
```

Esperado: PASS em todos, inclusive os que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A
git commit -m "fix(TEC-128): o indicador conta do recebimento e nao do inicio do job"
```

---

### Task 6: Os quatro cenários da card, ponta a ponta

**Files:**
- Create: `tests/features/test_debounce_de_rajada.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-5.
- Produces: nada — é a prova de que a card está satisfeita.

Estes testes entram pelo webhook, como os da TEC-125, e não chamam o job diretamente. Usam janela curta (centésimos) por configuração.

- [ ] **Step 1: Write the tests**

Crie `tests/features/test_debounce_de_rajada.py`:

```python
"""Cenarios Gherkin de TEC-128.

Funcionalidade: Agrupamento de rajada de mensagens
"""

import asyncio
import json

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

JANELA = "0.3"


def envelope(wamid: str, texto: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [
                                {
                                    "from": "5511911112222",
                                    "id": wamid,
                                    "timestamp": "1755900000",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def assinado(payload: dict, secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    return body, {
        SIGNATURE_HEADER: compute_signature(secret, body),
        "Content-Type": "application/json",
    }


async def enviar(client, settings, wamid: str, texto: str) -> None:
    body, headers = assinado(envelope(wamid, texto), settings.whatsapp_app_secret)
    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200


async def test_tres_mensagens_em_rajada_viram_um_turno(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Tres mensagens em cinco segundos viram um turno.

    A prova e sobre a FILA, nao sobre a resposta: o que a card pede e que so
    uma das tres carregue o turno. Rodar o turno de verdade exigiria o
    classificador, que e outro assunto.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.R1", "oi")
        await enviar(client, settings, "wamid.R2", "procuro apartamento")
        await enviar(client, settings, "wamid.R3", "ate 500 mil")

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 3
        # As tres esperam, e nenhuma esta pronta agora: e isso que impede as
        # tres respostas.
        assert all(job.score is not None for job in jobs)
    finally:
        get_settings.cache_clear()


async def test_mensagem_nova_empurra_o_fim_da_espera(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Mensagem nova durante a espera reinicia o debounce.

    Reiniciar nao e um mecanismo aqui: cada mensagem carrega o proprio relogio,
    entao o instante em que a ULTIMA acorda ja e `ultima + janela`.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.E1", "oi")
        primeiro = {job.job_id: job.score for job in await redis_pool.queued_jobs()}

        await asyncio.sleep(0.1)
        await enviar(client, settings, "wamid.E2", "procuro apartamento")

        jobs = {job.job_id: job.score for job in await redis_pool.queued_jobs()}
        nova = next(score for job_id, score in jobs.items() if job_id not in primeiro)
        antiga = next(iter(primeiro.values()))
        assert nova is not None and antiga is not None
        assert nova > antiga
    finally:
        get_settings.cache_clear()


async def test_mensagem_isolada_tambem_espera_a_janela(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Mensagem isolada nao espera -- com a emenda E-01, ela espera.

    A card intitula o cenario "nao espera" e o corpo dele diz "quando os 6
    segundos de debounce se esgotam". O corpo e que descreve o sistema: a
    espera e incondicional, porque a rajada so e reconhecivel depois de
    terminada. Ver a D1 do desenho e a emenda E-01.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.S1", "ainda tem o 2 quartos?")

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
    finally:
        get_settings.cache_clear()


async def test_optout_na_rajada_nao_espera(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Opt-out nao espera o fim da rajada."""
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "30")
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.O1", "oi")
        await enviar(client, settings, "wamid.O2", "nao quero mais receber mensagens")

        jobs = {job.job_id: job for job in await redis_pool.queued_jobs()}
        assert len(jobs) == 2

        optout = await session.scalar(
            select(Message).where(Message.provider_message_id == "wamid.O2")
        )
        assert optout is not None
        pronto = jobs[f"msg:{optout.id}"]
        comum = next(job for job_id, job in jobs.items() if job_id != f"msg:{optout.id}")
        assert pronto.score is not None and comum.score is not None
        assert pronto.score < comum.score
    finally:
        get_settings.cache_clear()


async def test_todas_da_rajada_ficam_gravadas(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """A resposta contempla as tres porque as tres estao no banco.

    O agrupamento nao descarta conteudo: a mensagem superada fecha como
    PROCESSED e entra no contexto do turno da carregadora pela janela de
    `literais_apos`, que e o mecanismo que ja existia.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.G1", "oi")
        await enviar(client, settings, "wamid.G2", "procuro apartamento")
        await enviar(client, settings, "wamid.G3", "ate 500 mil")

        total = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.direction == MessageDirection.INBOUND)
        )
        assert total == 3
        estados = await session.scalars(select(Message.status))
        assert set(estados) == {MessageStatus.QUEUED}
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/features/test_debounce_de_rajada.py -v --tb=short
```

Esperado: PASS em todos. Se algum falhar, é defeito nas Tasks 1-5 — conserte lá, não afrouxe o teste.

- [ ] **Step 3: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/features/test_debounce_de_rajada.py
git commit -m "test(TEC-128): os quatro cenarios da card entram pelo webhook"
```

---

### Task 7: A prosa que a mudança tornou falsa

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md:130`
- Modify: `docs/superpowers/specs/2026-09-01-tec-182-opt-out-design.md:161`
- Modify: `docs/superpowers/specs/2026-08-23-tec-122-ingestao-whatsapp-design.md:25`
- Modify: `docs/superpowers/specs/2026-09-21-tec-128-debounce-de-rajada-design.md` (Status)
- Modify: `CLAUDE.md:209`

- [ ] **Step 1: A emenda ao SRS**

Sob a RN-01.6 em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md:130`, como item **aninhado**, sem reescrever o texto de 22/08/2026:

```markdown
  - Emenda E-01 (TEC-128, 21/09/2026): o debounce é **incondicional** — toda mensagem recebida aguarda a janela antes de virar turno, e não apenas a que integra uma rajada de três em oito segundos. A condição original não é implementável: a rajada só é reconhecível depois de terminada, e a essa altura a resposta à primeira mensagem já teria sido entregue e a reserva dela em `outbound_dispatches` já estaria commitada. A janela é configurável (`debounce_de_rajada_segundos`, default 6 s) e mensagem de opt-out não a aguarda.
```

- [ ] **Step 2: As três notas de prosa**

Em `2026-09-01-tec-182-opt-out-design.md:161`, ao fim do parágrafo que diz *"procurar por `debounce` devolve zero"*:

```markdown
> **Atualizado pela TEC-128 (21/09/2026):** a RN-01.6 foi implementada e este parágrafo descreve o repo de antes. O cenário deixou de ser vacuamente verdadeiro, e o furo que ele pedia existe em dois pontos — ver a D5 de `2026-09-21-tec-128-debounce-de-rajada-design.md`.
```

Em `2026-08-23-tec-122-ingestao-whatsapp-design.md:25`, a justificativa da escolha do ARQ cita o `cron` "que TEC-128 (debounce 6s) […] vai precisar". Acrescente ao fim da célula:

```markdown
(A TEC-128 acabou usando `_defer_by`, não `cron`; a escolha do ARQ continua certa, a justificativa é que não se confirmou para esta card.)
```

Em `CLAUDE.md:209`, troque `1877 linhas` por `2706 linhas`.

No cabeçalho de `2026-09-21-tec-128-debounce-de-rajada-design.md`, troque o Status para `implementado`.

- [ ] **Step 3: Rode a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO`, `VIZINHO`, `PROSA`, `FALSO` e `NOMEIA`. `FALSO` é o único que afirma em vez de suspeitar — se aparecer algum, é citação apontando além do fim de um arquivo que a branch mexeu, e tem de ser corrigida. A listagem não é gate e não reprova nada; o julgamento é seu.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(TEC-128): a emenda E-01 e a prosa que o debounce tornou falsa"
```

---

### Task 8: A suíte inteira, uma vez

- [ ] **Step 1: Rode a suíte**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

**Uma execução verde basta.** Guarde o hash junto com o resultado.

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — é o Postgres caindo sob o paralelismo. Rode por blocos:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short
./.venv/Scripts/python.exe -m pytest tests/features --tb=short
```

Se a falha for uma só, com `ConnectionResetError [WinError 64]` na negociação SSL, ela **não autoriza conclusão nenhuma** — nem a favor nem contra a mudança. Se a primeira execução falhar de verdade, repita sobre a mesma árvore antes de culpar a branch: é a única coisa que separa flake de regressão.

- [ ] **Step 2: Push e PR**

```bash
git push -u origin feat/tec-128-debounce-de-rajada
gh pr create --base main --title "TEC-128: a rajada de mensagens vira um turno so" --body "<corpo>"
```

- [ ] **Step 3: Comentar na card e mover para "Em análise"**

O comentário registra o que some se ficar só no PR:

- **A divergência da card:** o debounce é incondicional, e a condição "3 mensagens em menos de 8 segundos" não é implementável. Emenda **E-01** ao SRS, sob a RN-01.6.
- **O cenário "Mensagem isolada não espera"** foi implementado como *espera a janela* — o título da card diz uma coisa e o corpo do cenário diz outra; o corpo é que descreve o sistema.
- **Lacuna que é decisão de produto:** toda mensagem passa a custar a janela de latência, inclusive a isolada, que é o caso comum. O valor nasce em 6 s e é configurável; zero desliga.
- **O que a card não entrega:** a exclusão mútua entre workers continua parcial (TEC-218) — o debounce reduz a chance de dois turnos simultâneos do mesmo lead, mas não a elimina.
- **Escopo a mais, com razão:** o indicador de digitação passou a contar do recebimento. Sem isso, a TEC-274 deixaria de cumprir o que promete no exato momento em que esta card entra.

Mover para **Em análise** (transição `31`), não para Feito — quem mergeia é que fecha.

---

## Self-review do plano

**Cobertura do desenho:** D1 → Task 7 (emenda) e o teste da Task 6; D2 → Task 1; D3 → Task 2; D4 → Task 3; D5 → Task 4; D6 → Task 5; D7 → conferido na Task 3, Step 5 (o sweeper continua sem atraso, e o teste de `test_sweep_stalled.py` roda lá); D8 → Task 1; D9 → Task 7. Os quatro cenários Gherkin da card → Task 6.

**Tipos e nomes, conferidos entre tarefas:** `enqueue_process_message(..., *, atraso_segundos: float = 0.0)` é o mesmo nome na Task 1, na Task 3 e na Task 4. `superada_por_mais_nova(session, message)` é o mesmo da Task 2 na Task 3 e na Task 4. `_persist` muda de tipo de retorno só na Task 4, e `ingest` absorve a mudança sem alterar a própria assinatura pública — nenhum chamador externo vê diferença.

**Onde a Task 3 pode quebrar a suíte existente:** qualquer teste que hoje envie pelo webhook e espere o job estar pronto imediatamente passa a esperar 6 s. O Step 5 da Task 3 roda essa vizinhança de propósito, e a instrução é fixar a janela em zero no teste, nunca baixar o default.

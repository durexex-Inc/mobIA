# TEC-295 — Moderação na rajada: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a mensagem que o debounce agrupa passar pela moderação de entrada, e fazer a rajada cuja última mensagem é bloqueada ainda responder a pergunta legítima que veio antes dela.

**Architecture:** A moderação entra no ramo de `process_message` que hoje fecha `"agrupado"`, chamando a mesma `marcar_bloqueada` que o turno usa — marca e auditoria num commit só. No turno, o bloco de bloqueio de entrada deixa de retornar cedo quando a recusa foi entregue **e** existe fala do lead pendente de resposta; como `marcar_bloqueada` roda antes, o contexto que o turno monta já exclui a própria fala bloqueada.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, ARQ sobre Redis, Postgres, Anthropic (Haiku 4.5 para moderação), pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-09-21-tec-295-moderacao-na-rajada-design.md`](../specs/2026-09-21-tec-295-moderacao-na-rajada-design.md)

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado — citação de texto que o lead recebe mantém o acento do literal.
- **Texto que o lead recebe: português COM acento.** Esta card não cria texto novo para o lead; `TEXTO_DA_RECUSA_DE_ENTRADA` já existe.
- **Prosa em `docs/` e `.md`: com acento.**
- **Comentário desatualizado é defeito neste repo, não sujeira.**
- **Os três gates, nesta ordem, antes de cada commit:**
  ```
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
  `ruff check` passar não diz nada sobre `ruff format`. O `mypy` roda **sem argumento**.
- **Loop rápido:** `./.venv/Scripts/python.exe -m pytest tests/unit` (~4s, sem `docker compose`). `tests/integration` e `tests/features` exigem os containers.
- **Nenhum teste faz chamada paga.** A moderação em teste é sempre o `ModeradorFake` de `tests/conftest.py:508-553`.
- **`tests/` não tem `__init__.py`.** Import de helper entre arquivos de teste é **absoluto** (`from test_rajada import gravar`), nunca relativo.
- **Commits:** `tipo(TEC-295): o que passou a ser verdade`, assunto em português sem acento.

## As quatro garantias que a implementação não pode reabrir

Copiadas do desenho, porque toda tarefa as tem de respeitar:

1. **(TEC-233)** A fala reprovada na entrada nunca vira a resposta daquele turno.
2. **(TEC-236)** A fala reprovada nunca entra em contexto de turno nenhum nem no resumo permanente.
3. **(TEC-236/TEC-142)** Marca e auditoria saem no mesmo commit; não existe "marcada sem auditoria".
4. **(TEC-150/cadência)** Score e follow-up usam `direction=INBOUND AND bloqueada_em IS NULL`, a mesma definição da janela de contexto.

---

### Task 1: A consulta que diz se ficou pergunta sem resposta

**Files:**
- Modify: `src/mobia/domain/messages/rajada.py` (arquivo de 46 linhas, ganha uma segunda função)
- Test: `tests/integration/test_rajada.py` (já existe, com o helper `gravar`)

**Interfaces:**
- Consumes: nada.
- Produces: `async def ha_fala_pendente_antes(session: AsyncSession, message: Message) -> bool`, consumida pela Task 4.

**Por que existe:** a Task 4 faz o turno bloqueado continuar e responder. Se a mensagem bloqueada for a única — sem rajada —, continuar faria o agente responder ao histórico anterior, que é o engajamento que a TEC-233 recusou. Esta consulta é a condição que impede isso.

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/integration/test_rajada.py` (o arquivo já importa `gravar`, `MessageDirection`, `MessageRole`, `datetime`, `timedelta`):

```python
async def test_sem_nada_antes_nao_ha_fala_pendente(session) -> None:
    """Mensagem isolada: nao ha pergunta orfa para o turno bloqueado responder."""
    from mobia.domain.messages.rajada import ha_fala_pendente_antes

    unica = await gravar(session, created_at=datetime.now(UTC))

    assert await ha_fala_pendente_antes(session, unica) is False


async def test_irma_mais_antiga_sem_resposta_conta(session) -> None:
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos ate 500 mil?")
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    assert await ha_fala_pendente_antes(session, ultima) is True


async def test_irma_mais_antiga_ja_bloqueada_nao_conta(session) -> None:
    """Fala bloqueada nao e pergunta legitima -- e a mesma definicao que o
    score e a cadencia de follow-up usam."""
    from sqlalchemy import update

    from mobia.domain.messages.models import Message
    from mobia.domain.messages.rajada import ha_fala_pendente_antes

    agora = datetime.now(UTC)
    bloqueada = await gravar(session, created_at=agora)
    await session.execute(
        update(Message).where(Message.id == bloqueada.id).values(bloqueada_em=agora)
    )
    await session.commit()
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    assert await ha_fala_pendente_antes(session, ultima) is False


async def test_fala_do_agente_entre_as_duas_fecha_a_pendencia(session) -> None:
    """O agente ja respondeu a primeira: nao ha nada pendente antes da segunda."""
    from mobia.domain.messages.rajada import ha_fala_pendente_antes

    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos?")
    await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="Temos sim! Posso te mandar as opcoes?",
    )
    ultima = await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await ha_fala_pendente_antes(session, ultima) is False


async def test_pendente_atras_de_uma_bloqueada_ainda_conta(session) -> None:
    """O caso que uma consulta ingenua perde.

    Olhar so a mensagem IMEDIATAMENTE anterior daria False aqui, porque a
    imediatamente anterior esta bloqueada -- e a pergunta legitima de antes
    dela ficaria orfa em silencio.
    """
    from sqlalchemy import update

    from mobia.domain.messages.models import Message
    from mobia.domain.messages.rajada import ha_fala_pendente_antes

    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos ate 500 mil?")
    bloqueada = await gravar(session, created_at=agora + timedelta(seconds=1))
    await session.execute(
        update(Message)
        .where(Message.id == bloqueada.id)
        .values(bloqueada_em=agora + timedelta(seconds=1))
    )
    await session.commit()
    ultima = await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await ha_fala_pendente_antes(session, ultima) is True


async def test_pendente_de_outro_lead_nao_conta(session) -> None:
    from mobia.domain.messages.rajada import ha_fala_pendente_antes

    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, conversation_key="5511999998888")
    minha = await gravar(session, created_at=agora + timedelta(seconds=1))

    assert await ha_fala_pendente_antes(session, minha) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rajada.py -v --tb=short
```

Esperado: os seis novos FALHAM com `ImportError: cannot import name 'ha_fala_pendente_antes'`.

- [ ] **Step 3: Implement**

Em `src/mobia/domain/messages/rajada.py`, troque a linha de import do SQLAlchemy por

```python
from sqlalchemy import func, literal, or_, select, tuple_
```

e acrescente ao fim do arquivo:

```python
async def ha_fala_pendente_antes(session: AsyncSession, message: Message) -> bool:
    """Ficou fala do lead sem resposta antes desta mensagem?

    Existe INBOUND deste lead, nao bloqueada, mais antiga que `message` e mais
    nova que a ultima fala do agente? Se existe, o lead perguntou alguma coisa
    que ninguem respondeu -- tipicamente uma irma de rajada que fechou
    "agrupado" enquanto esta mensagem carregava o turno.

    **Nao basta olhar a mensagem imediatamente anterior.** Numa rajada em que a
    penultima foi bloqueada pela moderacao e a antepenultima era legitima, a
    imediatamente anterior esta bloqueada e a pergunta legitima ficaria orfa.
    Por isso a fronteira e a ultima fala do AGENTE, e nao a linha vizinha.

    A fronteira do agente compara so `created_at`, e nao o par ordenado que
    `superada_por_mais_nova` usa contra `message`: fala do agente nasce uma de
    cada vez, pelo recorder, nunca num lote de envelope, entao nao ha ali o
    empate de instante que obriga o desempate por `id` do lado do lead.

    `bloqueada_em IS NULL` e a mesma definicao de "fala do lead" que
    `contar_mensagens_do_lead` (`context/repositorio.py`) e a ancora da
    cadencia de follow-up (`followup/repositorio.py`) usam. `context/score.py`
    registra que as tres leituras tem de concordar; esta e a quarta.
    """
    ultima_do_agente = (
        select(func.max(Message.created_at))
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.OUTBOUND,
        )
        .scalar_subquery()
    )
    pendente = await session.scalar(
        select(Message.id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.INBOUND,
            Message.bloqueada_em.is_(None),
            tuple_(Message.created_at, Message.id)
            < tuple_(literal(message.created_at), literal(message.id)),
            # Conversa sem nenhuma fala do agente ainda: `MAX` devolve NULL e
            # toda INBOUND anterior conta.
            or_(ultima_do_agente.is_(None), Message.created_at > ultima_do_agente),
        )
        .limit(1)
    )
    return pendente is not None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_rajada.py -v --tb=short
```

Esperado: todos passam, inclusive os que já existiam.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/rajada.py tests/integration/test_rajada.py
git commit -m "feat(TEC-295): a consulta que diz se ficou pergunta sem resposta"
```

---

### Task 2: A mensagem agrupada passa pela moderação de entrada

**Files:**
- Modify: `src/mobia/workers/jobs/process_message.py` (o ramo `else` da guarda de superação, e uma função nova de módulo)
- Test: `tests/integration/test_moderacao_na_rajada.py` (criar)

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `async def _moderar_superada(session_factory, linha: Message, corpo: str, *, moderador: ModeradorPort) -> bool` — devolve se bloqueou. Privada do módulo; nenhuma tarefa posterior a chama.

**Onde entra, exatamente:** no bloco da guarda de superação (`if await superada_por_mais_nova(...)`), dentro do `else` final — o ramo que hoje fecha `PROCESSED` e retorna `"agrupado"`. **Não** nos três ramos que já furam a janela (opt-out, pedido de humano, entrega parcial): nesses o turno roda e a moderação acontece pelo caminho normal de `turno.py`.

- [ ] **Step 1: Write the failing tests**

Crie `tests/integration/test_moderacao_na_rajada.py`:

```python
"""A mensagem agrupada passa pela moderacao de entrada (TEC-295, D1-D3)."""

from datetime import UTC, datetime, timedelta

from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake  # type: ignore[import-not-found]
from sqlalchemy import func, select
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel, Veredito
from mobia.domain.outbound.port import GuardedOutbound
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

REPROVAVEL = "texto que a moderacao reprova"


class ModeradorQueBloqueia:
    """Bloqueia so o texto combinado, e conta quantas vezes foi chamado."""

    def __init__(self, texto_bloqueado: str = REPROVAVEL) -> None:
        self.texto_bloqueado = texto_bloqueado
        self.chamadas: list[str] = []

    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito:
        self.chamadas.append(texto)
        if texto == self.texto_bloqueado:
            return Veredito(bloqueado=True, motivo="teste", categoria="ASSEDIO")
        return Veredito(bloqueado=False, motivo="liberado")


class ModeradorCaido:
    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito:
        raise ModeracaoIndisponivel("provedor fora do ar")


def _ctx(moderador) -> dict:
    """O ctx de oito chaves que `process_message` exige.

    Molde de `tests/integration/test_process_message_agrupado.py`; so o
    moderador varia entre os testes deste arquivo.
    """
    return {
        "session_factory": get_sessionmaker(),
        "outbound": GuardedOutbound(get_sessionmaker()),
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": moderador,
        "agendador": AgendadorNoop(),
        "indicador": IndicadorNoop(),
    }


async def test_superada_reprovavel_recebe_marca_e_auditoria(session) -> None:
    """A garantia 3: marca e evento saem juntos, pela mesma `marcar_bloqueada`."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    await gravar(session, created_at=agora + timedelta(seconds=1))

    moderador = ModeradorQueBloqueia()
    resultado = await process_message(_ctx(moderador), str(superada.id))

    assert resultado == "agrupado"
    await session.commit()
    linha = await session.get(Message, superada.id)
    assert linha is not None
    await session.refresh(linha)
    assert linha.bloqueada_em is not None
    eventos = await session.scalar(
        select(func.count())
        .select_from(ModerationEvent)
        .where(ModerationEvent.message_id == superada.id)
    )
    assert eventos == 1


async def test_superada_liberada_nao_ganha_marca(session) -> None:
    """A D1 nao pode bloquear o caminho comum."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto="tem 2 quartos?")
    await gravar(session, created_at=agora + timedelta(seconds=1))

    moderador = ModeradorQueBloqueia()
    resultado = await process_message(_ctx(moderador), str(superada.id))

    assert resultado == "agrupado"
    assert moderador.chamadas == ["tem 2 quartos?"]
    await session.commit()
    linha = await session.get(Message, superada.id)
    assert linha is not None
    await session.refresh(linha)
    assert linha.bloqueada_em is None


async def test_superada_bloqueada_ainda_fecha_agrupado(session) -> None:
    """A D3: ela ganha a marca, nao vira turno e nao gera recusa propria."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    await gravar(session, created_at=agora + timedelta(seconds=1))

    resultado = await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))

    assert resultado == "agrupado"
    await session.commit()
    estado = await session.scalar(select(Message.status).where(Message.id == superada.id))
    assert estado == MessageStatus.PROCESSED


async def test_moderacao_indisponivel_nao_derruba_o_agrupamento(session) -> None:
    """A D2: fail-open. Deixar subir faria `attempts` crescer e, esgotadas as
    cinco, o lead receberia um aviso de erro por uma mensagem que so precisava
    ser agrupada."""
    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    await gravar(session, created_at=agora + timedelta(seconds=1))

    resultado = await process_message(_ctx(ModeradorCaido()), str(superada.id))

    assert resultado == "agrupado"
    await session.commit()
    linha = await session.get(Message, superada.id)
    assert linha is not None
    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.attempts == 0
    assert linha.bloqueada_em is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_na_rajada.py -v --tb=short
```

Esperado: `test_superada_reprovavel_recebe_marca_e_auditoria` e `test_superada_liberada_nao_ganha_marca` FALHAM — a moderação ainda não é chamada, então `bloqueada_em` fica `None` e `moderador.chamadas` fica vazio. Os outros dois já passam: são não-regressão.

- [ ] **Step 3: Implement a função de módulo**

Em `src/mobia/workers/jobs/process_message.py`, acrescente aos imports:

```python
from mobia.domain.messages.bloqueio import marcar_bloqueada
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
)
```

E acrescente a função, junto das outras privadas do módulo (antes de `process_message`):

```python
async def _moderar_superada(
    session_factory: async_sessionmaker[AsyncSession],
    linha: Message,
    corpo: str,
    *,
    moderador: ModeradorPort,
) -> bool:
    """Modera a fala que vai fechar "agrupado". Devolve se ela foi bloqueada.

    A superada nunca chega a `executar_turno`, e a moderacao de entrada mora la
    dentro -- entao sem isto ela nunca seria moderada. `bloqueada_em` ficaria
    NULL, e a coluna tem QUATRO consumidores: a janela de contexto
    (`context/janela.py`), o resumo permanente que se forma na dobra, a
    contagem do lead score (`context/repositorio.py`) e a ancora da cadencia de
    follow-up (`followup/repositorio.py`).

    **Fail-open em `ModeracaoIndisponivel`**, pela mesma assimetria que o port
    documenta e que o turno ja pratica na entrada. Deixar a excecao subir faria
    `attempts` crescer e, esgotadas as cinco tentativas, `_encaminhar_por_erro`
    abriria handoff e avisaria o lead de um erro tecnico -- por uma mensagem que
    so precisava ser agrupada. A consequencia e honesta: provedor fora do ar
    significa fala nao moderada entrando no contexto, como ja acontece hoje no
    turno normal.

    `marcar_bloqueada` e a mesma funcao que `turno.py` chama, e nao uma copia:
    ela grava a marca e o `ModerationEvent` no MESMO commit (TEC-142), e e essa
    atomicidade que impede o estado "marcada sem auditoria".
    """
    try:
        veredito = await moderador.moderar(corpo, direcao=Direcao.ENTRADA)
    except ModeracaoIndisponivel as exc:
        log.error(
            "moderacao.indisponivel",
            direcao=Direcao.ENTRADA.value,
            message_id=str(linha.id),
            reason=str(exc),
        )
        return False

    if not veredito.bloqueado:
        return False

    # `error` e nao `warning`, pelo mesmo criterio de `turno.py`: e o nivel que
    # o alerta observa. O texto julgado **nao** entra no log -- e fala do lead,
    # coberta pela regra de PII.
    log.error(
        "moderacao.entrada_bloqueada",
        message_id=str(linha.id),
        motivo=veredito.motivo,
        categoria=veredito.categoria,
    )
    await marcar_bloqueada(
        session_factory,
        linha.id,
        channel=linha.channel,
        conversation_key=linha.conversation_key,
        # `categoria or CATEGORIA_OUTRO` pela mesma razao de `turno.py`:
        # `ModeradorPort` e um `Protocol`, um adaptador futuro pode devolver
        # `Veredito(bloqueado=True)` sem categoria, e a coluna e `not null`.
        categoria=veredito.categoria or CATEGORIA_OUTRO,
    )
    return True
```

- [ ] **Step 4: Ligar a função no ramo do agrupado**

Ainda em `process_message.py`, no `else` final da guarda de superação — o ramo que hoje começa com `await session.execute(update(Message)...)` e termina em `return "agrupado"` —, insira a chamada **antes** do `UPDATE`, e acrescente a frase ao comentário de topo do bloco:

```python
                else:
                    # TEC-295: a superada e moderada aqui, e so aqui. Nos tres
                    # ramos acima o turno roda e a moderacao acontece pelo
                    # caminho normal de `turno.py`.
                    if corpo:
                        await _moderar_superada(
                            session_factory, linha, corpo, moderador=ctx["moderador"]
                        )
                    await session.execute(
                        update(Message)
                        .where(Message.id == identifier)
                        .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
                    )
                    await session.commit()
                    log.info("message.agrupado", message_id=message_id)
                    return "agrupado"
```

E no comentário de topo do bloco (o que começa em `# RN-01.6 (TEC-128, D4)`), a frase "esta fecha PROCESSED sem rodar nada" passou a ser falsa: agora ela é moderada antes de fechar. Ajuste-a — sem reescrever o resto, que continua verdadeiro.

- [ ] **Step 5: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_na_rajada.py tests/integration/test_process_message_agrupado.py tests/integration/test_optout_fura_a_janela.py tests/integration/test_entrega_parcial_nao_agrupa.py -v --tb=short
```

Esperado: todos passam. Os três últimos arquivos são as exceções da TEC-128 — se algum quebrar, a moderação entrou no ramo errado.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A
git commit -m "feat(TEC-295): a mensagem agrupada passa pela moderacao de entrada"
```

---

### Task 3: As quatro garantias, provadas pela via de cada uma

**Files:**
- Test: `tests/integration/test_moderacao_na_rajada.py` (acrescentar)

**Interfaces:**
- Consumes: o comportamento da Task 2. Nenhum código novo.
- Produces: nada.

**Por que é tarefa separada:** a Task 2 prova que a marca é gravada. Isto prova que a marca **serve** — que a fala bloqueada some dos quatro consumidores. É outra superfície de revisão: um revisor pode aceitar "a moderação roda" e rejeitar "as garantias estão provadas". Na TEC-128 foi exatamente a tarefa de teste que escondeu os defeitos mais graves.

Cada teste prova pela via do consumidor, **não** pelo desfecho do turno — um teste que só verifique `resultado == "agrupado"` não diz nada sobre contexto, score ou cadência.

- [ ] **Step 1: Write the tests**

Acrescente a `tests/integration/test_moderacao_na_rajada.py`:

```python
async def test_superada_bloqueada_sai_da_janela_de_contexto(session) -> None:
    """Garantia 2 (TEC-236), provada por `literais_apos` e nao pelo desfecho."""
    from mobia.domain.context.janela import literais_apos

    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))
    await session.commit()

    literais = await literais_apos(session, ultima.channel, ultima.conversation_key, None)
    ids = {linha.id for linha in literais}
    assert superada.id not in ids
    assert ultima.id in ids


async def test_superada_bloqueada_sai_da_contagem_do_score(session) -> None:
    """Garantia 4, lado do lead score."""
    from mobia.domain.context.repositorio import contar_mensagens_do_lead

    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto=REPROVAVEL)
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    antes = await contar_mensagens_do_lead(
        session, channel=ultima.channel, conversation_key=ultima.conversation_key
    )
    assert antes == 2

    await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))
    await session.commit()

    depois = await contar_mensagens_do_lead(
        session, channel=ultima.channel, conversation_key=ultima.conversation_key
    )
    assert depois == 1


async def test_superada_liberada_continua_no_contexto(session) -> None:
    """A D1 nao pode tirar do contexto a fala que a moderacao liberou."""
    from mobia.domain.context.janela import literais_apos

    agora = datetime.now(UTC)
    superada = await gravar(session, created_at=agora, texto="tem 2 quartos?")
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    await process_message(_ctx(ModeradorQueBloqueia()), str(superada.id))
    await session.commit()

    literais = await literais_apos(session, ultima.channel, ultima.conversation_key, None)
    assert superada.id in {linha.id for linha in literais}
```

**Sobre a assinatura de `contar_mensagens_do_lead`:** ela está em `src/mobia/domain/context/repositorio.py:1146`. **Confirme os nomes dos parâmetros abrindo o arquivo** antes de rodar — se divergirem do que está escrito acima, ajuste a chamada do teste, não a função.

- [ ] **Step 2: A garantia 4, lado do follow-up**

A âncora da cadência é a CTE `_CTES_DA_ANCORA` em `src/mobia/domain/followup/repositorio.py:161-190`, usada por `_SELECIONAR_CANDIDATOS`. **Abra o arquivo e identifique a função pública que executa essa consulta** (a que o job `sweep_followups` chama). Escreva um teste no mesmo molde dos dois acima: uma fala bloqueada não pode ser a âncora que define quando o follow-up dispara.

Se a função pública exigir montagem de estado demais para um teste de integração honesto — conversa, qualificação, cadência —, **não force**: em vez disso, escreva um teste que exercite a CTE diretamente sobre `messages` e afirme que a linha bloqueada não aparece, e registre no relatório por que o caminho completo não foi exercitado. Um teste que monta meia dúzia de entidades para se auto-satisfazer prova menos que um que exercita a consulta de verdade.

- [ ] **Step 3: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_na_rajada.py -v --tb=short
```

Esperado: todos passam. Se algum falhar, é defeito da Task 2 — conserte lá, não afrouxe o teste.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/integration/test_moderacao_na_rajada.py
git commit -m "test(TEC-295): a marca some a fala bloqueada dos quatro consumidores"
```

---

### Task 4: A carregadora bloqueada entrega a recusa e responde

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (o bloco de bloqueio de entrada, que hoje termina em `return await _entregar_texto_fixo(...)`)
- Test: `tests/integration/test_moderacao_de_entrada.py` (já existe)

**Interfaces:**
- Consumes: `ha_fala_pendente_antes(session, message)` da Task 1.
- Produces: nada.

**O que muda, e por que é pequeno.** O bloco hoje faz `marcar_bloqueada` e depois `return await _entregar_texto_fixo(...)`. Ele passa a guardar o desfecho e só retornar quando não houver o que responder. **Depois da linha do `return` não há um único uso de `corpo` em `executar_turno`** — todo o resto trabalha sobre `contexto`, que `montar_contexto` reconstrói do banco, e como `marcar_bloqueada` já rodou, `literais_apos` já exclui a própria fala bloqueada. O turno que continua enxerga a pergunta pendente e não enxerga a fala reprovada.

**`_entregar_texto_fixo` tem seis retornos** — `"expirado"`, `"sem_resposta"`, `"bloqueado_por_optout"`, `"bloqueado_por_atendimento_humano"`, `"reentrega_suprimida"` e `"respondido"`. Só o último significa que a recusa saiu. Nos outros cinco o turno retorna como hoje: se a recusa não chegou ao lead — porque ele está em opt-out, com atendimento humano, ou a janela fechou —, a resposta também não pode ir.

- [ ] **Step 1: Write the failing tests**

Leia `tests/integration/test_moderacao_de_entrada.py` inteiro antes de escrever: ele já monta um turno com moderador que bloqueia, e você deve seguir o molde dele em vez de inventar outro. Acrescente ao fim:

```python
async def test_bloqueada_com_pergunta_pendente_recusa_e_responde(session) -> None:
    """TEC-295, D4. O xingamento e recusado; a pergunta anterior e respondida.

    Antes da TEC-128 o lead recebia as duas coisas, porque cada mensagem tinha
    o proprio turno. O debounce juntou os dois casos num turno so, e este teste
    e o que impede a pergunta legitima de morrer junto com a recusa.
    """
    ...


async def test_bloqueada_sem_nada_pendente_so_recusa(session) -> None:
    """A condicao da D4. Sem ela, um turno bloqueado isolado responderia ao
    historico anterior -- o engajamento que a TEC-233 recusou de proposito."""
    ...


async def test_recusa_barrada_por_optout_concorrente_nao_responde(session) -> None:
    """A primeira ressalva da D4: se a recusa nao chegou ao lead, a resposta
    tambem nao vai."""
    ...
```

**Estes três estão como esqueleto de propósito, e preenchê-los é seu trabalho nesta tarefa.** A razão é que o molde correto depende de como `test_moderacao_de_entrada.py` monta o turno hoje, e copiar um molde que eu inventasse aqui produziria um teste que não casa com o arquivo. Leia o arquivo, siga o que ele faz, e para cada um dos três garanta que ele **falharia** antes da sua mudança — rode-os antes de implementar e mostre a saída no relatório.

Para o terceiro, veja como `_bloqueado_por_optout_concorrente` é exercitado nos testes que já existem (procure em `tests/integration/` por `bloqueado_por_optout`).

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py -v --tb=short
```

Esperado: os dois primeiros FALHAM (hoje o turno retorna logo depois da recusa, então nenhuma resposta sai). O terceiro provavelmente já passa — é não-regressão.

- [ ] **Step 3: Implement**

Em `src/mobia/domain/agente/turno.py`, troque o `return await _entregar_texto_fixo(...)` do bloco de bloqueio de entrada por:

```python
                desfecho_da_recusa = await _entregar_texto_fixo(
                    session_factory,
                    message=message,
                    outbound=outbound,
                    recorder_texto=TEXTO_DA_RECUSA_DE_ENTRADA,
                )
                # TEC-295, D4. Ate aqui o turno retornava, e com o debounce isso
                # passou a matar pergunta legitima: numa rajada, a pergunta que
                # veio antes do xingamento fecha "agrupado" sem resposta, e
                # `PROCESSED` e terminal -- nada a reenfileira.
                #
                # So `"respondido"` significa que a recusa chegou ao lead. Nos
                # outros cinco desfechos de `_entregar_texto_fixo` -- janela
                # fechada, recusa permanente da Meta, reentrega suprimida,
                # opt-out concorrente, atendimento humano concorrente -- a
                # resposta tambem nao pode ir.
                if desfecho_da_recusa != "respondido":
                    return desfecho_da_recusa
                async with session_factory() as sessao_da_pendencia:
                    tem_pendencia = await ha_fala_pendente_antes(sessao_da_pendencia, message)
                if not tem_pendencia:
                    # Fala reprovada isolada: continuar faria o agente responder
                    # ao historico anterior, que e o engajamento que a TEC-233
                    # recusou de proposito.
                    return desfecho_da_recusa
                # Cai para fora do bloco e segue o turno. O contexto que
                # `montar_contexto` monta a seguir NAO inclui esta fala: a
                # `marcar_bloqueada` acima ja carimbou a linha, e `literais_apos`
                # filtra por `bloqueada_em IS NULL`. Nao ha um unico uso de
                # `corpo` daqui para baixo -- conferido no desenho.
                log.info(
                    "moderacao.recusa_com_resposta_pendente",
                    message_id=str(message.id),
                )
```

Acrescente o import:

```python
from mobia.domain.messages.rajada import ha_fala_pendente_antes
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_moderacao_de_entrada.py tests/integration/test_moderacao_de_saida.py tests/integration/test_bloqueio_e_auditoria.py -v --tb=short
```

Esperado: todos passam. Os dois últimos arquivos cobrem a moderação de saída e a auditoria — se algum quebrar, a continuação mexeu em algo que não devia.

- [ ] **Step 5: Confirme que as duas entregas usam `kind` diferentes**

A recusa e a resposta reservam em `outbound_dispatches`, que é UNIQUE em `(message_id, kind)`. Verifique no código qual `kind` cada uma usa e confirme que diferem; se colidirem, a segunda entrega vira `reentrega_suprimida` silenciosa. **Reporte os dois valores no relatório.** Se colidirem, pare e diga — é defeito de desenho, não de implementação.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add -A
git commit -m "feat(TEC-295): a carregadora bloqueada recusa e ainda responde o pendente"
```

---

### Task 5: A prosa, a suíte e o PR

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-tec-295-moderacao-na-rajada-design.md` (Status)
- Modify: `docs/superpowers/specs/2026-09-21-tec-128-debounce-de-rajada-design.md` (a D5 descreve três detecções; agora são quatro)

- [ ] **Step 1: Prosa**

Troque o Status do desenho da TEC-295 para `implementado`.

No desenho da TEC-128, a D5 enumera as detecções que furam a janela e a lista está incompleta desde que esta card existe. Acrescente uma nota curta apontando para a TEC-295 — **sem reescrever a D5**, que descreve corretamente o que aquela card fez.

- [ ] **Step 2: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
./.venv/Scripts/python.exe scripts/comentarios_tocados.py --tudo
```

Releia cada `ALTERADO`, `VIZINHO`, `PROSA`, `FALSO` e `NOMEIA`. `FALSO` é o único que afirma; os outros são suspeita. **Esta card cresceu `process_message.py` e `turno.py`, então espere citações derivadas em specs de outras cards** — foi exatamente isso que a TEC-128 teve de consertar, e a TEC-296 existe por causa disso. Conserte as que apontarem para conteúdo sem relação, e reporte a contagem de cada marca.

- [ ] **Step 3: A suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta. Se voltar com centenas de `ERROR` de setup, não repita o mesmo comando — rode por blocos (`tests/unit`, `tests/integration`, `tests/features`). Uma falha isolada com `ConnectionResetError [WinError 64]` não autoriza conclusão nenhuma.

- [ ] **Step 4: Push, PR, e a card**

```bash
git push -u origin feat/tec-295-moderacao-na-rajada
gh pr create --base main --title "TEC-295: a moderacao de entrada deixa de ser atropelada pelo debounce" --body "<corpo>"
```

O comentário na card registra o que some se ficar só no PR:

- **A janela de corrida da D5 fica aberta por decisão**, não por esquecimento: se o job da superada falhar, a carregadora pode montar contexto antes da marca existir, e a fala não moderada entra naquele turno. O resumo permanente continua protegido.
- **Provedor de moderação fora do ar significa fala não moderada no contexto** (D2, fail-open) — mesmo comportamento do turno normal, agora num caminho a mais.
- **O custo volta ao de antes da TEC-128:** uma moderação por mensagem recebida, US$ 0,00057 cada. A TEC-128 economizou essas chamadas por acidente.
- **O texto fixo de recusa continua sem passar pela moderação de saída** — lacuna declarada pela TEC-233, não é desta card.

Mover para **Em análise**, não para Feito.

---

## Self-review do plano

**Cobertura do desenho:** D1 → Task 2; D2 → Task 2 (teste do fail-open); D3 → Task 2; D4 → Task 4, com a condição vindo da Task 1; D5 → nada a implementar, entra no comentário da card na Task 5; D6 → nada a fazer, é a lista do que não muda. As quatro garantias → Task 3, cada uma pela via do seu consumidor.

**Onde deixei esqueleto de propósito, e por quê:** os três testes da Task 4 e o teste de follow-up da Task 3. Nos dois casos o molde correto depende de como um arquivo existente monta o cenário, e um molde inventado aqui produziria teste que não casa com o arquivo. Em ambos o plano diz o que o teste tem de provar e manda mostrar a falha antes da implementação. **Isto é o único lugar do plano onde o implementador escreve código que não está escrito aqui** — se isso for inaceitável, a alternativa é uma tarefa de leitura antes, e não vale o passo a mais.

**Nomes conferidos entre tarefas:** `ha_fala_pendente_antes(session, message) -> bool` é o mesmo na Task 1 e na Task 4. `_moderar_superada` só existe na Task 2. `marcar_bloqueada`, `CATEGORIA_OUTRO`, `Direcao`, `ModeracaoIndisponivel` e `ModeradorPort` são todos do código que já existe, com os caminhos de import escritos.

**Risco maior:** a Task 4 mexe em `executar_turno`, que tem 2706 linhas e é o arquivo mais denso do repo. A mudança é pequena e o desenho verificou que não há uso de `corpo` abaixo dela, mas é onde uma regressão silenciosa custaria mais caro — por isso o Step 4 daquela tarefa roda os três arquivos de moderação juntos, e não só o que ela tocou.

# TEC-124 — Canal web via WebSocket: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Abrir o canal `web` ponta a ponta no servidor — a visitante fala por WebSocket, a mensagem entra na mesma fila do WhatsApp, e a resposta do agente volta na mesma sessão.

**Architecture:** O endpoint não tem pipeline próprio: ele monta um `ParsedMessage` e chama o `IngestionService` de sempre com `channel="web"`. A volta é o único caminho novo — o worker produz a resposta noutro processo, então `WebOutbound` publica num canal do Redis (`mobia:web:{sessão}`) que a conexão aberta assina. A escolha do adaptador deixa de ser fixa: `ctx["outbound"]` vira um roteador que lê `messages.channel` da linha.

**Tech Stack:** FastAPI/Starlette (WebSocket), SQLAlchemy async, `redis.asyncio` (pub/sub), ARQ, pytest + pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-09-23-tec-124-widget-web-via-websocket-design.md`](../specs/2026-09-23-tec-124-widget-web-via-websocket-design.md)

## Global Constraints

- **Os três gates estáticos, nesta ordem, antes de qualquer commit:** `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy` (sem argumento). Localmente com `./.venv/Scripts/python.exe -m …`. O formatador é gate separado do linter.
- **Comentário e docstring em `src/` e `tests/`: português SEM acento.** Exceção: valor citado que o lead vê, que segue o literal.
- **Texto que o lead recebe: português COM acento.** Nesta card isso alcança os frames de erro que chegam ao navegador.
- **Prosa em `docs/` e no SRS: com acento.**
- **Nenhuma migration.** A coluna `channel` já existe e não ganha CHECK (D1 da spec).
- **Emendas ao SRS entram como item aninhado `Emenda E-nn (TEC-124, 24/09/2026)` abaixo da regra que alteram**, nunca reescrevendo o texto de 22/08/2026.
- **Mensagem de commit:** `tipo(TEC-124): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Nome de arquivo de teste distinto entre `tests/unit` e `tests/integration`** — basename repetido aborta a coleta da suíte inteira e não aparece quando se roda o arquivo sozinho.
- Testes de integração e de feature exigem `docker compose` de pé. `tests/unit` não.

## Review Focus

Cinco entradas que a spec implica e que nenhum caminho feliz exercita. Cada uma tem o teste pregado na task que é dona do código.

1. **Frame que não é JSON** (texto solto, ou `bytes`) — tem de fechar com 1002, não virar 500 nem traceback do uvicorn. Task 5.
2. **`sessao` que não é UUID** (`"abc"`, `""`, um número) — não pode virar `conversation_key` arbitrária: fecha com 1002. Um UUID válido e desconhecido é caso legítimo e retoma vazio. Task 5.
3. **`texto` vazio ou só espaço em branco** — não vira linha em `messages`: senão o agente responde ao nada, com chamada paga ao modelo. Frame `erro`, conexão viva. Task 5.
4. **Texto acima do teto** — recusa com frame `erro` e a conexão **continua aberta**; derrubar o socket transformaria um Ctrl+V infeliz em perda da conversa. Task 5.
5. **Duas abas na mesma sessão** — as duas assinam o mesmo canal e as duas recebem a resposta. É o comportamento esperado, e o que não pode acontecer é uma derrubar a outra. Task 6.

---

### Task 1: O vocabulário de canal

**Files:**
- Create: `src/mobia/domain/messages/canais.py`
- Modify: `src/mobia/domain/messages/service.py:61`
- Test: `tests/unit/test_canais_do_messages.py`

**Interfaces:**
- Consumes: nada.
- Produces: `CANAL_WHATSAPP: str`, `CANAL_WEB: str`, `REMETENTE_DO_WIDGET: str`, `CANAIS_COM_REENGAJAMENTO: tuple[str, ...]`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/unit/test_canais_do_messages.py
"""O vocabulario de `messages.channel` (TEC-124)."""

from mobia.domain.messages.canais import (
    CANAIS_COM_REENGAJAMENTO,
    CANAL_WEB,
    CANAL_WHATSAPP,
)


def test_os_dois_canais_sao_minusculos() -> None:
    # A coluna esta povoada com `whatsapp` desde a TEC-122. Um valor
    # maiusculo ao lado faria consulta por canal depender de caixa.
    assert CANAL_WHATSAPP == "whatsapp"
    assert CANAL_WEB == "web"


def test_o_reengajamento_e_allowlist_e_nao_alcanca_o_web() -> None:
    # Allowlist e nao `!= CANAL_WEB`: canal novo nasce de fora.
    assert CANAIS_COM_REENGAJAMENTO == (CANAL_WHATSAPP,)
    assert CANAL_WEB not in CANAIS_COM_REENGAJAMENTO


def test_o_default_da_ingestao_e_a_constante_e_nao_um_literal_solto() -> None:
    import inspect

    from mobia.domain.messages.service import IngestionService

    assinatura = inspect.signature(IngestionService.ingest)
    assert assinatura.parameters["channel"].default == CANAL_WHATSAPP
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_canais_do_messages.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.messages.canais'`

- [ ] **Step 3: Escrever o módulo**

```python
# src/mobia/domain/messages/canais.py
"""O vocabulario de `messages.channel`. TEC-124.

Ate esta card o unico valor da coluna era a string `"whatsapp"`, escrita a mao
no default de `IngestionService.ingest`. O canal web precisa de um segundo
valor, e um segundo literal solto seria o primeiro passo para tres grafias do
mesmo canal.

**Minusculo, e nao `WEB` como a card escreve.** A coluna ja esta povoada com
`whatsapp` desde a TEC-122; um valor maiusculo ao lado faria toda consulta por
canal depender de caixa, e o primeiro `WHERE channel = 'web'` escrito de
memoria sairia vazio sem erro nenhum. A divergencia esta no comentario da
card.

**Sem CHECK no banco, ao contrario de `role` e `direction` (TEC-223).** La o
vocabulario esta fechado e um literal errado burla filtro em SQL cru. Aqui ele
ainda cresce -- TEC-131 e TEC-132 podem trazer mais -- e o custo de errar e
outro: canal sem adaptador nao passa despercebido, o roteador levanta.
"""

CANAL_WHATSAPP = "whatsapp"
CANAL_WEB = "web"

# O "de" do canal web. Nao ha numero de origem, e a coluna precisa de valor:
# `indicador_de_digitacao` desiste cedo quando `recipient_external_id` e nulo,
# e `_avisar_lead_da_janela_humana` le esse campo como o remetente do canal.
REMETENTE_DO_WIDGET = "widget"

# Quem recebe reengajamento (RF-13). **Allowlist, e nao `!= CANAL_WEB`**:
# canal novo nasce de fora e entra quando alguem decidir que ele tem para onde
# empurrar mensagem. O web nao tem: um follow-up de 24h numa sessao de
# navegador vira linha em `followups` marcada como enviada e texto que a
# visitante so veria se voltasse por conta propria -- caso em que ela nao
# precisava do follow-up.
CANAIS_COM_REENGAJAMENTO: tuple[str, ...] = (CANAL_WHATSAPP,)
```

E em `service.py`, trocar o literal do default:

```python
from mobia.domain.messages.canais import CANAL_WHATSAPP

    async def ingest(
        self, parsed: list[ParsedMessage], channel: str = CANAL_WHATSAPP
    ) -> list[uuid.UUID]:
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_canais_do_messages.py -v`
Expected: 3 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/canais.py src/mobia/domain/messages/service.py tests/unit/test_canais_do_messages.py
git commit -m "feat(TEC-124): o canal de mensagem vira vocabulario, e nao mais literal no default da ingestao"
```

---

### Task 2: O roteador de saída por canal

**Files:**
- Create: `src/mobia/domain/outbound/roteador.py`
- Test: `tests/integration/test_roteador_de_canal.py`

**Interfaces:**
- Consumes: `CANAL_WHATSAPP`, `CANAL_WEB` (Task 1); `OutboundPort` de `domain/outbound/port.py`.
- Produces: `RoteadorPorCanal(session_factory, portas: dict[str, OutboundPort])` com `async send(message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool`; e `CanalSemPorta(Exception)`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_roteador_de_canal.py
"""O roteador que escolhe o adaptador pela linha. TEC-124, D5."""

import uuid
from typing import Any

import pytest

from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.outbound.roteador import CanalSemPorta, RoteadorPorCanal
from tests.conftest import _entrada_do_lead  # o helper ja existente


class PortaEspia:
    def __init__(self) -> None:
        self.chamadas: list[tuple[uuid.UUID, str, dict[str, Any]]] = []

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        self.chamadas.append((message_id, kind, payload))
        return True


async def test_roteia_para_o_adaptador_do_canal_da_linha(session, session_factory) -> None:
    linha = await _entrada_do_lead(session, texto="oi")
    linha.channel = CANAL_WEB
    await session.commit()

    whatsapp, web = PortaEspia(), PortaEspia()
    roteador = RoteadorPorCanal(
        session_factory, {CANAL_WHATSAPP: whatsapp, CANAL_WEB: web}
    )

    assert await roteador.send(linha.id, "resposta", {"texto": "ola"}) is True
    assert [chamada[0] for chamada in web.chamadas] == [linha.id]
    assert whatsapp.chamadas == []


async def test_linha_inexistente_levanta_alto(session_factory) -> None:
    # Defeito de chamador, nao indisponibilidade: engolir deixaria o lead sem
    # resposta com um log de `info`.
    roteador = RoteadorPorCanal(session_factory, {CANAL_WHATSAPP: PortaEspia()})
    with pytest.raises(CanalSemPorta):
        await roteador.send(uuid.uuid4(), "resposta", {"texto": "ola"})


async def test_canal_sem_porta_levanta_alto(session, session_factory) -> None:
    linha = await _entrada_do_lead(session, texto="oi")
    linha.channel = CANAL_WEB
    await session.commit()

    roteador = RoteadorPorCanal(session_factory, {CANAL_WHATSAPP: PortaEspia()})
    with pytest.raises(CanalSemPorta):
        await roteador.send(linha.id, "resposta", {"texto": "ola"})
```

> Antes de escrever, confira a assinatura real de `_entrada_do_lead` em `tests/conftest.py` (ela recebe `session` e `texto=`). Se o helper não for importável de fora, replique as três linhas que criam a `Message` em vez de importá-lo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_roteador_de_canal.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.outbound.roteador'`

- [ ] **Step 3: Escrever o roteador**

```python
# src/mobia/domain/outbound/roteador.py
"""A escolha do adaptador de saida pelo canal da linha. TEC-124, D5.

Ate esta card `ctx["outbound"]` era uma instancia unica de `WhatsAppOutbound`,
e o canal nao entrava na decisao porque so havia um. Com o web, entra.

**A escolha se faz pela LINHA, e nao pelo chamador.** `OutboundPort.send`
recebe `message_id`, e e dele que sai o canal: um SELECT por chave primaria a
cada envio, em troca de nenhum dos sitios de chamada mudar -- inclusive os
seis dentro de `turno.py`, que tem mais de quatro mil linhas, e o
`_avisar_lead_da_janela_humana`, que fala com o lead de dentro da notificacao
de handoff. Um caminho de envio novo, escrito por quem nao leu esta card,
nasce roteado em vez de mandar tudo por WhatsApp.

**Nao herda de `GuardedOutbound`, de proposito.** As guardas de opt-out e de
atendimento humano e a reserva em `outbound_dispatches` moram no adaptador de
destino; repeti-las aqui reservaria duas vezes o mesmo envio e a segunda
reserva colidiria com a primeira, fazendo todo envio parecer duplicata
suprimida.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.outbound.port import OutboundPort

log = structlog.get_logger(__name__)


class CanalSemPorta(Exception):
    """A linha nao existe, ou o canal dela nao tem adaptador montado.

    Levanta em vez de devolver False porque nao e indisponibilidade: e defeito
    de chamador ou de montagem do worker. Devolver False faria o turno fechar
    como "reentrega suprimida" -- PROCESSED, terminal -- e o lead nunca
    receberia nada, com um `info` no log mandando quem investiga para o lado
    errado. Propagada crua, cai no contrato que `OutboundPort` ja escreve:
    a mensagem vira FAILED e alguem ve.
    """


class RoteadorPorCanal:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        portas: dict[str, OutboundPort],
    ) -> None:
        self._session_factory = session_factory
        self._portas = portas

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        async with self._session_factory() as session:
            canal = (
                await session.execute(select(Message.channel).where(Message.id == message_id))
            ).scalar_one_or_none()

        if canal is None:
            raise CanalSemPorta(f"nao ha linha em messages para {message_id}")

        porta = self._portas.get(canal)
        if porta is None:
            raise CanalSemPorta(f"canal {canal} sem adaptador de saida montado")

        return await porta.send(message_id, kind, payload)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_roteador_de_canal.py -v --tb=short`
Expected: 3 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/outbound/roteador.py tests/integration/test_roteador_de_canal.py
git commit -m "feat(TEC-124): a saida escolhe o adaptador pelo canal da linha, e nao por uma instancia unica"
```

---

### Task 3: `WebOutbound` — publica e nunca levanta

**Files:**
- Create: `src/mobia/domain/outbound/web.py`
- Test: `tests/integration/test_web_outbound.py`

**Interfaces:**
- Consumes: `GuardedOutbound` (`domain/outbound/port.py`), `redis.asyncio.Redis`.
- Produces: `WebOutbound(session_factory, redis)`, `canal_da_sessao(sessao: str) -> str`, `PREFIXO_DA_SESSAO: str`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_web_outbound.py
"""A entrega no canal web. TEC-124, D4."""

import json

from mobia.domain.messages.canais import CANAL_WEB
from mobia.domain.outbound.web import WebOutbound, canal_da_sessao
from tests.conftest import _entrada_do_lead


async def _linha_web(session, sessao: str):
    linha = await _entrada_do_lead(session, texto="oi")
    linha.channel = CANAL_WEB
    linha.conversation_key = sessao
    await session.commit()
    return linha


async def test_publica_o_texto_na_sessao(session, session_factory, redis_pool) -> None:
    sessao = "8c0f0a3e-0000-4000-8000-000000000001"
    linha = await _linha_web(session, sessao)

    ouvinte = redis_pool.pubsub()
    await ouvinte.subscribe(canal_da_sessao(sessao))

    porta = WebOutbound(session_factory, redis_pool)
    assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is True

    recebida = None
    async for evento in ouvinte.listen():
        if evento["type"] == "message":
            recebida = json.loads(evento["data"])
            break
    await ouvinte.aclose()

    assert recebida == {"tipo": "mensagem", "texto": "ola", "kind": "resposta"}


async def test_sem_ouvinte_o_envio_e_bem_sucedido(session, session_factory, redis_pool) -> None:
    # A aba fechou. A fala ja esta em `messages` e a reconexao a mostra --
    # levantar aqui faria o sweeper rodar o turno inteiro de novo, com
    # chamada nova e paga ao modelo, para reentregar o que ja esta no banco.
    sessao = "8c0f0a3e-0000-4000-8000-000000000002"
    linha = await _linha_web(session, sessao)

    porta = WebOutbound(session_factory, redis_pool)
    assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is True


async def test_redis_indisponivel_nao_derruba_o_turno(session, session_factory) -> None:
    class RedisQueCai:
        async def publish(self, canal: str, mensagem: str) -> int:
            raise ConnectionError("redis fora")

    sessao = "8c0f0a3e-0000-4000-8000-000000000003"
    linha = await _linha_web(session, sessao)

    porta = WebOutbound(session_factory, RedisQueCai())
    assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is True


async def test_a_ficha_com_imagem_viaja_com_link_e_legenda(
    session, session_factory, redis_pool
) -> None:
    sessao = "8c0f0a3e-0000-4000-8000-000000000004"
    linha = await _linha_web(session, sessao)

    ouvinte = redis_pool.pubsub()
    await ouvinte.subscribe(canal_da_sessao(sessao))

    porta = WebOutbound(session_factory, redis_pool)
    await porta.send(
        linha.id,
        "ficha_1",
        {"para": sessao, "tipo": "imagem", "link": "http://f/1.jpg", "legenda": "Apê"},
    )

    recebida = None
    async for evento in ouvinte.listen():
        if evento["type"] == "message":
            recebida = json.loads(evento["data"])
            break
    await ouvinte.aclose()

    assert recebida == {
        "tipo": "imagem",
        "link": "http://f/1.jpg",
        "legenda": "Apê",
        "kind": "ficha_1",
    }
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_web_outbound.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.outbound.web'`

- [ ] **Step 3: Escrever o adaptador**

```python
# src/mobia/domain/outbound/web.py
"""A entrega no canal web: publicar na sessao aberta. TEC-124, D4.

**Este adaptador nao levanta excecao nenhuma, e isso diverge de proposito do
contrato que `OutboundPort` escreve.** La, falha de rede e `EnvioRetentavel`
porque no WhatsApp a rede e o UNICO caminho ate o lead: sem ela, ele nunca
recebe. Aqui nao e. A fala do agente ja foi gravada em `messages` por
`MessageRecorder` antes de qualquer publicacao, e a reconexao a mostra (ver
`domain/messages/historico.py`) -- a publicacao e o atalho que a faz chegar
AGORA, nao o caminho que a faz chegar. Retentar custaria uma chamada nova e
paga ao modelo para reentregar o que ja esta no banco, por causa de uma aba
que a visitante fechou.

Por isso publicacao sem ouvinte sai em `info` e e o caso NORMAL, nao falha.

**`EnvioForaDaJanela` tambem nunca sai daqui**: o canal web nao tem janela, e
o docstring de `OutboundPort` ja registrava isso antes desta card existir.

**Kind que nao seja texto nem imagem nao e publicado.** Nenhum caminho manda
template para o web -- as varreduras que os enviam filtram por
`CANAIS_COM_REENGAJAMENTO` --, entao chegar um aqui e defeito de roteamento
nosso. Fechar o turno em falha puniria o lead por isso; o `warning` e o
registro em `messages` sao o que sobra, e o historico da reconexao ainda
mostra o texto.
"""

import json
import uuid
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.outbound.port import GuardedOutbound

log = structlog.get_logger(__name__)

# O namespace das publicacoes. Fora do `arq:` da fila e do `ratelimit:` do
# limitador, que sao os outros dois deste Redis.
PREFIXO_DA_SESSAO = "mobia:web"


def canal_da_sessao(sessao: str) -> str:
    return f"{PREFIXO_DA_SESSAO}:{sessao}"


class WebOutbound(GuardedOutbound):
    """Publica a fala do agente no canal da sessao.

    Herda de `GuardedOutbound` porque e a rota segura: e a heranca que traz as
    guardas de opt-out e de atendimento humano, que o Protocol nao forca e que
    um adaptador escrito direto contra ele nao teria.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Any,
    ) -> None:
        super().__init__(session_factory)
        self._redis = redis

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        corpo = _frame_de(kind, payload)
        if corpo is None:
            log.warning(
                "web.kind_sem_forma",
                message_id=str(message_id),
                kind=kind,
                tipo=payload.get("tipo"),
            )
            return

        if self._redis is None:
            log.warning("web.sem_redis", message_id=str(message_id), kind=kind)
            return

        try:
            ouvintes = await self._redis.publish(
                canal_da_sessao(str(payload["para"])), json.dumps(corpo)
            )
        except RedisError as exc:
            # So o nome da classe, como no resto do projeto.
            log.warning(
                "web.publicacao_falhou",
                message_id=str(message_id),
                kind=kind,
                reason=type(exc).__name__,
            )
            return

        # `ouvintes == 0` e o caso normal de uma aba fechada, nao falha -- ver
        # o docstring do modulo.
        log.info(
            "web.publicado", message_id=str(message_id), kind=kind, ouvintes=int(ouvintes)
        )


def _frame_de(kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Traduz o payload da porta para o frame que o navegador le.

    `tipo` ausente e texto, pelo mesmo default que `WhatsAppOutbound` aplica:
    os chamadores anteriores a TEC-162 nao mandam a chave.
    """
    tipo = payload.get("tipo")
    if tipo is None or tipo == "texto":
        return {"tipo": "mensagem", "texto": payload["texto"], "kind": kind}
    if tipo == "imagem":
        return {
            "tipo": "imagem",
            "link": payload["link"],
            "legenda": payload["legenda"],
            "kind": kind,
        }
    return None
```

> `ConnectionError` do teste é subclasse de `RedisError`? **Não.** `redis.exceptions.ConnectionError` é, mas a builtin não. No teste use `from redis.exceptions import ConnectionError as ErroDeConexao` e levante essa, para exercitar o `except` real.

- [ ] **Step 4: Corrigir o teste conforme a nota acima, rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_web_outbound.py -v --tb=short`
Expected: 4 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/outbound/web.py tests/integration/test_web_outbound.py
git commit -m "feat(TEC-124): a fala do agente no canal web sai por publicacao, e a queda do socket nao e falha de entrega"
```

---

### Task 4: O histórico da sessão

**Files:**
- Create: `src/mobia/domain/messages/historico.py`
- Test: `tests/integration/test_historico_da_sessao.py`

**Interfaces:**
- Consumes: `Message`, `decrypt`/`aad_de` de `infra/crypto.py`, `CANAL_WEB`.
- Produces: `FalaDoHistorico` (dataclass congelada: `papel: str`, `texto: str`, `em: datetime`) e `async historico_da_sessao(session_factory, *, canal: str, sessao: str, limite: int) -> list[FalaDoHistorico]`.

> Divergência declarada em relação à spec: ela contava quatro arquivos novos, e este é o quinto. A consulta podia morar dentro da rota, mas aí só seria testável com um socket aberto — e é ela que carrega a promessa da card de não perder o que já foi dito.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_historico_da_sessao.py
"""O que a visitante ve ao reabrir o widget. TEC-124, D6."""

from datetime import UTC, datetime

from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.historico import historico_da_sessao
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, encrypt

SESSAO = "8c0f0a3e-0000-4000-8000-0000000000aa"


async def _fala(session, *, papel, direcao, texto, bloqueada=False):
    identificador = __import__("uuid").uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL_WEB,
            provider_message_id=None,
            sender_external_id=SESSAO,
            recipient_external_id=REMETENTE_DO_WIDGET,
            conversation_key=SESSAO,
            role=papel,
            direction=direcao,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(texto, aad_de(identificador, "text_body")),
            bloqueada_em=datetime.now(UTC) if bloqueada else None,
        )
    )
    await session.commit()


async def test_devolve_as_falas_em_ordem_cronologica(session, session_factory) -> None:
    await _fala(session, papel=MessageRole.LEAD, direcao=MessageDirection.INBOUND, texto="oi")
    await _fala(
        session, papel=MessageRole.AGENTE, direcao=MessageDirection.OUTBOUND, texto="olá!"
    )

    falas = await historico_da_sessao(
        session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=50
    )

    assert [(f.papel, f.texto) for f in falas] == [("lead", "oi"), ("agente", "olá!")]


async def test_a_fala_bloqueada_pela_moderacao_nao_volta_a_tela(
    session, session_factory
) -> None:
    # Mesmo criterio da TEC-236 e da Emenda E-01 da RN-02.2: ela nao entra em
    # contexto nem em resumo, e esta seria a unica tela onde reapareceria.
    await _fala(
        session,
        papel=MessageRole.LEAD,
        direcao=MessageDirection.INBOUND,
        texto="conteudo bloqueado",
        bloqueada=True,
    )

    falas = await historico_da_sessao(
        session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=50
    )

    assert falas == []


async def test_o_limite_corta_as_mais_antigas_e_preserva_a_ordem(
    session, session_factory
) -> None:
    for indice in range(5):
        await _fala(
            session,
            papel=MessageRole.LEAD,
            direcao=MessageDirection.INBOUND,
            texto=f"fala {indice}",
        )

    falas = await historico_da_sessao(session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=2)

    assert [f.texto for f in falas] == ["fala 3", "fala 4"]


async def test_sessao_desconhecida_devolve_vazio(session_factory) -> None:
    # UUID valido que nunca falou: `localStorage` de uma sessao ja encerrada,
    # ou de outro ambiente. Nao e erro.
    falas = await historico_da_sessao(
        session_factory,
        canal=CANAL_WEB,
        sessao="8c0f0a3e-0000-4000-8000-0000000000ff",
        limite=50,
    )
    assert falas == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_historico_da_sessao.py -v --tb=short`
Expected: FAIL com `ModuleNotFoundError: No module named 'mobia.domain.messages.historico'`

- [ ] **Step 3: Escrever o módulo**

```python
# src/mobia/domain/messages/historico.py
"""O que a visitante do widget ve ao reabrir a pagina. TEC-124, D6.

**Le de `messages`, e nao de uma copia em Redis.** A durabilidade desta
conversa ja e do Postgres nos dois sentidos: a fala da visitante porque o
`IngestionService` commita antes de enfileirar, e a do agente porque o
`MessageRecorder` grava antes de o `WebOutbound` publicar. Uma segunda
representacao do mesmo fato seria mais uma coisa que pode divergir.

**A fala bloqueada pela moderacao fica de fora**, pelo mesmo criterio da
TEC-236 e da Emenda E-01 da RN-02.2: ela nao entra em contexto nem em resumo,
e esta tela seria o unico lugar do sistema em que ela reapareceria.

So `LEAD` e `AGENTE`: `CORRETOR` e `SISTEMA` existem para o handoff e para o
registro interno, e nao sao a conversa que a visitante teve.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, decrypt

_PAPEL_NA_TELA = {MessageRole.LEAD.value: "lead", MessageRole.AGENTE.value: "agente"}


@dataclass(frozen=True)
class FalaDoHistorico:
    papel: str
    texto: str
    em: datetime


async def historico_da_sessao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    canal: str,
    sessao: str,
    limite: int,
) -> list[FalaDoHistorico]:
    """As ultimas `limite` falas, em ordem cronologica.

    A consulta desce por `created_at DESC` para o `LIMIT` cortar as MAIS
    ANTIGAS -- cortar as recentes devolveria o comeco de uma conversa longa e
    esconderia o que acabou de ser dito --, e a lista e revertida antes de
    sair, porque quem le a tela le de cima para baixo.

    Desempata por `id DESC` pela mesma razao que `falas_do_lead` em
    `followup/repositorio.py`: `_persist` grava o lote de um envelope num
    unico INSERT e `created_at` cai no `now()` do statement, constante para
    todas as linhas dele.
    """
    async with session_factory() as session:
        linhas = (
            (
                await session.execute(
                    select(Message)
                    .where(
                        Message.channel == canal,
                        Message.conversation_key == sessao,
                        Message.role.in_(tuple(_PAPEL_NA_TELA)),
                        Message.bloqueada_em.is_(None),
                    )
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(limite)
                )
            )
            .scalars()
            .all()
        )

    falas = []
    for linha in reversed(linhas):
        texto = decrypt(linha.text_body, aad_de(linha.id, "text_body"))
        if texto is None:
            # Linha sem corpo em claro -- midia, ou uma fala gravada sem
            # texto. Nao ha o que mostrar, e inventar um placeholder seria
            # afirmar na tela algo que a tabela nao diz.
            continue
        falas.append(
            FalaDoHistorico(papel=_PAPEL_NA_TELA[linha.role], texto=texto, em=linha.created_at)
        )
    return falas
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_historico_da_sessao.py -v --tb=short`
Expected: 4 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/messages/historico.py tests/integration/test_historico_da_sessao.py
git commit -m "feat(TEC-124): a sessao web relida devolve a conversa, sem a fala que a moderacao bloqueou"
```

---

### Task 5: O endpoint — handshake, sessão e entrada

**Files:**
- Create: `src/mobia/api/routes/widget.py`
- Modify: `src/mobia/app/main.py` (registrar o router), `src/mobia/app/config.py` (dois campos novos), `tests/conftest.py` (o cliente WebSocket e a fixture do app)
- Test: `tests/integration/test_widget_handshake.py`

**Interfaces:**
- Consumes: `IngestionService`, `ParsedMessage`, `CANAL_WEB`, `REMETENTE_DO_WIDGET`, `historico_da_sessao` (Task 4).
- Produces: `router` (FastAPI `APIRouter` com `WS /widget/chat`); constantes `TAMANHO_MAXIMO_DO_TEXTO`, `CODIGO_PROTOCOLO = 1002`, `CODIGO_EXCESSO = 1013`; em `tests/conftest.py`, a fixture `ws_cliente` (fábrica `(app) -> ClienteWebSocket`) e `app_do_widget`.

- [ ] **Step 1: Escrever o cliente WebSocket de teste em `tests/conftest.py`**

Ele fala o protocolo ASGI direto, **no mesmo event loop do teste**. É por isso que não se usa o `TestClient` do Starlette aqui: ele roda o app numa thread com loop próprio, e as conexões asyncpg das fixtures não sobrevivem à troca de loop — é a mesma razão que o docstring de `banco_limpo` já registra.

```python
# tests/conftest.py -- acrescentar ao fim
class ClienteWebSocket:
    """Fala ASGI direto com o app, sem sair do event loop do teste."""

    def __init__(self, app, *, caminho: str = "/widget/chat", ip: str = "203.0.113.7") -> None:
        self._app = app
        self._caminho = caminho
        self._ip = ip
        self._para_o_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._do_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tarefa: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "ClienteWebSocket":
        escopo = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self._caminho,
            "raw_path": self._caminho.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": (self._ip, 55000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        await self._para_o_app.put({"type": "websocket.connect"})
        self._tarefa = asyncio.create_task(
            self._app(escopo, self._para_o_app.get, self._do_app.put)
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._para_o_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._tarefa is not None:
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(self._tarefa, timeout=5)

    async def evento(self) -> dict[str, Any]:
        """O proximo evento ASGI que o app emitiu -- accept, send ou close.

        Com teto: sem ele, um endpoint que nunca responde penduraria a suite,
        e travamento sem `pytest-timeout` instalado nao morre, espera.
        """
        return await asyncio.wait_for(self._do_app.get(), timeout=5)

    async def aceitar(self) -> None:
        evento = await self.evento()
        assert evento["type"] == "websocket.accept", evento

    async def enviar(self, frame: dict[str, Any]) -> None:
        await self._para_o_app.put({"type": "websocket.receive", "text": json.dumps(frame)})

    async def enviar_cru(self, texto: str) -> None:
        await self._para_o_app.put({"type": "websocket.receive", "text": texto})

    async def receber(self) -> dict[str, Any]:
        evento = await self.evento()
        assert evento["type"] == "websocket.send", evento
        return json.loads(evento["text"])

    async def fechamento(self) -> int:
        evento = await self.evento()
        assert evento["type"] == "websocket.close", evento
        return int(evento.get("code", 1000))


@pytest.fixture
def app_do_widget(banco_limpo: None, redis_pool):
    app = create_app()
    app.state.redis_pool = redis_pool
    return app


@pytest.fixture
def ws_cliente(app_do_widget):
    def _criar(**kwargs) -> ClienteWebSocket:
        return ClienteWebSocket(app_do_widget, **kwargs)

    return _criar
```

Imports a garantir no topo do `conftest.py`: `asyncio`, `json`, `from contextlib import suppress`, `from typing import Any`. Vários já estão lá — confira antes de acrescentar duplicata.

- [ ] **Step 2: Escrever o teste que falha**

```python
# tests/integration/test_widget_handshake.py
"""O aperto de mao do widget e a entrada de mensagem. TEC-124, D2 e D3."""

import uuid

from sqlalchemy import select

from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.models import Message


async def test_sem_sessao_o_servidor_emite_um_uuid(ws_cliente) -> None:
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        frame = await ws.receber()

    assert frame["tipo"] == "sessao"
    uuid.UUID(frame["sessao"])  # levanta se nao for UUID


async def test_a_mensagem_vira_linha_no_canal_web(ws_cliente, session) -> None:
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        sessao = (await ws.receber())["sessao"]
        await ws.enviar(
            {"tipo": "mensagem", "id": "m-1", "texto": "esse apê da zona sul ainda está?"}
        )
        await ws.receber()  # o `recebido` do servidor confirma a gravacao

    linha = (
        await session.execute(select(Message).where(Message.conversation_key == sessao))
    ).scalar_one()
    assert linha.channel == CANAL_WEB
    assert linha.provider_message_id == "m-1"
    assert linha.recipient_external_id == REMETENTE_DO_WIDGET
    assert linha.sender_external_id == sessao


async def test_primeiro_frame_que_nao_e_ola_fecha_com_1002(ws_cliente) -> None:
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "mensagem", "texto": "oi"})
        assert await ws.fechamento() == 1002


async def test_frame_que_nao_e_json_fecha_com_1002(ws_cliente) -> None:
    # Review Focus 1.
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar_cru("nao sou json")
        assert await ws.fechamento() == 1002


async def test_sessao_que_nao_e_uuid_fecha_com_1002(ws_cliente) -> None:
    # Review Focus 2: aceitar viraria `conversation_key` arbitraria.
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": "abc"})
        assert await ws.fechamento() == 1002


async def test_texto_vazio_nao_vira_linha_e_a_conexao_segue(ws_cliente, session) -> None:
    # Review Focus 3: viraria turno, com chamada paga ao modelo, para nada.
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        await ws.receber()
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "   "})
        erro = await ws.receber()
        assert erro == {"tipo": "erro", "motivo": "texto_vazio"}

        await ws.enviar({"tipo": "mensagem", "id": "m-2", "texto": "agora vai"})
        assert (await ws.receber())["tipo"] == "recebido"

    linhas = (await session.execute(select(Message))).scalars().all()
    assert [linha.provider_message_id for linha in linhas] == ["m-2"]


async def test_texto_acima_do_teto_e_recusado_sem_derrubar(ws_cliente, monkeypatch) -> None:
    # Review Focus 4: derrubar transformaria um Ctrl+V infeliz em perda da
    # conversa inteira.
    from mobia.app.config import get_settings

    monkeypatch.setenv("TAMANHO_MAXIMO_DO_TEXTO_DO_WIDGET", "10")
    get_settings.cache_clear()

    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        await ws.receber()
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "x" * 11})
        assert await ws.receber() == {"tipo": "erro", "motivo": "texto_longo_demais"}

        await ws.enviar({"tipo": "mensagem", "id": "m-2", "texto": "curto"})
        assert (await ws.receber())["tipo"] == "recebido"


async def test_retomar_devolve_o_historico(ws_cliente) -> None:
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        sessao = (await ws.receber())["sessao"]
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "primeira"})
        await ws.receber()

    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": sessao})
        assert (await ws.receber())["sessao"] == sessao
        historico = await ws.receber()

    assert historico["tipo"] == "historico"
    assert [fala["texto"] for fala in historico["mensagens"]] == ["primeira"]


async def test_id_repetido_nao_grava_duas_linhas(ws_cliente, session) -> None:
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        await ws.receber()
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "primeira"})
        await ws.receber()
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "primeira"})
        await ws.receber()

    linhas = (await session.execute(select(Message))).scalars().all()
    assert len(linhas) == 1
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_handshake.py -v --tb=short`
Expected: FAIL — o app não tem `/widget/chat`, então o primeiro `aceitar()` recebe `websocket.close` em vez de `websocket.accept`.

- [ ] **Step 4: Acrescentar os dois campos de configuração**

Em `src/mobia/app/config.py`, junto dos demais campos de `Settings`:

```python
    # Quantas falas a reconexao do widget devolve (TEC-124, D6). Cinquenta
    # cobre a conversa inteira no caso comum e evita decifrar um historico
    # longo a cada reconexao -- e esta tela nao e o lugar de auditar
    # transcricao, que e o painel.
    historico_do_widget_mensagens: int = 50

    # Teto de caracteres por frame de texto do widget (TEC-124, D3). Acima
    # disso o frame e recusado e a conexao CONTINUA aberta.
    tamanho_maximo_do_texto_do_widget: int = 4096
```

- [ ] **Step 5: Escrever o endpoint**

```python
# src/mobia/api/routes/widget.py
"""O canal web: WebSocket do widget do site. TEC-124, RF-01.

**Nao ha pipeline proprio aqui.** O endpoint monta um `ParsedMessage` e chama
o mesmo `IngestionService` do webhook com `channel=CANAL_WEB`. Com isso o
canal herda, sem escrever linha nenhuma: persistir antes de enfileirar, o rate
limit por numero, o debounce de rajada, o atalho que fura a janela para
opt-out e pedido de humano, e a contagem de duplicata descartada.

**Nenhuma chamada a modelo acontece dentro do ciclo da conexao**, pelo mesmo
motivo que a RN-01.2 escreve para o webhook.

O `id` do frame vira `provider_message_id`: e ele que faz o reenvio depois de
uma queda cair na UNIQUE `(channel, provider_message_id)` que ja existe --
dedup sem codigo novo, pelo mesmo mecanismo que absorve a reentrega da Meta.
"""

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from mobia.api.deps import get_ingestion_service
from mobia.app.config import get_settings
from mobia.app.logging import correlation_id
from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.historico import historico_da_sessao
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker

log = structlog.get_logger(__name__)
router = APIRouter(tags=["widget"])

TIPO_OLA = "ola"
TIPO_MENSAGEM = "mensagem"

# 1002 e o codigo de violacao de protocolo do RFC 6455. Frame fora de ordem,
# JSON invalido e sessao que nao e UUID caem todos aqui: sao cliente quebrado,
# nao erro nosso, e nao ha frame de erro que ajude quem os manda.
CODIGO_PROTOCOLO = 1002


@router.websocket("/widget/chat")
async def chat(
    websocket: WebSocket,
    service: IngestionService = Depends(get_ingestion_service),
) -> None:
    correlation_id.set(str(uuid.uuid4()))
    await websocket.accept()

    sessao = await _apresentar(websocket)
    if sessao is None:
        return

    log.info("widget.conectado", sessao=sessao)
    try:
        await _ler_do_lead(websocket, service, sessao)
    except WebSocketDisconnect:
        log.info("widget.desconectado", sessao=sessao)


async def _apresentar(websocket: WebSocket) -> str | None:
    """O primeiro frame decide a identidade, e nada mais passa antes dele."""
    try:
        primeiro = await _receber_json(websocket)
    except WebSocketDisconnect:
        return None
    except json.JSONDecodeError:
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None

    if not isinstance(primeiro, dict) or primeiro.get("tipo") != TIPO_OLA:
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None

    bruto = primeiro.get("sessao")
    if bruto is None:
        sessao = str(uuid.uuid4())
        retomada = False
    else:
        try:
            # `str(UUID(...))` normaliza: maiuscula e chaves entram, e a
            # `conversation_key` gravada e sempre a mesma forma.
            sessao = str(uuid.UUID(str(bruto)))
        except ValueError:
            # Aceitar qualquer string aqui deixaria o cliente escolher a
            # `conversation_key` -- inclusive a de outra conversa.
            await websocket.close(code=CODIGO_PROTOCOLO)
            return None
        retomada = True

    await websocket.send_json({"tipo": "sessao", "sessao": sessao})

    if retomada:
        falas = await historico_da_sessao(
            get_sessionmaker(),
            canal=CANAL_WEB,
            sessao=sessao,
            limite=get_settings().historico_do_widget_mensagens,
        )
        await websocket.send_json(
            {
                "tipo": "historico",
                "mensagens": [
                    {"papel": fala.papel, "texto": fala.texto, "em": fala.em.isoformat()}
                    for fala in falas
                ],
            }
        )

    return sessao


async def _ler_do_lead(websocket: WebSocket, service: IngestionService, sessao: str) -> None:
    settings = get_settings()
    teto = settings.tamanho_maximo_do_texto_do_widget

    while True:
        try:
            frame = await _receber_json(websocket)
        except json.JSONDecodeError:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        if not isinstance(frame, dict) or frame.get("tipo") != TIPO_MENSAGEM:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        texto = str(frame.get("texto") or "")
        if not texto.strip():
            # Nao vira linha: um turno sobre texto vazio custaria chamada paga
            # ao modelo para responder ao nada.
            await websocket.send_json({"tipo": "erro", "motivo": "texto_vazio"})
            continue
        if len(texto) > teto:
            # Recusa SEM fechar: derrubar o socket transformaria um Ctrl+V
            # infeliz em perda da conversa inteira.
            await websocket.send_json({"tipo": "erro", "motivo": "texto_longo_demais"})
            continue

        # Sem `id` o cliente funciona, so nao ganha a dedup da UNIQUE.
        identificador = str(frame.get("id") or uuid.uuid4())
        await service.ingest(
            [
                ParsedMessage(
                    provider_message_id=identificador,
                    sender_external_id=sessao,
                    recipient_external_id=REMETENTE_DO_WIDGET,
                    content_type=MessageContentType.TEXTO,
                    text_body=texto,
                    raw_payload=frame,
                )
            ],
            channel=CANAL_WEB,
        )
        await websocket.send_json({"tipo": "recebido", "id": identificador})


async def _receber_json(websocket: WebSocket) -> Any:
    """Le um frame de texto e o interpreta.

    `receive_text` e nao `receive_json`: o do Starlette levanta
    `json.JSONDecodeError` de dentro dele do mesmo jeito, mas passar por aqui
    deixa o tratamento num lugar so e aceita frame binario sem estourar
    `KeyError`.
    """
    return json.loads(await websocket.receive_text())
```

- [ ] **Step 6: Registrar o router em `create_app`**

Em `src/mobia/app/main.py`, junto do `include_router(whatsapp_router)` (sem o gate de token: o endpoint é público por natureza):

```python
from mobia.api.routes.widget import router as widget_router

    app.include_router(whatsapp_router)
    app.include_router(widget_router)
```

- [ ] **Step 7: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_handshake.py -v --tb=short`
Expected: 9 passed

- [ ] **Step 8: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/routes/widget.py src/mobia/app/main.py src/mobia/app/config.py tests/conftest.py tests/integration/test_widget_handshake.py
git commit -m "feat(TEC-124): a visitante do site fala por websocket, e a mensagem entra na fila de sempre"
```

---

### Task 6: A volta — a resposta chega na sessão aberta

**Files:**
- Modify: `src/mobia/api/routes/widget.py`
- Test: `tests/integration/test_widget_recebe_resposta.py`

**Interfaces:**
- Consumes: `canal_da_sessao` (Task 3).
- Produces: nada novo para fora; o endpoint passa a escrever frames vindos do Redis.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_widget_recebe_resposta.py
"""A resposta do agente volta na sessao aberta. TEC-124, D4."""

import asyncio
import json

from mobia.domain.outbound.web import canal_da_sessao


async def _abrir(ws_cliente, sessao=None):
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    frame = await ws.receber()
    if sessao is not None:
        await ws.receber()  # o historico
    return ws, frame["sessao"]


async def test_a_publicacao_chega_na_sessao(ws_cliente, redis_pool) -> None:
    ws, sessao = await _abrir(ws_cliente)
    try:
        # A assinatura do endpoint e assincrona: sem esta espera o publish
        # pode sair antes de ela existir, e pub/sub nao guarda nada.
        await asyncio.sleep(0.2)
        await redis_pool.publish(
            canal_da_sessao(sessao),
            json.dumps({"tipo": "mensagem", "texto": "olá!", "kind": "resposta"}),
        )
        assert await ws.receber() == {
            "tipo": "mensagem",
            "texto": "olá!",
            "kind": "resposta",
        }
    finally:
        await ws.__aexit__()


async def test_duas_abas_na_mesma_sessao_recebem_as_duas(ws_cliente, redis_pool) -> None:
    # Review Focus 5. O que nao pode acontecer e uma derrubar a outra.
    primeira, sessao = await _abrir(ws_cliente)
    segunda, _ = await _abrir(ws_cliente, sessao=sessao)
    try:
        await asyncio.sleep(0.2)
        await redis_pool.publish(
            canal_da_sessao(sessao),
            json.dumps({"tipo": "mensagem", "texto": "olá!", "kind": "resposta"}),
        )
        assert (await primeira.receber())["texto"] == "olá!"
        assert (await segunda.receber())["texto"] == "olá!"
    finally:
        await primeira.__aexit__()
        await segunda.__aexit__()


async def test_publicacao_de_outra_sessao_nao_vaza(ws_cliente, redis_pool) -> None:
    ws, _ = await _abrir(ws_cliente)
    try:
        await asyncio.sleep(0.2)
        await redis_pool.publish(
            canal_da_sessao("8c0f0a3e-0000-4000-8000-0000000000bb"),
            json.dumps({"tipo": "mensagem", "texto": "de outra pessoa", "kind": "resposta"}),
        )
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "oi"})
        # O proximo frame e o `recebido` da propria mensagem, e nao a fala
        # alheia: se ela tivesse vazado, chegaria primeiro.
        assert (await ws.receber())["tipo"] == "recebido"
    finally:
        await ws.__aexit__()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_recebe_resposta.py -v --tb=short`
Expected: FAIL — `asyncio.TimeoutError` no `receber()`, porque nada assina o canal.

- [ ] **Step 3: Assinar o canal e bombear as publicações**

Em `widget.py`, trocar o corpo do `chat` depois do `_apresentar` e acrescentar a função nova:

```python
    log.info("widget.conectado", sessao=sessao)

    pool = getattr(websocket.app.state, "redis_pool", None)
    if pool is None:
        # Sem Redis nao ha volta possivel. A entrada ainda funcionaria, mas o
        # lead falaria sozinho -- e melhor recusar do que simular atendimento.
        log.error("widget.sem_redis", sessao=sessao)
        await websocket.close(code=CODIGO_INDISPONIVEL)
        return

    # Uma conexao do pool por sessao aberta, enquanto ela viver: e o preco do
    # pub/sub, e o que dimensiona o pool do Redis quando o widget escalar.
    assinatura = pool.pubsub()
    await assinatura.subscribe(canal_da_sessao(sessao))

    entrada = asyncio.create_task(_ler_do_lead(websocket, service, sessao))
    saida = asyncio.create_task(_escrever_do_agente(websocket, assinatura))
    try:
        # A primeira que terminar decide: o lead fechou a aba, ou o socket
        # morreu escrevendo. A outra nao tem mais para quem falar.
        await asyncio.wait({entrada, saida}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for tarefa in (entrada, saida):
            tarefa.cancel()
        # `gather` com `return_exceptions` para o cancelamento de uma nao
        # esconder a excecao da outra nem vazar "task exception never
        # retrieved" no log.
        await asyncio.gather(entrada, saida, return_exceptions=True)
        await assinatura.aclose()
        log.info("widget.desconectado", sessao=sessao)


async def _escrever_do_agente(websocket: WebSocket, assinatura: Any) -> None:
    """Repassa ao navegador o que o worker publicou para esta sessao."""
    async for evento in assinatura.listen():
        if evento.get("type") != "message":
            continue
        await websocket.send_text(
            evento["data"].decode() if isinstance(evento["data"], bytes) else evento["data"]
        )
```

E o `_ler_do_lead` deixa de precisar do `try/except WebSocketDisconnect` no `chat` — ele passa a ser tarefa, e a desconexão termina a tarefa. Envolva o corpo dele:

```python
async def _ler_do_lead(websocket: WebSocket, service: IngestionService, sessao: str) -> None:
    try:
        ...  # o laco de hoje, sem alteracao
    except WebSocketDisconnect:
        return
```

Acrescentar no topo do módulo: `import asyncio`, `from mobia.domain.outbound.web import canal_da_sessao`, e

```python
# 1011 e "condicao inesperada no servidor" do RFC 6455: e o que o widget ve
# quando o Redis nao esta montado, que nao e culpa dele.
CODIGO_INDISPONIVEL = 1011
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_recebe_resposta.py tests/integration/test_widget_handshake.py -v --tb=short`
Expected: 12 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/routes/widget.py tests/integration/test_widget_recebe_resposta.py
git commit -m "feat(TEC-124): a fala do agente publicada pelo worker chega a sessao aberta no uvicorn"
```

---

### Task 7: O limite por IP no handshake, e o comentário que mentia

**Files:**
- Modify: `src/mobia/api/routes/widget.py`, `src/mobia/app/main.py:40-45` (o comentário), `src/mobia/api/middleware.py` (o comentário de `ROTAS_ISENTAS`, se ele disser algo que deixou de valer)
- Test: `tests/integration/test_widget_limite_por_ip.py`

**Interfaces:**
- Consumes: `resolver_ip` e `ROTAS_ISENTAS` de `api/middleware.py`; `chave_de_ip`, `consumir`, `JANELA_DE_UM_MINUTO`; `registrar_bloqueio`, `ESCOPO_IP`, `CHANNEL_HTTP`.
- Produces: `CODIGO_EXCESSO = 1013` em `widget.py`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_widget_limite_por_ip.py
"""O handshake conta contra o limite por IP. TEC-124, D7; RNF-16."""

from sqlalchemy import select

from mobia.app.config import get_settings
from mobia.domain.limites.models import RateLimitEvent


async def test_handshake_acima_do_limite_fecha_com_1013(
    ws_cliente, session, monkeypatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(2):
        async with ws_cliente(ip="198.51.100.9") as ws:
            await ws.aceitar()

    async with ws_cliente(ip="198.51.100.9") as ws:
        assert await ws.fechamento() == 1013

    evento = (
        await session.execute(select(RateLimitEvent).where(RateLimitEvent.chave == "198.51.100.9"))
    ).scalar_one()
    assert evento.limite == 2


async def test_outro_ip_nao_e_afetado(ws_cliente, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    async with ws_cliente(ip="198.51.100.10") as ws:
        await ws.aceitar()
    async with ws_cliente(ip="198.51.100.11") as ws:
        await ws.aceitar()
```

> Confira o nome real da coluna de `RateLimitEvent` (`chave`, `limite`) em `domain/limites/models.py` antes de rodar, e ajuste a asserção se divergir.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_limite_por_ip.py -v --tb=short`
Expected: FAIL — a terceira conexão é aceita, porque `BaseHTTPMiddleware` não vê escopo `websocket`.

- [ ] **Step 3: Contar o handshake dentro do endpoint**

No topo de `chat`, **antes do `accept()`**:

```python
    correlation_id.set(str(uuid.uuid4()))

    pool = getattr(websocket.app.state, "redis_pool", None)
    if not await _cabe_no_limite_por_ip(websocket, pool):
        await websocket.close(code=CODIGO_EXCESSO)
        return

    await websocket.accept()
```

E a função:

```python
async def _cabe_no_limite_por_ip(websocket: WebSocket, pool: Any) -> bool:
    """O limite da RNF-16 aplicado ao aperto de mao.

    **Mora aqui, e nao no middleware, porque o middleware nao alcanca.**
    `RateLimitPorIP` e `BaseHTTPMiddleware`, e essa classe devolve cedo para
    todo escopo que nao seja `http`: o handshake de um `ws://` nunca passa por
    ela. Ate a TEC-124 o comentario de `create_app` dizia o contrario -- que
    aplicar o middleware por omissao evitava "errar para o lado de esquecer o
    widget do TEC-124" --, e era exatamente esse o erro que ele deixava
    acontecer. A Emenda E-01 da RNF-16 esta certa ao escrever "toda rota HTTP
    restante": o widget nao e uma.

    Mesmo limite e mesma janela do middleware, de proposito: dois tetos para o
    mesmo IP seriam duas coisas para manter em sincronia.
    """
    settings = get_settings()
    limite = settings.rate_limit_requisicoes_por_ip_por_minuto
    if limite <= 0:
        return True

    ip = resolver_ip(
        socket_host=websocket.client.host if websocket.client else None,
        forwarded_for=websocket.headers.get("x-forwarded-for"),
        confiar_em_forwarded_for=settings.confiar_em_forwarded_for,
    )
    if ip is None:
        return True

    consumo = await consumir(
        pool, chave=chave_de_ip(ip), limite=limite, janela_segundos=JANELA_DE_UM_MINUTO
    )
    if consumo.permitido:
        return True

    log.warning(
        "ratelimit.blocked",
        escopo=ESCOPO_IP,
        ip=ip,
        rota="/widget/chat",
        volume=consumo.volume,
        limite=limite,
    )
    await registrar_bloqueio(
        get_sessionmaker(),
        pool,
        escopo=ESCOPO_IP,
        chave=ip,
        channel=CHANNEL_HTTP,
        volume=consumo.volume,
        limite=limite,
    )
    return False
```

Imports novos em `widget.py`:

```python
from mobia.api.middleware import resolver_ip
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import CHANNEL_HTTP, ESCOPO_IP
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_ip, consumir
```

E a constante:

```python
# 1013 e "try again later" do RFC 6455 -- o analogo do 429 que o middleware
# devolve na rota HTTP.
CODIGO_EXCESSO = 1013
```

- [ ] **Step 4: Corrigir o comentário de `create_app`**

Em `src/mobia/app/main.py`, substituir o comentário do `add_middleware`:

```python
    # Primeiro middleware do projeto (TEC-205). Aplica-se por omissao e nao por
    # opt-in: uma lista de rotas incluidas erraria para o lado de esquecer uma
    # rota nova, que e o erro caro. Quem precisa ficar de fora esta em
    # `ROTAS_ISENTAS`, com a razao de cada uma escrita la.
    #
    # **Ele nao cobre o widget, e ate a TEC-124 este comentario dizia que
    # sim.** `BaseHTTPMiddleware` devolve cedo para todo escopo que nao seja
    # `http`, entao o handshake de `/widget/chat` nunca passa por aqui. O
    # limite por IP daquela rota e aplicado dentro dela -- ver
    # `_cabe_no_limite_por_ip` em `api/routes/widget.py`.
    app.add_middleware(RateLimitPorIP)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_widget_limite_por_ip.py -v --tb=short`
Expected: 2 passed

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/api/routes/widget.py src/mobia/app/main.py tests/integration/test_widget_limite_por_ip.py
git commit -m "fix(TEC-124): o handshake do widget conta no limite por IP, que o middleware http nunca alcancou"
```

---

### Task 8: O worker monta as portas por canal

**Files:**
- Modify: `src/mobia/workers/main.py:100-105`, `src/mobia/workers/jobs/process_message.py:361-364` e `:498-502`
- Test: `tests/integration/test_indicador_por_canal.py`

**Interfaces:**
- Consumes: `RoteadorPorCanal` (Task 2), `WebOutbound` (Task 3), `CANAL_WHATSAPP`/`CANAL_WEB` (Task 1).
- Produces: `ctx["outbound"]` passa a ser `RoteadorPorCanal`; `ctx["indicador"]` vira `ctx["indicadores"]: dict[str, IndicadorDePresencaPort]`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_indicador_por_canal.py
"""O indicador de digitacao escolhido pelo canal da linha. TEC-124, D5."""

import uuid
from datetime import UTC, datetime
from typing import Any

from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.app.config import get_settings
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.crypto import aad_de, encrypt
from mobia.workers.jobs.process_message import process_message

SESSAO = "8c0f0a3e-0000-4000-8000-0000000000cc"


class IndicadorEspiao:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, str]] = []

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        self.chamadas.append((provider_message_id, de))


async def _entrada_web(session) -> Message:
    """A entrada do widget, com os DOIS campos que enganam a guarda de insumo."""
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL_WEB,
        provider_message_id="m-1",
        sender_external_id=SESSAO,
        recipient_external_id=REMETENTE_DO_WIDGET,
        conversation_key=SESSAO,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("oi", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.RECEIVED,
        created_at=datetime.now(UTC),
    )
    session.add(linha)
    await session.commit()
    return linha


async def test_a_linha_web_nao_indica_pela_meta(
    session, redis_pool, monkeypatch, outbound_fake
) -> None:
    """O perigo e concreto, e nao hipotetico.

    `indicador_de_digitacao` desiste cedo quando `provider_message_id` ou
    `recipient_external_id` sao nulos. No web os DOIS estao preenchidos -- o
    id do cliente e a constante `widget` --, entao a guarda nao desiste e o
    `WhatsAppIndicador` dispararia um POST para a Meta com um UUID de sessao
    no lugar do wamid.
    """
    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "0")
    get_settings.cache_clear()

    linha = await _entrada_web(session)
    espiao = IndicadorEspiao()
    ctx: dict[str, Any] = _ctx()
    ctx["outbound"] = outbound_fake()
    ctx["indicadores"] = {CANAL_WHATSAPP: espiao, CANAL_WEB: IndicadorNoop()}

    await process_message(ctx, str(linha.id))

    assert espiao.chamadas == []


async def test_a_linha_whatsapp_continua_indicando(
    session, redis_pool, monkeypatch, outbound_fake
) -> None:
    """A outra metade: o dicionario trocado de lado calaria o WhatsApp."""
    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "0")
    get_settings.cache_clear()

    linha = await gravar(session, created_at=datetime.now(UTC))
    espiao = IndicadorEspiao()
    ctx: dict[str, Any] = _ctx()
    ctx["outbound"] = outbound_fake()
    ctx["indicadores"] = {CANAL_WHATSAPP: espiao, CANAL_WEB: IndicadorNoop()}

    await process_message(ctx, str(linha.id))

    assert len(espiao.chamadas) == 1
```

> `_ctx` e `gravar` são importados de módulo irmão, com `# type: ignore[import-not-found]`, do mesmo jeito que `test_indicador_de_digitacao.py` já faz — é o idioma desta suíte, não improviso. `_ctx()` monta o `outbound` como `GuardedOutbound` cru, cujo `_deliver` levanta `NotImplementedError`; por isso a linha `ctx["outbound"] = outbound_fake()`, já que aqui o turno **roda** de verdade.

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_por_canal.py -v --tb=short`
Expected: FAIL com `KeyError: 'indicador'`

- [ ] **Step 3: Trocar a montagem no worker**

```python
# src/mobia/workers/main.py
    ctx["outbound"] = RoteadorPorCanal(
        session_factory,
        {
            CANAL_WHATSAPP: WhatsAppOutbound(session_factory),
            # Mesmo `ctx["redis"]` do agendador -- o ARQ ja o gravou antes
            # deste hook, e um segundo pool seria redundante.
            CANAL_WEB: WebOutbound(session_factory, ctx["redis"]),
        },
    )
    # TEC-274 e TEC-124. Dicionario e nao instancia unica: no web os dois
    # campos que fariam `indicador_de_digitacao` desistir estao preenchidos, e
    # o `WhatsAppIndicador` dispararia um POST para a Meta com um UUID de
    # sessao no lugar do wamid. Sem `session_factory`: as guardas do indicador
    # moram no agendador (`domain/outbound/presenca.py`), nao no adaptador.
    ctx["indicadores"] = {
        CANAL_WHATSAPP: WhatsAppIndicador(),
        # Lacuna declarada da TEC-124: publicar "digitando" exigiria a sessao
        # na assinatura do `IndicadorDePresencaPort`, e esta card nao mexe
        # nesse contrato.
        CANAL_WEB: IndicadorNoop(),
    }
```

- [ ] **Step 4: Trocar o uso em `process_message`**

Em `process_message.py`, no bloco do indicador (hoje `indicador=ctx["indicador"]`):

```python
        async with indicador_de_digitacao(
            session_factory,
            message=linha,
            # `ctx["indicadores"][canal]` direto, e nao `.get(...) or
            # IndicadorNoop()`, pela mesma razao que o comentario de
            # `agendador` acima escreve: o fallback trocaria a porta real por
            # um duble dentro de producao, e o sintoma de um `startup` que
            # deixasse de popular a chave -- ou de um canal novo sem
            # indicador -- seria nenhum indicador, nunca, sem log e sem erro.
            indicador=ctx["indicadores"][linha.channel],
            apos_segundos=apos_segundos,
        ):
```

E atualizar o comentário de `ctx[...]` do topo da função, que hoje cita `ctx["indicador"]` no singular.

- [ ] **Step 5: Corrigir os testes que montam `ctx["indicador"]`**

São sete, medidos nesta árvore em 24/09/2026:

| arquivo | linha | o que está lá |
| --- | --- | --- |
| `tests/integration/test_process_message_agrupado.py` | 43 | `IndicadorNoop()` — é o `_ctx()` que os outros importam |
| `tests/integration/test_indicador_de_digitacao.py` | 240 | `espiao` |
| `tests/integration/test_cancelamento_do_worker.py` | 65 | `IndicadorNoop()` |
| `tests/integration/test_handoff_por_erro.py` | 32 | `IndicadorNoop()` |
| `tests/integration/test_moderacao_na_rajada.py` | 72 | `IndicadorNoop()` |
| `tests/integration/test_sweep_stalled.py` | 32 | `IndicadorNoop()` |
| `tests/features/test_reprocessamento_apos_falha.py` | 49 | `IndicadorNoop()` |

Cada um vira `"indicadores": {CANAL_WHATSAPP: <o que estava lá>, CANAL_WEB: IndicadorNoop()}`. Confirme com `grep -rn '"indicador"' tests/` que não sobrou nenhum — a tabela é de uma data, e a branch pode ter mexido em algum depois.

- [ ] **Step 6: Rodar o bloco e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration -k "indicador or presenca or cancelamento" -v --tb=short`
Expected: tudo verde

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/workers/main.py src/mobia/workers/jobs/process_message.py tests/
git commit -m "feat(TEC-124): o worker monta saida e indicador por canal, e o web nao fala com a Meta"
```

---

### Task 9: Reengajamento não alcança o web

**Files:**
- Modify: `src/mobia/domain/followup/repositorio.py` (`_CTES_DA_ANCORA`, os dois `text()` e os dois sítios de execução)
- Test: `tests/integration/test_followup_ignora_o_web.py`

**Interfaces:**
- Consumes: `CANAIS_COM_REENGAJAMENTO` (Task 1).
- Produces: nada novo — as duas consultas passam a aceitar o bind `canais_com_reengajamento`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/integration/test_followup_ignora_o_web.py
"""A cadencia de reengajamento nao alcanca o canal web. TEC-124, D8."""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.followup.repositorio import candidatos_a_followup, listar_dormentes
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
AGORA = ANCORA + timedelta(days=3)


async def _lead(session, *, canal: str, conversa: str) -> None:
    """Um lead qualificado e quente, com a fala ancora ja velha.

    Mesma forma de `_qualificacao` e `_fala_do_lead` em
    `test_followups_model.py`, com o canal por parametro -- la ele e a
    constante `CANAL` do modulo.
    """
    session.add(
        LeadQualification(
            channel=canal,
            conversation_key=conversa,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura="QUENTE",
        )
    )
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=canal,
            provider_message_id=f"id.{identificador.hex[:10]}",
            sender_external_id=conversa,
            recipient_external_id="222222222",
            conversation_key=conversa,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=ANCORA,
        )
    )
    await session.commit()


async def test_lead_do_web_nao_vira_candidato(session) -> None:
    await _lead(session, canal=CANAL_WHATSAPP, conversa="5511955554444")
    await _lead(session, canal=CANAL_WEB, conversa="8c0f0a3e-0000-4000-8000-0000000000dd")

    candidatos = await candidatos_a_followup(session, agora=AGORA)

    assert {candidato.channel for candidato in candidatos} == {CANAL_WHATSAPP}


async def test_lead_do_web_tambem_nao_aparece_entre_os_dormentes(session) -> None:
    """A mesma CTE serve as duas consultas -- e este teste e o que prova que o
    filtro ficou na CTE compartilhada e nao so na primeira delas."""
    await _lead(session, canal=CANAL_WEB, conversa="8c0f0a3e-0000-4000-8000-0000000000de")

    dormentes = await listar_dormentes(session, agora=AGORA)

    assert [dormente.channel for dormente in dormentes] == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_followup_ignora_o_web.py -v --tb=short`
Expected: FAIL — o lead do web aparece entre os candidatos.

- [ ] **Step 3: Filtrar na CTE compartilhada**

Em `_CTES_DA_ANCORA`, dentro de `falas_do_lead`:

```sql
         WHERE direction = 'INBOUND'
           AND bloqueada_em IS NULL
           -- TEC-124, D8. Allowlist e nao `channel <> 'web'`: canal novo
           -- nasce de fora do reengajamento e entra quando alguem decidir
           -- que ele tem para onde empurrar mensagem. Filtrar aqui, na CTE
           -- que as duas consultas compartilham, e o que garante que o
           -- dormente tambem nao apareca.
           AND channel IN :canais_com_reengajamento
```

Nos dois `text()`, acrescentar o bind:

```python
).bindparams(
    bindparam("temperaturas_validas", expanding=True),
    bindparam("canais_com_reengajamento", expanding=True),
)
```

E nos dois sítios de execução — o de `candidatos_a_followup` (~linha 270) e o de `listar_dormentes` (~linha 412) — acrescentar ao dicionário de parâmetros:

```python
        "canais_com_reengajamento": CANAIS_COM_REENGAJAMENTO,
```

- [ ] **Step 4: Rodar e ver passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_followup_ignora_o_web.py tests/integration/test_followups_model.py tests/integration/test_followups_dormentes.py -v --tb=short`

> Se `test_followups_dormentes.py` não existir com esse nome, rode `tests/integration -k followup` — o ponto é que as duas consultas que compartilham a CTE sejam exercitadas, não o nome do arquivo.
Expected: tudo verde

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/followup/repositorio.py tests/integration/test_followup_ignora_o_web.py
git commit -m "feat(TEC-124): o reengajamento so alcanca canal com push, e o web fica de fora por allowlist"
```

---

### Task 10: Os cenários da card, as emendas e a prosa

**Files:**
- Create: `tests/features/test_atendimento_pelo_widget_web.py`
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (três emendas), `src/mobia/domain/outbound/port.py` (a emenda no docstring)
- Test: o próprio arquivo de features

**Interfaces:**
- Consumes: tudo o que as tasks anteriores produziram.
- Produces: nada.

- [ ] **Step 1: Escrever os três cenários Gherkin da card**

```python
# tests/features/test_atendimento_pelo_widget_web.py
"""Cenarios Gherkin de TEC-124.

Funcionalidade: Atendimento pelo widget web
"""

import asyncio
import json

from sqlalchemy import select

from mobia.domain.messages.canais import CANAL_WEB
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.web import canal_da_sessao


async def test_conversar_pelo_chat_do_site(ws_cliente, session, redis_pool) -> None:
    """Cenario: Conversar pelo chat do site."""
    ws = ws_cliente()
    await ws.__aenter__()
    try:
        # Dada uma sessao de widget web aberta
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        sessao = (await ws.receber())["sessao"]
        await asyncio.sleep(0.2)

        # Quando a visitante envia a pergunta
        await ws.enviar(
            {
                "tipo": "mensagem",
                "id": "m-1",
                "texto": "esse apartamento da zona sul ainda está disponível?",
            }
        )
        await ws.receber()

        # Entao a mensagem entra na fila de processamento com canal WEB
        linha = (
            await session.execute(select(Message).where(Message.conversation_key == sessao))
        ).scalar_one()
        assert linha.channel == CANAL_WEB
        assert linha.status in (MessageStatus.RECEIVED, MessageStatus.QUEUED)
        assert await redis_pool.zcard("arq:queue") == 1

        # E a resposta do agente chega na mesma sessao
        await redis_pool.publish(
            canal_da_sessao(sessao),
            json.dumps({"tipo": "mensagem", "texto": "Ainda está!", "kind": "resposta"}),
        )
        assert (await ws.receber())["texto"] == "Ainda está!"
    finally:
        await ws.__aexit__()


async def test_reconectar_sem_perder_o_que_ja_foi_dito(ws_cliente, session) -> None:
    """Cenario: Reconectar sem perder o que ja foi dito."""
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        sessao = (await ws.receber())["sessao"]
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "quero dois quartos"})
        await ws.receber()

    # Quando a conexao cai e a visitante recarrega a pagina
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": sessao})
        await ws.receber()
        historico = await ws.receber()

    # Entao a sessao e retomada com o historico visivel
    assert [fala["texto"] for fala in historico["mensagens"]] == ["quero dois quartos"]

    # E nenhuma mensagem ja recebida pelo servidor e perdida
    linhas = (await session.execute(select(Message))).scalars().all()
    assert len(linhas) == 1


async def test_whatsapp_indisponivel_nao_afeta_o_canal_web(
    ws_cliente, session, monkeypatch
) -> None:
    """Cenario: WhatsApp indisponivel nao afeta o canal web."""
    # Dado que a integracao com o WhatsApp esta fora do ar: o token some, que
    # e a forma como esta arvore representa "sem WhatsApp" -- `workers/main.py`
    # recusa subir sem ele.
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    from mobia.app.config import get_settings

    get_settings.cache_clear()

    # Quando uma visitante escreve pelo widget web
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": None})
        sessao = (await ws.receber())["sessao"]
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "oi"})
        assert (await ws.receber())["tipo"] == "recebido"

    # Entao o atendimento acontece normalmente
    linha = (
        await session.execute(select(Message).where(Message.conversation_key == sessao))
    ).scalar_one()
    assert linha.channel == CANAL_WEB
```

- [ ] **Step 2: Rodar e ver passar** (as tasks anteriores já entregaram o comportamento)

Run: `./.venv/Scripts/python.exe -m pytest tests/features/test_atendimento_pelo_widget_web.py -v --tb=short`
Expected: 3 passed

- [ ] **Step 3: A emenda no docstring de `OutboundPort`**

Em `src/mobia/domain/outbound/port.py`, dentro do docstring do `Protocol`, logo depois do bullet de `EnvioRetentavel`:

```
    **Emenda (TEC-124, 24/09/2026): o adaptador do canal web nao levanta
    nenhum dos tres.** A lista acima pressupoe que a rede seja o caminho ate o
    lead, e no WhatsApp ela e. No web nao: a fala ja foi gravada em `messages`
    antes de qualquer publicacao, e a reconexao a mostra. Falha de Redis,
    ausencia de ouvinte e kind sem forma viram log e o envio conta como
    entregue -- retentar cobraria uma chamada nova e paga ao modelo para
    reentregar o que ja esta no banco. Ver `domain/outbound/web.py`.
```

- [ ] **Step 4: As três emendas ao SRS**

Em `docs/srs/srs-agente-sdr-imobiliario-v1.0.md`, como item aninhado abaixo de cada regra. Confira o próximo número livre de cada uma antes de escrever — RN-01.1 e RNF-16 já têm emendas nesta árvore.

Abaixo da **RN-01.1**:

```markdown
  - **Emenda E-01 (TEC-124, 24/09/2026):** a identidade do canal web é o **UUID de sessão emitido pelo servidor**, não o telefone. A segunda frase desta regra — "um mesmo lead identificado pelo telefone tem histórico unificado entre canais" — descreve a TEC-129 e não esta card: aqui, duas sessões da mesma pessoa, em dois navegadores, são duas conversas sem relação entre si, e o widget não pede telefone em momento algum. O id é emitido no primeiro frame e reapresentado pela página na reconexão; ele nunca viaja em URL, porque em query string entraria em log de acesso, `Referer` e histórico do navegador. **Consequência declarada:** quem tiver o id lê aquela conversa — é a mesma exposição de um link mágico, mitigada por ser UUIDv4 e por não haver autenticação de visitante nesta fase.
```

Abaixo da **RN-13.1**:

```markdown
  - **Emenda E-01 (TEC-124, 24/09/2026):** a cadência vale apenas para canal com push. O canal web fica de fora por construção — a seleção de candidatos filtra por `CANAIS_COM_REENGAJAMENTO` (`domain/messages/canais.py`), hoje só o WhatsApp. A razão é que um follow-up de 24 h numa sessão de navegador não chega a ninguém: viraria linha em `followups` marcada como enviada e texto que a visitante só veria se voltasse por conta própria — caso em que ela não precisava do follow-up. **É allowlist e não exclusão do web**: canal novo nasce de fora e entra quando alguém decidir que ele tem para onde empurrar mensagem. Reengajar visitante de site é decisão de produto, e não existe card para ela.
```

Abaixo da **RNF-16** (como Emenda E-02, depois da E-01 da TEC-205):

```markdown
- **Emenda E-02 (TEC-124, 24/09/2026)** — o limite por IP passa a ser aplicado também no **handshake do WebSocket do widget**, por dentro do próprio endpoint. A Emenda E-01 escreve que o limite "se aplica a toda rota HTTP restante", e isso está correto: `RateLimitPorIP` é um `BaseHTTPMiddleware`, e essa classe devolve cedo para todo escopo que não seja `http` — o handshake de `ws://` nunca passava por ela. O comentário de `create_app` afirmava o contrário desde a TEC-205, citando o widget desta card pelo nome, e foi corrigido junto. Mesmo limite e mesma janela do middleware, de propósito; o excedente recebe o código de fechamento 1013, análogo ao 429 da rota HTTP, e grava a mesma linha em `rate_limit_events`.
```

- [ ] **Step 5: A listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Releia cada `ALTERADO` e cada `VIZINHO` que a branch produziu. Os suspeitos conhecidos: o comentário da UNIQUE em `messages/models.py` (que fala do widget no futuro e agora ele existe), o de `ROTAS_ISENTAS`, o docstring de `IngestionService`, e o de `EnvioForaDaJanela` em `port.py`. Corrija o que a branch tornou falso.

- [ ] **Step 6: A suíte inteira, uma vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — rode por blocos (`tests/unit`, `tests/integration`, `tests/features`), conforme o CLAUDE.md.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add tests/features/test_atendimento_pelo_widget_web.py docs/srs/srs-agente-sdr-imobiliario-v1.0.md src/mobia/domain/outbound/port.py
git commit -m "docs(TEC-124): as emendas do canal web, e os tres cenarios da card exercitados"
```

---

## Depois do plano

`git push -u origin feat/tec-124-widget-web-via-websocket`, PR contra `main`, comentário na card e mover para **Em análise**. O comentário tem de registrar, no mínimo:

- **A divergência de caixa**: a card escreve `canal = WEB`, a implementação grava `web` (D1).
- **A lacuna do widget**: ninguém consegue conversar pelo site quando este PR entrar — existe o canal, não existe o chat.
- **A lacuna do indicador de digitação** no web (D5).
- **A decisão de produto** de não reengajar o canal web (D8).
- **O achado do limite por IP** (D7) — o comentário do repo prometia cobertura que não existia.
- **As três emendas ao SRS**, nomeadas.

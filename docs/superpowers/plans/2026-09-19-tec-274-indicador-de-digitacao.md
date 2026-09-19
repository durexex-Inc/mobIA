# TEC-274 — Indicador de digitação: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** um turno que passa de 4 segundos manda indicador de digitação ao lead no WhatsApp, uma vez, sem que falhar nisso custe a resposta.

**Architecture:** um gerente de contexto em `process_message` cria uma tarefa concorrente que dorme o limiar, confere as guardas de opt-out e atendimento humano, e chama uma porta nova (`IndicadorDePresencaPort`). `executar_turno` não muda. A tarefa é cancelada na saída, sem `await`.

**Tech Stack:** Python 3.13, asyncio, httpx, SQLAlchemy async, pytest (`asyncio_mode = "auto"`), structlog.

**Spec:** `docs/superpowers/specs/2026-09-19-tec-274-indicador-de-digitacao-design.md` — leia antes de começar. Este plano argumenta a partir dele.

## Global Constraints

- **Os três gates estáticos, com o escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  `./.venv/Scripts/python.exe -m mypy`
  O formatador é gate separado do linter: passar num não diz nada sobre o outro.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado, que segue o valor.
- **Texto que o lead recebe: português COM acento.** Esta card não acrescenta nenhum — o indicador não tem texto.
- **Prosa em `docs/`: com acento.**
- **Mensagens de commit:** português sem acento no assunto, formato `tipo(TEC-274): o que passou a ser verdade`, e terminando com a linha `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **`executar_turno` não pode ganhar nem perder uma linha nesta card** (D2 do desenho). Se um passo parecer pedir isso, pare e releia a D2.
- **Nenhuma migration.** O `wamid` e o `phone_number_id` já estão gravados.
- O corpo exato que a Meta exige, e que nenhum passo pode alterar:
  `{"messaging_product": "whatsapp", "status": "read", "message_id": "<wamid>", "typing_indicator": {"type": "text"}}`

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/mobia/domain/outbound/presenca.py` | **novo.** O contrato (`IndicadorDePresencaPort`), o dublê de produção (`IndicadorNoop`), e o agendador com as guardas (`indicador_de_digitacao`). Domínio, agnóstico de canal. |
| `src/mobia/domain/outbound/whatsapp.py` | ganha `WhatsAppIndicador` — o único que sabe de HTTP e da Meta. |
| `src/mobia/app/config.py` | ganha `indicador_de_digitacao_apos_segundos`. |
| `src/mobia/workers/jobs/process_message.py` | abre o gerente de contexto em volta de `executar_turno`; lê `ctx["indicador"]`. |
| `src/mobia/workers/main.py` | monta `ctx["indicador"]` no `startup`. |
| `tests/integration/test_indicador_de_digitacao.py` | **novo.** O agendador e as guardas. |
| `tests/integration/test_whatsapp_outbound.py` | ganha o teste do corpo que vai para a Meta. |
| `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` | Emenda E-01 da RN-04.7. |

A fronteira entre `presenca.py` e `whatsapp.py` é a mesma que `port.py`/`whatsapp.py` já desenha: as guardas são domínio, o HTTP é canal.

---

### Task 1: O contrato, o noop e o agendador com as guardas

**Files:**
- Create: `src/mobia/domain/outbound/presenca.py`
- Modify: `src/mobia/app/config.py` (junto de `whatsapp_api_base`, linha 134)
- Test: `tests/integration/test_indicador_de_digitacao.py` (novo)

**Interfaces:**
- Consumes: `esta_em_optout_por_mensagem(session, message_id) -> bool` de `mobia.domain.optout.repositorio`; `esta_silenciada_por_mensagem(session, message_id) -> bool` de `mobia.domain.atendimento.repositorio`; `Message` de `mobia.domain.messages.models`.
- Produces:
  - `IndicadorDePresencaPort` — Protocol com `async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None`
  - `IndicadorNoop` — implementação que só loga
  - `indicador_de_digitacao(session_factory, *, message: Message, indicador: IndicadorDePresencaPort, apos_segundos: float) -> AsyncIterator[None]` — gerente de contexto assíncrono
  - `Settings.indicador_de_digitacao_apos_segundos: float = 4.0`

O teste é de integração e não unitário porque as guardas consultam o Postgres: `docker compose` precisa estar de pé.

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/integration/test_indicador_de_digitacao.py`:

```python
"""O relogio do indicador de digitacao, e as guardas do disparo. TEC-274, RN-04.7."""

import asyncio
import uuid

from conftest import CANAL_AGENTE, CONVERSA_AGENTE
from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import registrar_optout
from mobia.domain.outbound.presenca import indicador_de_digitacao
from mobia.infra.db import get_sessionmaker

# Centesimos de segundo e nao os 4 s da regra: tres cenarios a 4 s reais
# custariam mais de doze segundos por execucao da suite. O que se exercita e o
# relogio, e ele nao sabe que numero esta contando -- ver a D7 do desenho.
DEPRESSA = 0.02
DEVAGAR = 0.20


class IndicadorEspiao:
    """Conta os disparos. `erro` faz o disparo levantar, sem deixar de contar."""

    def __init__(self, erro: Exception | None = None) -> None:
        self.chamadas: list[tuple[str, str]] = []
        self._erro = erro

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        self.chamadas.append((provider_message_id, de))
        if self._erro is not None:
            raise self._erro


async def _entrada(session, *, wamid: str | None = "wamid.TESTE") -> Message:
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL_AGENTE,
        provider_message_id=wamid,
        conversation_key=CONVERSA_AGENTE,
        recipient_external_id="222222222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status="PROCESSING",
    )
    session.add(linha)
    await session.commit()
    return linha


async def test_geracao_demorada_dispara_o_indicador_uma_vez(session, banco_limpo) -> None:
    """O primeiro cenario do Gherkin, com a clausula 'UMA vez' afirmada.

    A asserta e `== 1` e nao `>= 1` de proposito: um laco de renovacao
    acidental passaria em `>= 1` e e exatamente o que a card proibe.
    """
    linha = await _entrada(session)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == [("wamid.TESTE", "222222222")]


async def test_geracao_rapida_nao_dispara_nada(session, banco_limpo) -> None:
    """O segundo cenario do Gherkin."""
    linha = await _entrada(session)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEVAGAR
    ):
        await asyncio.sleep(DEPRESSA)

    assert espiao.chamadas == []


async def test_falha_no_indicador_nao_derruba_o_corpo(session, banco_limpo) -> None:
    """O terceiro cenario do Gherkin, no nivel do agendador.

    O corpo do `async with` e a resposta do agente: ele tem de completar e
    devolver o valor dele mesmo com o indicador levantando.
    """
    linha = await _entrada(session)
    espiao = IndicadorEspiao(erro=RuntimeError("a Meta caiu"))
    entregue = None

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)
        entregue = "a resposta saiu"

    assert espiao.chamadas != []
    assert entregue == "a resposta saiu"


async def test_optout_durante_a_espera_barra_o_indicador(session, banco_limpo) -> None:
    """A D3 do desenho, e a razao de as guardas rodarem no disparo.

    O opt-out chega DEPOIS de o relogio partir. Uma guarda que dependesse da
    posicao no codigo -- conferida antes de agendar -- deixaria o indicador
    sair para quem acabou de pedir silencio.
    """
    linha = await _entrada(session)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await registrar_optout(
            get_sessionmaker(),
            channel=CANAL_AGENTE,
            conversation_key=CONVERSA_AGENTE,
            message_id=linha.id,
        )
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == []


async def test_atendimento_humano_barra_o_indicador(
    session, semear_corretor, banco_limpo
) -> None:
    """RN-16.4: quem assumiu a conversa nao pode ter o agente digitando por cima."""
    linha = await _entrada(session)
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == []


async def test_linha_sem_wamid_nao_agenda_nada(session, banco_limpo) -> None:
    """`provider_message_id` e nullable, e o indicador nao existe sem ele.

    A Meta nao aceita indicador para um numero -- so como anotacao sobre uma
    mensagem recebida. Sem o wamid nao ha o que enviar, e agendar uma tarefa
    para descobrir isso quatro segundos depois seria trabalho para nada.
    """
    linha = await _entrada(session, wamid=None)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == []
```

- [ ] **Step 2: Rodar o teste para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_de_digitacao.py --tb=short
```

Esperado: FAIL na coleta, com `ModuleNotFoundError: No module named 'mobia.domain.outbound.presenca'`.

Se em vez disso vierem centenas de `ERROR` de setup com `ConnectionResetError [WinError 64]`, o banco ainda está subindo — espere e repita antes de diagnosticar qualquer coisa. Ver a seção "O banco demora mais que o healthcheck diz" no CLAUDE.md.

- [ ] **Step 3: Escrever `presenca.py`**

```python
"""O indicador de digitacao, e o relogio que decide quando envia-lo.

TEC-274, RN-04.7 (Emenda E-01). O contrato e proprio e nao um metodo a mais em
`OutboundPort` porque as duas semanticas sao opostas: la o TIPO da excecao
decide o desfecho do turno, e aqui excecao nenhuma decide coisa alguma. Ver a
D4 do desenho.

**A guarda mora aqui, no agendador, e nao no adaptador** -- e nao ha
equivalente de `GuardedOutbound` para herdar. A rota ate
`IndicadorDePresencaPort` e uma so, e e esta: quem instanciar um adaptador
direto e chama-lo por fora nao tem guarda nenhuma, o mesmo risco que o
docstring de `OutboundPort` ja escreve para si.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.atendimento.repositorio import esta_silenciada_por_mensagem
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import esta_em_optout_por_mensagem

log = structlog.get_logger(__name__)


class IndicadorDePresencaPort(Protocol):
    """Mostrar ao lead que estamos respondendo. Nada mais.

    **Nenhuma excecao deste metodo muda o desfecho do turno**, e e a
    diferenca central para `OutboundPort.send`. Nao ha retorno a interpretar,
    nao ha `kind`, nao ha reserva em `outbound_dispatches` e nao ha
    retentativa a decidir: um indicador que chega tarde nao vale nada, e a
    regra existe contra a percepcao de abandono -- falhar nela nao pode
    custar a resposta. Quem implementar isto pode levantar o que quiser; o
    agendador engole tudo e loga.

    `provider_message_id` e o id da mensagem de ENTRADA no provedor (o
    `wamid`, no WhatsApp), e nao um id nosso: o indicador da Meta e uma
    anotacao sobre uma mensagem recebida, nao um envio para um numero.
    """

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None: ...


class IndicadorNoop:
    """Nao indica nada -- o ambiente sem canal, e o duble natural nos testes."""

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        log.info("presenca.noop")


async def _esperar_e_indicar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_id: uuid.UUID,
    provider_message_id: str,
    de: str,
    indicador: IndicadorDePresencaPort,
    apos_segundos: float,
) -> None:
    """Dorme o limiar, confere as guardas, e dispara uma vez.

    **As guardas rodam aqui, depois do sono, e nao antes dele.** Conferi-las
    no agendamento cobriria so o opt-out ja gravado quando o turno comecou;
    conferi-las no disparo cobre tambem o lead que digita "parar" DURANTE a
    espera, que e precisamente a janela em que isso acontece. Sao as mesmas
    duas consultas de `GuardedOutbound.send` -- ver a D3 do desenho.

    O `except Exception` envolve as guardas junto com o disparo de proposito:
    um banco indisponivel nao pode virar excecao numa tarefa que ninguem
    aguarda. `asyncio.CancelledError` e `BaseException` e passa reto, que e o
    desfecho certo quando o gerente de contexto cancela.
    """
    await asyncio.sleep(apos_segundos)
    try:
        async with session_factory() as session:
            if await esta_em_optout_por_mensagem(session, message_id):
                log.info("presenca.indicador_barrado", motivo="optout")
                return
            if await esta_silenciada_por_mensagem(session, message_id):
                log.info("presenca.indicador_barrado", motivo="atendimento_humano")
                return
        await indicador.indicar_digitacao(provider_message_id=provider_message_id, de=de)
        log.info("presenca.indicador_enviado")
    except Exception as exc:
        # `warning` e nao `error`: o indicador falhar degrada a experiencia e
        # nao quebra nada -- a resposta sai pelo caminho de sempre. So o nome
        # da classe, como no resto do projeto: o texto de uma excecao de
        # terceiro nao e garantia que este repositorio possa dar.
        log.warning("presenca.indicador_falhou", reason=type(exc).__name__)


@asynccontextmanager
async def indicador_de_digitacao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    indicador: IndicadorDePresencaPort,
    apos_segundos: float,
) -> AsyncIterator[None]:
    """Envolve a geracao da resposta: passou de `apos_segundos`, indica.

    `apos_segundos` e parametro obrigatorio e nao lido de `Settings` aqui
    dentro: quem monta o turno e quem conhece a configuracao, e um default
    opcional so para o teste encurtar a espera seria producao carregando um
    parametro que producao nunca passa.

    **Na saida, `cancel()` sem `await`.** Awaitar dentro do `finally` devolve
    o `CancelledError` do escopo de FORA quando o `job_timeout` do ARQ estoura,
    e um `suppress` em volta o engoliria -- justamente o cancelamento que o
    `except asyncio.CancelledError` de `process_message` existe para ver
    chegar, e sem o qual a linha fica em PROCESSING para sempre. Nao awaitar
    nao custa nada: uma tarefa cancelada nao guarda excecao para ninguem
    recolher. A variavel local e a referencia forte que impede a coleta
    prematura ate la.
    """
    provider_message_id = message.provider_message_id
    de = message.recipient_external_id
    if provider_message_id is None or de is None:
        # Sem o wamid da entrada ou sem o numero do canal nao ha requisicao a
        # montar. Sair aqui, e nao descobrir isso depois do sono, evita uma
        # tarefa inteira para nada.
        log.info("presenca.sem_insumo", message_id=str(message.id))
        yield
        return

    tarefa = asyncio.create_task(
        _esperar_e_indicar(
            session_factory,
            message_id=message.id,
            provider_message_id=provider_message_id,
            de=de,
            indicador=indicador,
            apos_segundos=apos_segundos,
        )
    )
    try:
        yield
    finally:
        tarefa.cancel()
```

- [ ] **Step 4: Acrescentar o limiar em `config.py`**

Logo abaixo de `whatsapp_api_base` (linha 134):

```python
    # RN-04.7 (TEC-274). O valor da regra, e configuravel porque os testes
    # precisam injetar centesimos de segundo: tres cenarios a 4 s reais
    # custariam mais de doze segundos por execucao da suite.
    #
    # `float` e nao `int` como os `sweep_*_after_seconds` vizinhos, pela mesma
    # razao -- o teste precisa de 0.05, e um `int` o arredondaria para 0.
    #
    # Nao ha flag para desligar: a porta e o desligamento. Trocar
    # `ctx["indicador"]` por `IndicadorNoop` em `workers/main.py` desliga a
    # feature inteira sem tocar neste numero nem no dominio.
    indicador_de_digitacao_apos_segundos: float = 4.0
```

- [ ] **Step 5: Rodar o teste para ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_de_digitacao.py --tb=short
```

Esperado: 6 passed.

Se um teste falhar sozinho com `ConnectionResetError`, rode o arquivo de novo antes de mudar código — o CLAUDE.md registra ~5% de falha na negociação SSL desta máquina, e uma falha isolada com esse traceback não autoriza conclusão nenhuma.

- [ ] **Step 6: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/outbound/presenca.py src/mobia/app/config.py tests/integration/test_indicador_de_digitacao.py
git commit -m "$(cat <<'EOF'
feat(TEC-274): o relogio do indicador de digitacao, com as guardas no disparo

As guardas de opt-out e atendimento humano rodam DEPOIS do sono, nao
antes: so assim cobrem o lead que pede silencio durante a espera.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: O adaptador da Cloud API

**Files:**
- Modify: `src/mobia/domain/outbound/whatsapp.py` (acrescentar ao fim, depois de `WhatsAppOutbound`)
- Test: `tests/integration/test_whatsapp_outbound.py` (acrescentar ao fim)

**Interfaces:**
- Consumes: `IndicadorDePresencaPort` de `mobia.domain.outbound.presenca` (Task 1) — satisfeito estruturalmente, sem herança.
- Produces: `WhatsAppIndicador(cliente: httpx.AsyncClient | None = None)` com `async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente ao fim de `tests/integration/test_whatsapp_outbound.py`:

```python
async def test_indicador_monta_o_corpo_que_a_meta_exige(session) -> None:
    """O corpo do indicador nao e um envio de mensagem. TEC-274.

    `status: "read"` nao e opcional -- a Meta nao oferece "digitando..."
    isolado, e e por isso que a Emenda E-01 da RN-04.7 registra que o
    indicador marca a fala do lead como lida. Este teste e o unico lugar que
    exercita o corpo: errar uma chave aqui e uma feature que nao funciona em
    producao e passa em todo o resto da suite.
    """
    from mobia.domain.outbound.whatsapp import WhatsAppIndicador

    corpo: dict[str, object] = {}
    indicador = WhatsAppIndicador(cliente=cliente_que_captura(corpo))
    await indicador.indicar_digitacao(provider_message_id="wamid.ABC", de="222222222")

    assert corpo["messaging_product"] == "whatsapp"
    assert corpo["status"] == "read"
    assert corpo["message_id"] == "wamid.ABC"
    assert corpo["typing_indicator"] == {"type": "text"}
    # O indicador nao e mensagem: nenhuma das chaves de envio pode aparecer,
    # ou a Meta recusa o corpo inteiro.
    assert "to" not in corpo
    assert "type" not in corpo


async def test_indicador_usa_o_numero_do_canal_na_url(session) -> None:
    """A URL leva o `phone_number_id`, que mora em `recipient_external_id`."""
    from mobia.domain.outbound.whatsapp import WhatsAppIndicador

    urls: list[str] = []

    def _responde(requisicao: httpx.Request) -> httpx.Response:
        urls.append(str(requisicao.url))
        return httpx.Response(200, json={"success": True})

    indicador = WhatsAppIndicador(
        cliente=httpx.AsyncClient(transport=httpx.MockTransport(_responde))
    )
    await indicador.indicar_digitacao(provider_message_id="wamid.ABC", de="222222222")

    assert urls[0].endswith("/222222222/messages")


async def test_indicador_recusado_nao_levanta(session) -> None:
    """A D6 do desenho: toda falha e a mesma falha, e nenhuma escapa daqui.

    Nao ha reserva a liberar nem retentativa a decidir, entao 4xx e 5xx nao
    precisam ser distinguidos -- ao contrario de `_deliver`, onde o TIPO da
    excecao decide o desfecho do turno.
    """
    from mobia.domain.outbound.whatsapp import WhatsAppIndicador

    indicador = WhatsAppIndicador(
        cliente=cliente_que_responde(httpx.Response(400, json={"error": {"code": 100}}))
    )
    await indicador.indicar_digitacao(provider_message_id="wamid.ABC", de="222222222")
```

- [ ] **Step 2: Rodar o teste para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_whatsapp_outbound.py -k indicador --tb=short
```

Esperado: 3 failed, com `ImportError: cannot import name 'WhatsAppIndicador'`.

- [ ] **Step 3: Escrever `WhatsAppIndicador`**

Acrescente ao fim de `src/mobia/domain/outbound/whatsapp.py`, depois de `_codigo_do_erro`:

```python
class WhatsAppIndicador:
    """O indicador de digitacao da Cloud API. TEC-274, RN-04.7.

    **Nao herda de `GuardedOutbound`**, ao contrario de `WhatsAppOutbound`
    logo acima. Nao ha o que reservar: o indicador nao e mensagem, nao tem
    `kind`, e herdar obrigaria a inventar um kind sintetico numa tabela cuja
    UNIQUE `(message_id, kind)` existe para dedup de MENSAGEM -- um kind
    sintetico ali e o tipo de coisa que ninguem desfaz depois. As guardas de
    opt-out e atendimento humano, que a heranca daria de graca, moram no
    agendador (`domain/outbound/presenca.py`) e rodam no instante do disparo.

    **Mesmo endpoint de `_deliver`, corpo de outra forma.** A Cloud API nao
    tem rota propria para isto: o indicador sai como uma anotacao sobre a
    mensagem RECEBIDA, e por isso exige o `wamid` dela e um `status: "read"`
    que nao e opcional -- enviar o indicador marca a fala do lead como lida.
    Ver a Emenda E-01 da RN-04.7 no SRS.

    **Nenhuma excecao tipada e levantada daqui**, ao contrario de `_deliver`.
    Nao ha reserva a liberar nem retentativa a decidir, e um indicador que
    chega tarde nao vale nada: 4xx e 5xx viram a mesma linha de log. Erro de
    rede propaga cru e o agendador o engole -- ver o `except Exception` de
    `_esperar_e_indicar`.
    """

    def __init__(self, cliente: httpx.AsyncClient | None = None) -> None:
        self._cliente = cliente

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        settings = get_settings()
        url = f"{settings.whatsapp_api_base}/{de}/messages"
        corpo: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": provider_message_id,
            "typing_indicator": {"type": "text"},
        }
        cliente = self._cliente or httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS)

        try:
            resposta = await cliente.post(
                url,
                json=corpo,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            )
        finally:
            if self._cliente is None:
                await cliente.aclose()

        if resposta.status_code >= 400:
            # Nunca `resposta.text`: o corpo do erro da Meta pode ecoar o que
            # foi enviado. So o status, que e o que aponta para a causa.
            log.warning("presenca.recusado", status=resposta.status_code)
```

- [ ] **Step 4: Rodar o teste para ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_whatsapp_outbound.py --tb=short
```

Esperado: todos passam — os 10 que já existiam mais os 3 novos.

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/domain/outbound/whatsapp.py tests/integration/test_whatsapp_outbound.py
git commit -m "$(cat <<'EOF'
feat(TEC-274): o indicador de digitacao sai pela Cloud API

Mesmo POST /messages do envio, corpo de outra forma: status read mais o
wamid da entrada. Nao herda de GuardedOutbound -- nao ha o que reservar.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: A fiação — `process_message`, o worker e os `ctx` dos testes

**Files:**
- Modify: `src/mobia/workers/jobs/process_message.py:251-260`
- Modify: `src/mobia/workers/main.py` (import, e a linha de `ctx` junto de `ctx["outbound"]`)
- Modify: `tests/features/test_reprocessamento_apos_falha.py:22`
- Modify: `tests/integration/test_cancelamento_do_worker.py:55`
- Modify: `tests/integration/test_handoff_por_erro.py:22`
- Modify: `tests/integration/test_sweep_stalled.py:20`
- Test: `tests/integration/test_indicador_de_digitacao.py` (acrescentar ao fim)

**Interfaces:**
- Consumes: `indicador_de_digitacao`, `IndicadorNoop` (Task 1); `WhatsAppIndicador` (Task 2); `get_settings()` — já importado em `process_message.py`.
- Produces: a chave `ctx["indicador"]`, obrigatória em todo `ctx` que rode `process_message`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente ao fim de `tests/integration/test_indicador_de_digitacao.py`:

```python
async def test_turno_lento_dispara_o_indicador_de_ponta_a_ponta(
    session,
    semear_entrada,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    monkeypatch,
    caches_de_cliente_limpos,
    banco_limpo,
) -> None:
    """A fiacao inteira: `process_message` -> gerente de contexto -> porta.

    O limiar vem do ambiente e nao do argumento, porque o que este teste
    exercita e justamente a leitura de `Settings` que `process_message` faz --
    os testes acima ja cobrem o relogio com o limiar injetado.
    """
    from mobia.app.config import get_settings
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.workers.jobs.process_message import process_message

    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "0.02")
    get_settings.cache_clear()

    class ClassificadorLento:
        """Delega para o fake, com uma pausa na frente do relogio."""

        def __init__(self, interno) -> None:
            self._interno = interno

        def __getattr__(self, nome: str):
            return getattr(self._interno, nome)

        async def classificar(self, *args, **kwargs):
            await asyncio.sleep(DEVAGAR)
            return await self._interno.classificar(*args, **kwargs)

    linha = await semear_entrada(session)
    espiao = IndicadorEspiao()
    ctx = {
        "session_factory": get_sessionmaker(),
        "outbound": outbound_fake(get_sessionmaker()),
        "classificador": ClassificadorLento(classificador_fake()),
        "resumidor": resumidor_fake(),
        "contador": contador_fake(),
        "moderador": moderador_fake(),
        "agendador": AgendadorNoop(),
        "indicador": espiao,
    }

    await process_message(ctx, str(linha.id))

    assert len(espiao.chamadas) == 1
```

**Antes de escrever isto, confira os nomes das fixtures** — `classificador_fake`, `outbound_fake`, `resumidor_fake`, `contador_fake`, `moderador_fake` são fábricas em `tests/conftest.py` e algumas podem ser classes importadas direto (`from conftest import ClassificadorFake, ...`, como em `test_handoff_por_erro.py:7`). Use a forma que aquele arquivo usa; o que importa é que o `ctx` tenha as sete chaves antigas mais `indicador`.

- [ ] **Step 2: Rodar o teste para ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_de_digitacao.py -k ponta_a_ponta --tb=short
```

Esperado: FAIL — `espiao.chamadas` fica vazio, porque `process_message` ainda não abre o gerente de contexto.

- [ ] **Step 3: Abrir o gerente de contexto em `process_message`**

Em `src/mobia/workers/jobs/process_message.py`, acrescente ao bloco de imports:

```python
from mobia.domain.outbound.presenca import indicador_de_digitacao
```

E troque a chamada a `executar_turno` (linha 251) por:

```python
        # TEC-274, RN-04.7. O relogio mede o turno INTEIRO -- contexto,
        # resumo, modelo e as duas moderacoes --, e nao so a chamada ao
        # classificador: e o silencio que o lead percebe. Um turno com tres
        # segundos de contexto e tres e meio de modelo nao ultrapassa quatro
        # em nenhuma parte e deixa o lead seis segundos e meio no vazio.
        #
        # Mora AQUI e nao dentro de `executar_turno` porque as guardas baratas
        # ficam no topo daquela funcao e a primeira entrega mil e trezentas
        # linhas abaixo: o `async with` la dentro reindentaria cerca de duas
        # mil linhas, e a protecao que a posicao daria e reproduzida -- melhor
        # -- pela conferencia no disparo. Ver as D2 e D3 do desenho.
        async with indicador_de_digitacao(
            session_factory,
            message=linha,
            indicador=ctx["indicador"],
            apos_segundos=get_settings().indicador_de_digitacao_apos_segundos,
        ):
            resultado = await executar_turno(
                session_factory,
                message=linha,
                classificador=ctx["classificador"],
                resumidor=ctx["resumidor"],
                contador=ctx["contador"],
                outbound=outbound,
                moderador=ctx["moderador"],
                agendador=agendador,
            )
```

O comentário acima está sem acento de propósito, pela convenção de `src/`. Mantenha assim.

Acrescente também, junto do bloco que lê `agendador` no topo da função:

```python
    # `ctx[...]` direto pela mesma razao que `agendador` logo acima: um
    # `ctx.get("indicador") or IndicadorNoop()` trocaria a porta real por um
    # duble dentro de producao, e o sintoma de um `startup` que deixasse de
    # popular a chave seria nenhum indicador, nunca, sem log e sem erro.
```

(O valor em si é lido inline no `async with`; este comentário explica por que não há fallback.)

- [ ] **Step 4: Ligar a porta no `startup` do worker**

Em `src/mobia/workers/main.py`, no import de `whatsapp`:

```python
from mobia.domain.outbound.whatsapp import WhatsAppIndicador, WhatsAppOutbound
```

E logo abaixo de `ctx["outbound"] = WhatsAppOutbound(session_factory)`:

```python
    # TEC-274. Sem `session_factory`: as guardas do indicador moram no
    # agendador (`domain/outbound/presenca.py`), nao no adaptador. A guarda de
    # `WHATSAPP_ACCESS_TOKEN` logo acima ja cobre os dois -- sem token, este
    # tambem levaria 401.
    ctx["indicador"] = WhatsAppIndicador()
```

- [ ] **Step 5: Acrescentar a chave nos quatro `ctx` de teste**

Em cada um destes, acrescente `"indicador": IndicadorNoop(),` ao dicionário, com `from mobia.domain.outbound.presenca import IndicadorNoop` no topo do arquivo:

- `tests/features/test_reprocessamento_apos_falha.py:22` — `_ctx`
- `tests/integration/test_cancelamento_do_worker.py:55` — `_ctx`
- `tests/integration/test_handoff_por_erro.py:22` — `_ctx`
- `tests/integration/test_sweep_stalled.py:20` — `_ctx_do_turno`

`IndicadorNoop` e não um espião porque nenhum desses arquivos afirma nada sobre o indicador: eles precisam da chave para o `ctx` ficar completo, e um espião ali convidaria alguém a escrever a asserção no lugar errado.

- [ ] **Step 6: Rodar os testes tocados**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_indicador_de_digitacao.py tests/integration/test_handoff_por_erro.py tests/integration/test_cancelamento_do_worker.py tests/integration/test_sweep_stalled.py tests/features/test_reprocessamento_apos_falha.py --tb=short
```

Esperado: todos passam.

`test_cancelamento_do_worker.py` é o que mais importa aqui: ele afirma que o `CancelledError` chega inteiro a `process_message`. Se ele reprovar, o `finally` do gerente de contexto está engolindo o cancelamento — releia a D5 do desenho e confira que não há `await tarefa` depois do `cancel()`.

- [ ] **Step 7: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add src/mobia/workers tests/
git commit -m "$(cat <<'EOF'
feat(TEC-274): o turno passa a indicar digitacao quando demora

O gerente de contexto envolve executar_turno em process_message, que
nao muda nenhuma linha. O worker liga a porta real no startup.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: A emenda ao SRS, e a suíte inteira

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (item aninhado abaixo da RN-04.7, linha 195)

**Interfaces:**
- Consumes: nada. Produces: nada. É a task de fechamento.

- [ ] **Step 1: Acrescentar a Emenda E-01 da RN-04.7**

A RN-04.7 está na linha 195 e **não tem emenda nenhuma hoje** — a card avisa disso por extenso, e é verdade. Esta é a primeira. Acrescente como item aninhado logo abaixo, **sem reescrever o texto de 22/08/2026**, copiando o texto da seção "Emendas ao SRS" do desenho:

```markdown
  - **Emenda E-01 (TEC-274, 19/09/2026):** o indicador desta regra **não existe isolado na Cloud API da Meta**. Ele sai no mesmo `POST /{phone_number_id}/messages` do envio de mensagem, num corpo que exige `"status": "read"` e o `wamid` da mensagem de entrada — ou seja, **enviar o indicador marca a fala do lead como lida**, e não há variante sem esse efeito. A regra passa a valer com ele: um turno que ultrapassa os 4 s dá tique azul; um turno rápido não dá. A regra também ganha a duração que o canal impõe — o indicador desaparece após 25 s, e a TEC-274 não o renova (L1 do desenho). E os "4 s" passam a ser medidos do início do processamento da mensagem até a primeira entrega, e não da chamada ao modelo: é o silêncio que o lead percebe, e um turno com três segundos de montagem de contexto e três e meio de modelo deixa o lead seis segundos e meio no vazio sem que nenhuma parte isolada ultrapasse o limiar. Ver as D1, D2 e a L1 do desenho em `docs/superpowers/specs/2026-09-19-tec-274-indicador-de-digitacao-design.md`.
```

Indentação de dois espaços, como as emendas vizinhas da RN-04.2 e da RN-04.5. Prosa em `docs/` leva acento.

- [ ] **Step 2: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Reconfira cada `ALTERADO` e `VIZINHO` que ela listar, e todo `FALSO` — esta é a única marca que afirma em vez de suspeitar. Não é gate e não reprova nada; o julgamento é seu. Se ela apontar `PROSA` citando `whatsapp.py` ou `process_message.py` por linha, confira se a citação ainda aponta o que diz.

- [ ] **Step 3: Rodar a suíte inteira, UMA vez**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Guarde o hash junto com o resultado.

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando** — o Postgres caiu sob o paralelismo. `docker compose restart postgres` e rode por blocos:

```bash
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration --tb=short
./.venv/Scripts/python.exe -m pytest tests/features --tb=short
```

Se dezenas de testes falharem com `relation ... does not exist`, são os bancos dos workers com o carimbo adiantado, não a sua mudança — o CLAUDE.md descreve o conserto por banco. Se a primeira execução falhar de outra forma, repita sobre a mesma árvore antes de culpar o que você escreveu: é a única coisa que separa flake de regressão.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md
git commit -m "$(cat <<'EOF'
docs(TEC-274): a RN-04.7 ganha a primeira emenda

O indicador implica recibo de leitura, expira em 25 s, e os 4 s passam a
ser medidos do inicio do processamento ate a primeira entrega.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push e PR**

```bash
git push -u origin feat/tec-274-indicador-de-digitacao
gh pr create --base main --title "TEC-274: indicador de digitacao quando a resposta passa de 4 segundos" --body "..."
```

O corpo do PR termina com `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

**O trabalho não termina aqui.** Depois do PR, comente na card e mova-a para **Em análise** (não "Feito" — quem mergeia é que fecha). O comentário registra o que some se ficar só no PR:

- as divergências em relação ao texto da card: o endpoint **não** é próprio (a card supõe que seja), o recibo de leitura vem junto e é decisão de produto aceita, e o relógio mede o turno inteiro e não a geração;
- a Emenda E-01 da RN-04.7, nomeada — e o fato de que ela é a primeira, apesar do título da TEC-258;
- as quatro lacunas (L1 a L4 do desenho), com a consequência prática de cada uma dita sem rodeio: em especial que o indicador **some aos 25 s** e ninguém o renova, e que o tique azul passa a depender da latência.

---

## Auto-revisão do plano

**Cobertura do spec.** D1 → Task 3 (o `async with` em volta do turno inteiro). D2 → Task 3 Step 3. D3 → Task 1 Step 3 (`_esperar_e_indicar`) e Task 1 Step 1 (o teste do opt-out concorrente). D4 → Task 1 Step 3 e Task 2 Step 3. D5 → Task 1 Step 3 (`finally: tarefa.cancel()`) e Task 3 Step 6 (o teste de cancelamento como sentinela). D6 → Task 1 Step 3 (`except Exception`) e Task 2 Step 1 (o 400 que não levanta). D7 → Task 1 Step 4. Tabela de arquivos → Tasks 1-4. Testes do spec → Task 1 (cinco), Task 2 (o corpo), Task 3 (ponta a ponta). L1-L4 → Task 4 Step 5, no comentário da card. Emenda → Task 4 Step 1.

**Sem lacuna encontrada.** Os seis testes do agendador cobrem os três cenários do Gherkin mais os dois que o desenho acrescenta, mais o caso sem `wamid`, que o desenho não previa e a tipagem obrigou a decidir.

**Consistência de nomes.** `IndicadorDePresencaPort`, `IndicadorNoop`, `indicador_de_digitacao`, `_esperar_e_indicar`, `WhatsAppIndicador`, `indicar_digitacao(*, provider_message_id, de)`, `indicador_de_digitacao_apos_segundos`, `ctx["indicador"]` — conferidos entre as quatro tasks e contra o desenho.

**Um ponto aberto que o executor resolve na hora:** os nomes das fixtures de dublê no teste de ponta a ponta (Task 3, Step 1). O plano diz para conferir em `tests/conftest.py` e seguir a forma que `test_handoff_por_erro.py` usa, em vez de chutar.

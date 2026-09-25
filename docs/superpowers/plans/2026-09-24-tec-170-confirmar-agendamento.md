# TEC-170 — Confirmar o agendamento e avisar lead e corretor: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Depois que um agendamento vira `CONFIRMADO`, avisar o lead, avisar o corretor por e-mail e criar o evento no Google Calendar do corretor — três passos independentes, idempotentes, sem que nenhum desfaça o agendamento.

**Architecture:** Textos e aviso montados num módulo puro (`mensagens.py`); o calendário é uma porta com adaptador Google sobre `httpx` e um Noop (a flag é a credencial vazia); `avisar_confirmacao` em `confirmacao.py` faz os três passos com sessões curtas e três colunas novas como marca de feito; um job ARQ fino e uma porta de enfileiramento, sem chamador de produção ainda.

**Tech Stack:** Python 3.13, SQLAlchemy async + asyncpg, Alembic (à mão), ARQ, httpx, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md`

## Global Constraints

- Texto que o lead recebe: português **com acento**, como constante `TEXTO_...` de módulo registrada em `tests/unit/literais_ao_lead.py`. Nenhum texto ao lead contém as frases de `PROMESSAS_BANIDAS` (`tests/unit/test_promessa_ao_lead.py`) — em especial não diz que o corretor "foi avisado" nem que "entra em contato".
- Comentários e docstrings em `src/`, `tests/` e migrations: português **sem acento**. Prosa em `docs/`: com acento.
- `agora` entra como parâmetro com fuso; data e hora ao lead por `data_e_hora_absolutas` (fuso da imobiliária).
- Nenhum passo escreve em `agendamentos.status`. O agendamento continua `CONFIRMADO` em qualquer falha.
- Alerta = `log.error` com nome estável: `agendamento.calendario_falhou`, `agendamento.aviso_ao_corretor_falhou`, `agendamento.aviso_ao_lead_falhou`. Nunca logar corpo de resposta do Google nem credencial.
- A flag do calendário é `Settings.google_calendar_refresh_token` vazio → `CalendarioNoop`, zero chamadas, um aviso na subida do worker (`agendamento.calendario_desligado`).
- Sem biblioteca nova: Google via `httpx`, cliente injetável (molde de `WhatsAppTemplate`).
- Migrations à mão; `ex_agendamentos_sem_sobreposicao` nunca é tocada.
- Os três gates antes de todo commit: `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`, `./.venv/Scripts/python.exe -m mypy`.
- Commit: `tipo(TEC-170): o que passou a ser verdade`, sem acento no assunto, terminando com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. `git add` com caminhos explícitos; `.superpowers/` nunca entra.
- Citação de código em `.md` por âncora (`arquivo.py::Nome`), nunca por número de linha.

## Review Focus

1. **Reexecução do job depois de o lead escrever de novo** — não pode mandar a confirmação duas vezes (é o motivo de `lead_avisado_em`). Teste em Task 3.
2. **Guarda do outbound recusa (opt-out / atendimento humano)** — `send` devolve `False`; `lead_avisado_em` fica nulo, nada levanta, os outros passos rodam. Teste em Task 3.
3. **Visita sem imóvel** (`imovel_id` nulo) — sai sem endereço, sem `None` no texto. Teste em Task 1.
4. **Resposta do Google 200 sem `id`, ou token sem `access_token`** — vira `FalhaDeCalendario`, não `KeyError`. Teste em Task 2.
5. **Credencial parcial** (refresh token sem client id/secret) — o worker recusa subir com `ConfiguracaoInsegura`, em vez de falhar em todo agendamento. Teste em Task 4.

---

### Task 1: Os textos ao lead e o aviso ao corretor

**Files:**
- Create: `src/mobia/domain/agendamento/mensagens.py`
- Modify: `tests/unit/literais_ao_lead.py` (import + 3 entradas em `LITERAIS_AO_LEAD`)
- Modify: `tests/unit/test_literais_ao_lead.py` (tamanho esperado 28 → 31; se o número atual não for 28, some 3 ao atual)
- Test: `tests/unit/test_mensagens_de_confirmacao.py`

**Interfaces:**
- Produces:
  - `TEXTO_DA_CONFIRMACAO_DE_VISITA`, `TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL`, `TEXTO_DA_CONFIRMACAO_DE_REUNIAO` (str, com `{quando}`, `{corretor}` e, no primeiro, `{endereco}`)
  - `endereco_de(imovel: Imovel) -> str`
  - `texto_ao_lead(*, tipo: str, inicio: datetime, corretor: str, imovel: Imovel | None) -> str`
  - `aviso_ao_corretor(*, tipo: str, inicio: datetime, corretor: str, imovel: Imovel | None, channel: str, conversation_key: str, link: str) -> Aviso`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_mensagens_de_confirmacao.py`:

```python
"""Os textos da confirmacao de agendamento, testados. TEC-170, D3 e D4 do desenho.

Puro: o `Imovel` e transiente. 27/08/2026 e uma quinta-feira.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from mobia.domain.agendamento.mensagens import (
    aviso_ao_corretor,
    endereco_de,
    texto_ao_lead,
)
from mobia.domain.catalogo.models import Imovel

SP = ZoneInfo("America/Sao_Paulo")
QUINTA_15H = datetime(2026, 8, 27, 15, 0, tzinfo=SP)


def _imovel() -> Imovel:
    return Imovel(
        id=uuid.uuid4(),
        codigo="AP-123",
        titulo="Apartamento 3 quartos",
        bairro="Moema",
        cidade="São Paulo",
        uf="SP",
    )


def test_endereco_usa_o_que_o_catalogo_tem() -> None:
    assert endereco_de(_imovel()) == "Apartamento 3 quartos (cód. AP-123) — Moema, São Paulo/SP"


def test_visita_com_imovel_leva_data_endereco_e_corretor() -> None:
    texto = texto_ao_lead(
        tipo="VISITA_PRESENCIAL", inicio=QUINTA_15H, corretor="Paula", imovel=_imovel()
    )
    assert "quinta-feira, 27 de agosto, às 15h" in texto
    assert "Moema, São Paulo/SP" in texto
    assert "Paula" in texto


def test_visita_sem_imovel_nao_tem_endereco_nem_none() -> None:
    texto = texto_ao_lead(tipo="VISITA_PRESENCIAL", inicio=QUINTA_15H, corretor="Paula", imovel=None)
    assert "quinta-feira, 27 de agosto, às 15h" in texto
    assert "Paula" in texto
    assert "None" not in texto
    assert "cód." not in texto


def test_reuniao_remota_diz_que_e_remota_e_nao_da_endereco() -> None:
    texto = texto_ao_lead(
        tipo="REUNIAO_REMOTA", inicio=QUINTA_15H, corretor="Paula", imovel=_imovel()
    )
    assert "remota" in texto
    assert "Moema" not in texto
    assert "Paula" in texto


def test_hora_vem_no_fuso_local_mesmo_com_inicio_em_utc() -> None:
    inicio_utc = QUINTA_15H.astimezone(ZoneInfo("UTC"))
    texto = texto_ao_lead(tipo="VISITA_PRESENCIAL", inicio=inicio_utc, corretor="Paula", imovel=None)
    assert "às 15h" in texto


def test_aviso_ao_corretor_leva_os_dados_mais_o_lead_e_o_link() -> None:
    aviso = aviso_ao_corretor(
        tipo="VISITA_PRESENCIAL",
        inicio=QUINTA_15H,
        corretor="Paula",
        imovel=_imovel(),
        channel="whatsapp",
        conversation_key="5511911111111",
        link="https://painel/conversas/whatsapp/5511911111111",
    )
    assert "quinta-feira, 27 de agosto, às 15h" in aviso.assunto
    for trecho in (
        "quinta-feira, 27 de agosto, às 15h",
        "Moema, São Paulo/SP",
        "Paula",
        "whatsapp",
        "5511911111111",
        "https://painel/conversas/whatsapp/5511911111111",
    ):
        assert trecho in aviso.corpo
    assert aviso.etiqueta == "agendamento-confirmado"
    assert aviso.prioridade == "NORMAL"
    assert aviso.link == "https://painel/conversas/whatsapp/5511911111111"


def test_aviso_de_reuniao_remota_nao_tem_linha_de_imovel() -> None:
    aviso = aviso_ao_corretor(
        tipo="REUNIAO_REMOTA",
        inicio=QUINTA_15H,
        corretor="Paula",
        imovel=None,
        channel="web",
        conversation_key="sessao-1",
        link="https://painel/x",
    )
    assert "Reunião remota" in aviso.assunto
    assert "Imóvel" not in aviso.corpo
```

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_mensagens_de_confirmacao.py -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'mobia.domain.agendamento.mensagens'`

- [ ] **Step 3: Implement**

`src/mobia/domain/agendamento/mensagens.py`:

```python
"""O que o lead e o corretor leem quando o agendamento e confirmado. TEC-170.

Puro: nao toca banco nem rede. `confirmacao.py` carrega o agendamento e chama
estas funcoes. Ver docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md.
"""

from datetime import datetime

from mobia.domain.agendamento.data_falada import data_e_hora_absolutas
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.catalogo.models import Imovel
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho
from mobia.domain.notificacao.mensagem import Aviso

# Texto ao lead: com acento (TEC-267). Nenhum dos tres diz que o corretor "foi
# avisado": o e-mail aceito pelo servidor nao e o e-mail lido (TEC-286).
TEXTO_DA_CONFIRMACAO_DE_VISITA = (
    "Sua visita está confirmada para {quando}, em {endereco}. Quem vai te receber é {corretor}."
)
# Visita com `imovel_id` nulo: o schema permite, e um endereco inventado seria
# pior que nenhum.
TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL = (
    "Sua visita está confirmada para {quando}. Quem vai te receber é {corretor}."
)
TEXTO_DA_CONFIRMACAO_DE_REUNIAO = (
    "Sua reunião remota está confirmada para {quando}, com {corretor}."
)


def endereco_de(imovel: Imovel) -> str:
    """O endereco que o catalogo permite dar. D4 do desenho.

    `Imovel` nao tem logradouro, numero nem CEP: titulo e codigo identificam o
    imovel, e bairro, cidade e UF o situam. O numero exato o corretor passa.
    """
    return f"{imovel.titulo} (cód. {imovel.codigo}) — {imovel.bairro}, {imovel.cidade}/{imovel.uf}"


def texto_ao_lead(*, tipo: str, inicio: datetime, corretor: str, imovel: Imovel | None) -> str:
    quando = data_e_hora_absolutas(inicio)
    if tipo == TipoDeCompromisso.REUNIAO_REMOTA:
        return TEXTO_DA_CONFIRMACAO_DE_REUNIAO.format(quando=quando, corretor=corretor)
    if imovel is None:
        return TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL.format(quando=quando, corretor=corretor)
    return TEXTO_DA_CONFIRMACAO_DE_VISITA.format(
        quando=quando, endereco=endereco_de(imovel), corretor=corretor
    )


def aviso_ao_corretor(
    *,
    tipo: str,
    inicio: datetime,
    corretor: str,
    imovel: Imovel | None,
    channel: str,
    conversation_key: str,
    link: str,
) -> Aviso:
    """O e-mail ao corretor: os dados do lead mais a identificacao dele. D3.

    Etiqueta e prioridade vem do vocabulario do handoff para este fato, que
    ja existe -- nenhum handoff e aberto (o desenho explica por que).
    """
    quando = data_e_hora_absolutas(inicio)
    remota = tipo == TipoDeCompromisso.REUNIAO_REMOTA
    assunto = f"{'Reunião remota' if remota else 'Visita'} confirmada: {quando}"
    linhas = [
        f"Quando: {quando}",
        f"Tipo: {'Reunião remota' if remota else 'Visita presencial'}",
        f"Corretor: {corretor}",
    ]
    if not remota and imovel is not None:
        linhas.append(f"Imóvel: {endereco_de(imovel)}")
    linhas.append(f"Lead: {channel} {conversation_key}")
    linhas.append(f"Conversa completa: {link}")
    gatilho = Gatilho.AGENDAMENTO_CONFIRMADO
    return Aviso(
        assunto=assunto,
        corpo="\n".join(linhas),
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=str(PRIORIDADE_DE[gatilho]),
        link=link,
    )
```

The corretor's e-mail body is not lead text: it is not registered in `literais_ao_lead.py`.

- [ ] **Step 4: Register the three lead literals**

In `tests/unit/literais_ao_lead.py`, import the three `TEXTO_DA_CONFIRMACAO_*` from `mobia.domain.agendamento.mensagens` (keep imports sorted as ruff wants) and add them to `LITERAIS_AO_LEAD`. In `tests/unit/test_literais_ao_lead.py`, raise the expected length by 3.

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_mensagens_de_confirmacao.py tests/unit/test_literais_ao_lead.py tests/unit/test_promessa_ao_lead.py tests/unit/test_acento_no_texto_ao_lead.py -v --tb=short`
Expected: PASS. If the accent guard flags a word, fix the literal (it is lead text and must be accented), never the guard.

- [ ] **Step 6: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agendamento/mensagens.py tests/unit/test_mensagens_de_confirmacao.py tests/unit/literais_ao_lead.py tests/unit/test_literais_ao_lead.py
git commit -m "feat(TEC-170): os textos da confirmacao ao lead e o aviso ao corretor

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A porta do calendário e o adaptador Google

**Files:**
- Create: `src/mobia/domain/agendamento/calendario.py`
- Modify: `src/mobia/app/config.py` (4 campos)
- Modify: `.env.example` (4 variáveis, comentadas como as do CRM)
- Test: `tests/unit/test_google_calendar.py`

**Interfaces:**
- Produces:
  - `FalhaDeCalendario(RuntimeError)`
  - `CalendarioPort(Protocol)`: `async criar_evento(self, *, inicio: datetime, fim: datetime, titulo: str, descricao: str, convidado: str) -> str | None`
  - `CalendarioNoop` (devolve `None`, nenhuma chamada)
  - `GoogleCalendar(cliente: httpx.AsyncClient | None = None)`
  - `Settings.google_calendar_client_id: str = ""`, `google_calendar_client_secret: str = ""`, `google_calendar_refresh_token: str = ""`, `google_calendar_id: str = "primary"`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_google_calendar.py`:

```python
"""O adaptador do Google Calendar contra um transporte falso. TEC-170, D5.

Nenhuma chamada sai da maquina: `httpx.MockTransport` responde as duas URLs.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mobia.app.config import get_settings
from mobia.domain.agendamento.calendario import (
    CalendarioNoop,
    FalhaDeCalendario,
    GoogleCalendar,
)

SP = ZoneInfo("America/Sao_Paulo")
INICIO = datetime(2026, 8, 27, 15, 0, tzinfo=SP)
FIM = datetime(2026, 8, 27, 16, 0, tzinfo=SP)


@pytest.fixture(autouse=True)
def _credenciais(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "segredo")
    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "agenda@imobiliaria.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _cliente(responder) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    pedidos: list[httpx.Request] = []

    def _handler(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return responder(pedido)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler)), pedidos


def _ok(pedido: httpx.Request) -> httpx.Response:
    if pedido.url.host == "oauth2.googleapis.com":
        return httpx.Response(200, json={"access_token": "tok"})
    return httpx.Response(200, json={"id": "evento-1"})


async def _criar(calendario) -> str | None:
    return await calendario.criar_evento(
        inicio=INICIO, fim=FIM, titulo="Visita", descricao="Lead x", convidado="paula@x.com"
    )


async def test_troca_o_token_e_cria_o_evento_com_convite() -> None:
    cliente, pedidos = _cliente(_ok)
    assert await _criar(GoogleCalendar(cliente)) == "evento-1"

    token, evento = pedidos
    assert token.url == httpx.URL("https://oauth2.googleapis.com/token")
    form = dict(httpx.QueryParams(token.content.decode()))
    assert form == {
        "client_id": "cid",
        "client_secret": "segredo",
        "refresh_token": "refresh",
        "grant_type": "refresh_token",
    }

    assert evento.url.path == "/calendar/v3/calendars/agenda%40imobiliaria.com/events"
    assert evento.url.params["sendUpdates"] == "all"
    assert evento.headers["Authorization"] == "Bearer tok"
    corpo = json.loads(evento.content)
    assert corpo["summary"] == "Visita"
    assert corpo["description"] == "Lead x"
    assert corpo["attendees"] == [{"email": "paula@x.com"}]
    assert corpo["start"] == {"dateTime": INICIO.isoformat(), "timeZone": "America/Sao_Paulo"}
    assert corpo["end"] == {"dateTime": FIM.isoformat(), "timeZone": "America/Sao_Paulo"}


async def test_5xx_vira_falha_de_calendario() -> None:
    def _responder(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(503, text="segredo que nao pode ir para o log")

    cliente, _ = _cliente(_responder)
    with pytest.raises(FalhaDeCalendario) as erro:
        await _criar(GoogleCalendar(cliente))
    assert "segredo" not in str(erro.value)


async def test_token_recusado_vira_falha_e_nao_cria_evento() -> None:
    cliente, pedidos = _cliente(lambda pedido: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(FalhaDeCalendario):
        await _criar(GoogleCalendar(cliente))
    assert len(pedidos) == 1


async def test_erro_de_rede_vira_falha_de_calendario() -> None:
    def _responder(pedido: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede", request=pedido)

    cliente, _ = _cliente(_responder)
    with pytest.raises(FalhaDeCalendario):
        await _criar(GoogleCalendar(cliente))


async def test_resposta_sem_id_ou_sem_token_vira_falha_e_nao_keyerror() -> None:
    def _sem_id(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, json={})

    cliente, _ = _cliente(_sem_id)
    with pytest.raises(FalhaDeCalendario):
        await _criar(GoogleCalendar(cliente))

    cliente, _ = _cliente(lambda pedido: httpx.Response(200, json={}))
    with pytest.raises(FalhaDeCalendario):
        await _criar(GoogleCalendar(cliente))


async def test_noop_nao_chama_nada_e_devolve_none() -> None:
    assert await _criar(CalendarioNoop()) is None
```

Before relying on `monkeypatch.setenv` + `get_settings.cache_clear()`, check how other unit tests override `Settings` (grep `cache_clear` in `tests/`); use the repo's established way if it differs.

- [ ] **Step 2: Run to verify failure**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_google_calendar.py -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'mobia.domain.agendamento.calendario'`

- [ ] **Step 3: Add the settings**

In `src/mobia/app/config.py`, next to `crm_webhook_url`, with a comment in the same style (why, not what):

```python
    # TEC-170, D5. O refresh token OAuth da conta Google da imobiliaria que
    # ORGANIZA os eventos e convida o corretor. Vazio DESLIGA a integracao --
    # a convencao de `crm_webhook_url` --: o worker sobe com `CalendarioNoop`
    # e um aviso. Com o token preenchido, id e segredo do cliente passam a ser
    # obrigatorios (guarda no `startup` do worker).
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    # A agenda da conta organizadora onde o evento nasce. `primary` e a
    # principal dela; o corretor recebe o evento por convite, nao por escrita
    # direta na agenda dele.
    google_calendar_id: str = "primary"
```

In `.env.example`, after the CRM block, add the four variables empty (`GOOGLE_CALENDAR_ID=primary`), with a comment saying empty refresh token turns the integration off.

- [ ] **Step 4: Implement the port and adapters**

`src/mobia/domain/agendamento/calendario.py`:

```python
"""O evento na agenda do corretor. TEC-170, D5 do desenho.

Uma conta Google da imobiliaria ORGANIZA o evento e convida o corretor: o
Google envia o convite e o evento aparece na agenda dele, qualquer que seja o
provedor do e-mail -- sem Workspace nem delegacao. `httpx` puro, com cliente
injetavel, no molde de `WhatsAppTemplate`: nenhuma biblioteca Google.
"""

from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from mobia.app.config import get_settings

URL_DO_TOKEN = "https://oauth2.googleapis.com/token"
URL_DOS_EVENTOS = "https://www.googleapis.com/calendar/v3/calendars/{agenda}/events"
SEGUNDOS_DE_TIMEOUT = 15.0


class FalhaDeCalendario(RuntimeError):
    """O Google nao criou o evento.

    Mesmo papel de `FalhaDeCanal`: `avisar_confirmacao` captura so esta, e um
    defeito de programacao sobe. **A mensagem nunca carrega o corpo da
    resposta** -- a do endpoint de token pode ecoar credencial, e a mensagem
    vai para o log.
    """


class CalendarioPort(Protocol):
    async def criar_evento(
        self, *, inicio: datetime, fim: datetime, titulo: str, descricao: str, convidado: str
    ) -> str | None: ...


class CalendarioNoop:
    """A integracao desligada: nenhuma chamada, nenhum evento (`None`)."""

    async def criar_evento(
        self, *, inicio: datetime, fim: datetime, titulo: str, descricao: str, convidado: str
    ) -> str | None:
        return None


class GoogleCalendar:
    """Cria o evento na agenda da conta organizadora, com o corretor convidado."""

    def __init__(self, cliente: httpx.AsyncClient | None = None) -> None:
        self._cliente = cliente

    async def criar_evento(
        self, *, inicio: datetime, fim: datetime, titulo: str, descricao: str, convidado: str
    ) -> str | None:
        configuracao = get_settings()
        cliente = self._cliente or httpx.AsyncClient(timeout=SEGUNDOS_DE_TIMEOUT)
        try:
            token = await self._access_token(cliente)
            corpo: dict[str, Any] = {
                "summary": titulo,
                "description": descricao,
                "start": {"dateTime": inicio.isoformat(), "timeZone": configuracao.followup_fuso},
                "end": {"dateTime": fim.isoformat(), "timeZone": configuracao.followup_fuso},
                "attendees": [{"email": convidado}],
            }
            resposta = await cliente.post(
                URL_DOS_EVENTOS.format(agenda=quote(configuracao.google_calendar_id, safe="")),
                params={"sendUpdates": "all"},
                json=corpo,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resposta.status_code >= 400:
                raise FalhaDeCalendario(f"Google recusou o evento: HTTP {resposta.status_code}")
            identificador = _campo(resposta, "id")
        except httpx.HTTPError as erro:
            raise FalhaDeCalendario(f"Google inacessivel: {type(erro).__name__}") from erro
        finally:
            if self._cliente is None:
                await cliente.aclose()
        return identificador

    @staticmethod
    async def _access_token(cliente: httpx.AsyncClient) -> str:
        configuracao = get_settings()
        resposta = await cliente.post(
            URL_DO_TOKEN,
            data={
                "client_id": configuracao.google_calendar_client_id,
                "client_secret": configuracao.google_calendar_client_secret,
                "refresh_token": configuracao.google_calendar_refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resposta.status_code >= 400:
            raise FalhaDeCalendario(f"Google recusou o token: HTTP {resposta.status_code}")
        return _campo(resposta, "access_token")


def _campo(resposta: httpx.Response, nome: str) -> str:
    # 200 sem o campo, ou corpo que nao e JSON, e falha do Google -- nao um
    # KeyError que subiria como defeito de programacao.
    try:
        valor = resposta.json()[nome]
    except (ValueError, KeyError, TypeError) as erro:
        raise FalhaDeCalendario(f"Google respondeu sem `{nome}`") from erro
    if not isinstance(valor, str) or not valor:
        raise FalhaDeCalendario(f"Google respondeu sem `{nome}`")
    return valor
```

- [ ] **Step 5: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_google_calendar.py -v --tb=short`
Expected: PASS. Then `./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q` (the new settings must not break config tests).

- [ ] **Step 6: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agendamento/calendario.py src/mobia/app/config.py .env.example tests/unit/test_google_calendar.py
git commit -m "feat(TEC-170): a porta do calendario e o adaptador Google por organizador que convida

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Migration 0046 e `avisar_confirmacao`

**Files:**
- Create: `alembic/versions/0046_avisos_do_agendamento.py`
- Modify: `src/mobia/domain/agendamento/models.py` (3 colunas)
- Create: `src/mobia/domain/agendamento/confirmacao.py`
- Test: `tests/integration/test_confirmacao_do_agendamento.py`

**Interfaces:**
- Consumes: `texto_ao_lead`, `aviso_ao_corretor` (Task 1); `CalendarioPort`, `FalhaDeCalendario` (Task 2); `CanalDeNotificacaoPort`, `FalhaDeCanal` (`domain/notificacao/canais.py`); `OutboundPort`; `link_da_transcricao` (`domain/handoff/resumo.py`)
- Produces:
  - `Agendamento.calendar_event_id: Mapped[str | None]` (`String(120)`), `corretor_avisado_em`, `lead_avisado_em: Mapped[datetime | None]`
  - `AVISAR_CONFIRMACAO_JOB = "avisar_confirmacao"`, `KIND_DA_CONFIRMACAO = "confirmacao_de_agendamento"`
  - `async avisar_confirmacao(session_factory, *, agendamento_id: uuid.UUID, outbound: OutboundPort, email: CanalDeNotificacaoPort, calendario: CalendarioPort, agora: datetime) -> None`

Requires `docker compose` up.

- [ ] **Step 1: Migration and model**

`alembic/versions/0046_avisos_do_agendamento.py` (revision `0046`, down `0044`'s successor `0045`):

```python
"""o registro de cada aviso da confirmacao do agendamento

TEC-170, D2 e D7. Tres passos independentes -- lead, corretor, calendario --
e uma coluna por passo como marca de feito: nula e o registro de que o passo
nao aconteceu (falhou, foi recusado pela guarda ou a integracao esta
desligada), preenchida e o que impede a reexecucao de repeti-lo.

`calendar_event_id` com o nome e o tamanho do modelo de dados do SRS.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agendamentos", sa.Column("calendar_event_id", sa.String(120), nullable=True))
    op.add_column(
        "agendamentos", sa.Column("corretor_avisado_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agendamentos", sa.Column("lead_avisado_em", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agendamentos", "lead_avisado_em")
    op.drop_column("agendamentos", "corretor_avisado_em")
    op.drop_column("agendamentos", "calendar_event_id")
```

In `src/mobia/domain/agendamento/models.py`, after `motivo_da_alocacao`:

```python
    # TEC-170. Uma marca por passo da confirmacao (D2): nula e "nao aconteceu",
    # preenchida e o que impede a reexecucao de repetir. Ver a migration 0046.
    calendar_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    corretor_avisado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lead_avisado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Write the failing integration tests**

`tests/integration/test_confirmacao_do_agendamento.py`. Build a self-contained file (the repo's integration files copy their helpers; do not import helpers from other test files, except fixtures from `tests/conftest.py` and `eventos_de_log` from there). It needs:

- a corretor via the `semear_corretor` fixture (its email is what the email spy must receive);
- an `Imovel` added directly (copy the `_imovel` helper shape from `tests/integration/test_busca_no_turno.py`, with `bairro="Moema"`, `cidade="São Paulo"`, `uf="SP"`);
- an `Agendamento` row added directly with `status=CONFIRMADO`, `motivo_da_alocacao="MATCH_EXATO"`, `channel="whatsapp"`, `conversation_key="5511911111111"`, 27/08/2026 15h-16h São Paulo, `imovel_id` of that imóvel;
- a LEAD `Message` in that conversation (copy the `Message(...)` construction from `tests/conftest.py::semear`, with `recipient_external_id="222222222"`);
- spies: an outbound spy with `send(message_id, kind, payload) -> bool` returning a configurable bool and recording calls (copy `_OutboundFalso` from `tests/integration/test_notificacao_envio.py`); an email spy `_CanalEspiao` (same file) and `_CanalQueFalha`; a calendar spy recording calls and returning `"evento-1"`, a calendar that raises `FalhaDeCalendario("Google inacessivel: ConnectError")`, and `CalendarioNoop`.

The tests (names are the contract; write their bodies against the helpers above):

```python
async def test_confirmado_avisa_lead_corretor_e_cria_evento(...)
    # outbound: 1 call, kind KIND_DA_CONFIRMACAO, payload para=conversation_key,
    #   de="222222222", texto contains "Moema" and the corretor's nome;
    # email spy: 1 message to the corretor's email, body contains "5511911111111";
    # calendar spy: 1 call with convidado=corretor email, inicio/fim of the row;
    # row: lead_avisado_em == corretor_avisado_em == AGORA, calendar_event_id == "evento-1",
    #   status still CONFIRMADO.

async def test_calendario_indisponivel_nao_impede_os_avisos(..., caplog)
    # lead and corretor notified, calendar_event_id None, status CONFIRMADO,
    # exactly one `agendamento.calendario_falhou` event at level ERROR (use eventos_de_log).

async def test_flag_desligada_nao_chama_calendario(...)
    # CalendarioNoop: lead and corretor notified, calendar_event_id None, no error event.

async def test_email_que_falha_vira_alerta_e_o_resto_segue(..., caplog)
    # _CanalQueFalha: corretor_avisado_em None, `agendamento.aviso_ao_corretor_falhou` ERROR,
    # lead notified and event created.

async def test_reexecucao_nao_repete_nada(...)
    # run twice; between runs add a NEW lead message; totals stay 1/1/1.

async def test_guarda_do_outbound_recusa_e_lead_avisado_fica_nulo(...)
    # outbound spy returns False: lead_avisado_em None, no exception,
    # corretor notified, event created.

async def test_sem_mensagem_do_lead_pula_o_aviso_ao_lead(...)
    # no Message rows: outbound not called, lead_avisado_em None, other steps run.

@pytest.mark.parametrize("status", ["RESERVADO", "EXPIRADO"])
async def test_agendamento_nao_confirmado_e_no_op(status, ...)
    # nothing called, no column set.

async def test_agendamento_inexistente_e_no_op(...)
    # uuid4(): nothing called, no exception.
```

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_confirmacao_do_agendamento.py -v --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'mobia.domain.agendamento.confirmacao'` (or an import error on the new columns if you wrote the tests before Step 1).

- [ ] **Step 3: Implement `avisar_confirmacao`**

`src/mobia/domain/agendamento/confirmacao.py`:

```python
"""O que acontece depois que o agendamento e confirmado. TEC-170, RN-12.1.

Tres passos independentes -- avisar o lead, avisar o corretor, criar o evento
na agenda dele --, cada um com a propria sessao curta e sem transacao aberta
durante chamada de rede (o molde de `notificar`, em `notificacao/envio.py`).
A falha de um vira alerta e nao impede o seguinte; nenhum escreve em
`status`. Cada passo tem a sua coluna como marca de feito, e e ela que deixa
o job ser reexecutado sem repetir nada (D2 do desenho).

**Nenhum caminho de producao chama isto ainda**: quem ligar o agendamento a
conversa enfileira o job depois do commit de `confirmar()`. Ver
docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agendamento.calendario import CalendarioPort, FalhaDeCalendario
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.mensagens import aviso_ao_corretor, texto_ao_lead
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.resumo import link_da_transcricao
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import CanalDeNotificacaoPort, FalhaDeCanal
from mobia.domain.outbound.port import OutboundPort

log = structlog.get_logger()

AVISAR_CONFIRMACAO_JOB = "avisar_confirmacao"
KIND_DA_CONFIRMACAO = "confirmacao_de_agendamento"


@dataclass(frozen=True)
class _Retrato:
    """O que os tres passos precisam, lido uma vez e fora de sessao.

    Os passos rodam com sessoes proprias; carregar os objetos do ORM de uma
    sessao ja fechada para dentro de outra convidaria atributo expirado.
    """

    id: uuid.UUID
    tipo: str
    inicio: datetime
    fim: datetime
    channel: str
    conversation_key: str
    corretor_nome: str
    corretor_email: str
    imovel: Imovel | None
    lead_avisado: bool
    corretor_avisado: bool
    evento_criado: bool


async def avisar_confirmacao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    agendamento_id: uuid.UUID,
    outbound: OutboundPort,
    email: CanalDeNotificacaoPort,
    calendario: CalendarioPort,
    agora: datetime,
) -> None:
    """Os tres avisos de um agendamento CONFIRMADO; qualquer outro e no-op (D1)."""
    retrato = await _retratar(session_factory, agendamento_id)
    if retrato is None:
        return
    link = link_da_transcricao(retrato.channel, retrato.conversation_key)
    if not retrato.lead_avisado:
        await _avisar_lead(session_factory, retrato, outbound=outbound, agora=agora)
    if not retrato.corretor_avisado:
        await _avisar_corretor(session_factory, retrato, email=email, link=link, agora=agora)
    if not retrato.evento_criado:
        await _criar_evento(session_factory, retrato, calendario=calendario, link=link)


async def _retratar(
    session_factory: async_sessionmaker[AsyncSession], agendamento_id: uuid.UUID
) -> _Retrato | None:
    async with session_factory() as session:
        agendamento = await session.get(Agendamento, agendamento_id)
        if agendamento is None or agendamento.status != StatusDoAgendamento.CONFIRMADO:
            # O job pode ter sido enfileirado por um caminho que depois nao
            # commitou a confirmacao.
            log.info(
                "agendamento.confirmacao_ignorada",
                agendamento_id=str(agendamento_id),
                status=None if agendamento is None else agendamento.status,
            )
            return None
        corretor = await session.get(Corretor, agendamento.corretor_id)
        assert corretor is not None  # FK NOT NULL
        imovel = (
            await session.get(Imovel, agendamento.imovel_id) if agendamento.imovel_id else None
        )
        if imovel is not None:
            session.expunge(imovel)
        return _Retrato(
            id=agendamento.id,
            tipo=agendamento.tipo,
            inicio=agendamento.inicio,
            fim=agendamento.fim,
            channel=agendamento.channel,
            conversation_key=agendamento.conversation_key,
            corretor_nome=corretor.nome,
            corretor_email=corretor.email,
            imovel=imovel,
            lead_avisado=agendamento.lead_avisado_em is not None,
            corretor_avisado=agendamento.corretor_avisado_em is not None,
            evento_criado=agendamento.calendar_event_id is not None,
        )


async def _marcar(
    session_factory: async_sessionmaker[AsyncSession], agendamento_id: uuid.UUID, **valores: object
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Agendamento).where(Agendamento.id == agendamento_id).values(**valores)
        )
        await session.commit()


async def _avisar_lead(
    session_factory: async_sessionmaker[AsyncSession],
    retrato: _Retrato,
    *,
    outbound: OutboundPort,
    agora: datetime,
) -> None:
    # Ancorado na ultima mensagem DO LEAD, pelo motivo que a docstring de
    # `_avisar_lead_da_janela_humana` (`notificacao/envio.py`) explica: e ela
    # que carrega, em `recipient_external_id`, o numero do canal que fala com
    # ele.
    async with session_factory() as session:
        ultima_do_lead = (
            await session.execute(
                select(Message)
                .where(
                    Message.channel == retrato.channel,
                    Message.conversation_key == retrato.conversation_key,
                    Message.role == MessageRole.LEAD,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if ultima_do_lead is None:
        log.info("agendamento.aviso_ao_lead_sem_mensagem", agendamento_id=str(retrato.id))
        return
    texto = texto_ao_lead(
        tipo=retrato.tipo,
        inicio=retrato.inicio,
        corretor=retrato.corretor_nome,
        imovel=retrato.imovel,
    )
    try:
        aceito = await outbound.send(
            ultima_do_lead.id,
            KIND_DA_CONFIRMACAO,
            {"para": retrato.conversation_key, "de": ultima_do_lead.recipient_external_id, "texto": texto},
        )
    # `except Exception` aqui, e nao a lista curta dos outros passos: e o
    # mesmo contrato de `_avisar_lead_da_janela_humana`, porque o `outbound`
    # levanta tipos distintos por adaptador (`EnvioRetentavel`,
    # `EnvioRecusado`, `EnvioForaDaJanela`) e nenhum deles pode impedir o
    # aviso ao corretor.
    except Exception as falha:
        log.error(
            "agendamento.aviso_ao_lead_falhou",
            agendamento_id=str(retrato.id),
            reason=type(falha).__name__,
        )
        return
    if not aceito:
        # A guarda recusou (opt-out, atendimento humano) ou a mesma chave ja
        # tinha saido: nao e falha, e a coluna fica nula.
        log.info("agendamento.aviso_ao_lead_recusado", agendamento_id=str(retrato.id))
        return
    await _marcar(session_factory, retrato.id, lead_avisado_em=agora)


async def _avisar_corretor(
    session_factory: async_sessionmaker[AsyncSession],
    retrato: _Retrato,
    *,
    email: CanalDeNotificacaoPort,
    link: str,
    agora: datetime,
) -> None:
    aviso = aviso_ao_corretor(
        tipo=retrato.tipo,
        inicio=retrato.inicio,
        corretor=retrato.corretor_nome,
        imovel=retrato.imovel,
        channel=retrato.channel,
        conversation_key=retrato.conversation_key,
        link=link,
    )
    try:
        await email.enviar(destino=retrato.corretor_email, aviso=aviso)
    except FalhaDeCanal as falha:
        log.error(
            "agendamento.aviso_ao_corretor_falhou",
            agendamento_id=str(retrato.id),
            reason=type(falha).__name__,
        )
        return
    await _marcar(session_factory, retrato.id, corretor_avisado_em=agora)


async def _criar_evento(
    session_factory: async_sessionmaker[AsyncSession],
    retrato: _Retrato,
    *,
    calendario: CalendarioPort,
    link: str,
) -> None:
    remota = retrato.tipo == TipoDeCompromisso.REUNIAO_REMOTA
    titulo = "Reunião remota" if remota else "Visita"
    if not remota and retrato.imovel is not None:
        titulo = f"{titulo}: {retrato.imovel.titulo} ({retrato.imovel.codigo})"
    try:
        identificador = await calendario.criar_evento(
            inicio=retrato.inicio,
            fim=retrato.fim,
            titulo=titulo,
            descricao=f"Lead: {retrato.channel} {retrato.conversation_key}\n{link}",
            convidado=retrato.corretor_email,
        )
    except FalhaDeCalendario as falha:
        log.error(
            "agendamento.calendario_falhou",
            agendamento_id=str(retrato.id),
            reason=str(falha),
        )
        return
    if identificador is not None:
        await _marcar(session_factory, retrato.id, calendar_event_id=identificador)
```

Check before trusting: `Corretor.nome`/`email` are non-null in the model (they are, per TEC-196), and that `session.expunge(imovel)` keeps its loaded attributes readable after the session closes (it does for loaded column attributes; if a test shows `DetachedInstanceError`, copy the five fields `titulo, codigo, bairro, cidade, uf` into the snapshot instead and adapt `mensagens.py` calls by building a transient `Imovel` — report the change).

- [ ] **Step 4: Run the tests**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_confirmacao_do_agendamento.py tests/integration/test_agendamento_repositorio.py tests/integration/test_agendamento_schema.py tests/integration/test_visitas_por_dia.py -v --tb=short`
Expected: PASS. Then run the migration tests: `./.venv/Scripts/python.exe -m pytest tests/integration -k "migra or alembic" --tb=short -q`.

If many tests fail with `column ... does not exist`, it is the stale-worker-database trap (CLAUDE.md): check `alembic_version` before touching code.

- [ ] **Step 5: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add alembic/versions/0046_avisos_do_agendamento.py src/mobia/domain/agendamento/models.py src/mobia/domain/agendamento/confirmacao.py tests/integration/test_confirmacao_do_agendamento.py
git commit -m "feat(TEC-170): o agendamento confirmado avisa lead e corretor e cria o evento, cada passo uma vez

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: O job, a porta de enfileiramento e o worker

**Files:**
- Create: `src/mobia/domain/agendamento/agendador.py`
- Create: `src/mobia/workers/jobs/avisar_confirmacao.py`
- Modify: `src/mobia/workers/main.py` (`startup` + `WorkerSettings.functions` + guarda de configuração)
- Test: `tests/unit/test_agendador_de_confirmacao.py`; extend `tests/integration/test_worker_startup.py` (read it first and follow its shape)

**Interfaces:**
- Consumes: `avisar_confirmacao`, `AVISAR_CONFIRMACAO_JOB` (Task 3); `GoogleCalendar`, `CalendarioNoop` (Task 2)
- Produces:
  - `AgendadorDeConfirmacaoPort(Protocol)`: `async agendar(self, agendamento_id: uuid.UUID) -> None`; `AgendadorDeConfirmacaoNoop`; `AgendadorDeConfirmacaoArq(pool: ArqRedis)` enfileirando `AVISAR_CONFIRMACAO_JOB` com `_job_id=f"confirmacao:{agendamento_id}"`
  - job `avisar_confirmacao(ctx, agendamento_id: str) -> str` registered with `func(..., keep_result=0)`
  - `ctx["email_ao_corretor"]` (the same `EmailSmtp` instance used in `canais_de_notificacao`) and `ctx["calendario"]`

- [ ] **Step 1: The enqueue port (test first)**

`tests/unit/test_agendador_de_confirmacao.py`: a fake pool recording `enqueue_job(*args, **kwargs)`; assert `AgendadorDeConfirmacaoArq(pool).agendar(id)` calls `enqueue_job("avisar_confirmacao", str(id), _job_id=f"confirmacao:{id}")`, and that `AgendadorDeConfirmacaoNoop().agendar(id)` returns `None`. Run it failing, then write `src/mobia/domain/agendamento/agendador.py` in the exact shape of `src/mobia/domain/handoff/agendador.py` (docstrings: the `_job_id` fixed keeps two live jobs for the same agendamento from existing; no production caller yet — whoever wires `confirmar()` into the conversation calls `agendar` after the commit).

- [ ] **Step 2: The job**

`src/mobia/workers/jobs/avisar_confirmacao.py`, in the shape of `src/mobia/workers/jobs/notificar.py`:

```python
"""O job que avisa lead e corretor do agendamento confirmado. TEC-170."""

import uuid
from datetime import UTC, datetime
from typing import Any

from mobia.domain.agendamento.confirmacao import avisar_confirmacao as _avisar_confirmacao


async def avisar_confirmacao(ctx: dict[str, Any], agendamento_id: str) -> str:
    """Os tres avisos do agendamento. O nome da funcao e `AVISAR_CONFIRMACAO_JOB`.

    O ARQ registra o job pelo `__name__` da funcao, entao o nome aqui e o
    contrato com `AgendadorDeConfirmacaoArq` -- mudar um sem o outro faz o
    enfileiramento cair num job que nao existe. As portas vem do `ctx`: e o
    `startup` que decide a implementacao, e o teste troca sem tocar no job.
    """
    await _avisar_confirmacao(
        ctx["session_factory"],
        agendamento_id=uuid.UUID(agendamento_id),
        outbound=ctx["outbound"],
        email=ctx["email_ao_corretor"],
        calendario=ctx["calendario"],
        agora=datetime.now(UTC),
    )
    return "avisado"
```

Add a unit assertion (in `tests/unit/test_agendador_de_confirmacao.py`) that `avisar_confirmacao.__name__ == AVISAR_CONFIRMACAO_JOB`.

- [ ] **Step 3: The worker**

In `src/mobia/workers/main.py`:

1. Keep one `EmailSmtp()` instance: `email = EmailSmtp()`, `ctx["canais_de_notificacao"] = (email, WhatsAppTemplate())`, `ctx["email_ao_corretor"] = email`, with a one-line comment saying why it is the same instance (the SMTP guard of the startup already validated it).
2. After the CRM block:

```python
    # TEC-170, D5. A flag e a credencial vazia, na convencao do CRM logo
    # acima: sem refresh token o worker sobe com o Noop e avisa uma vez por
    # subida. Com o token, id e segredo sao obrigatorios -- ver a guarda.
    if settings.google_calendar_refresh_token:
        ctx["calendario"] = GoogleCalendar()
    else:
        ctx["calendario"] = CalendarioNoop()
        log.warning(
            "agendamento.calendario_desligado",
            motivo="GOOGLE_CALENDAR_REFRESH_TOKEN nao configurado; nenhum evento sera criado",
        )
```

3. A guard next to the existing ones that raise `ConfiguracaoInsegura` (read how they are written and called from `startup`, and follow the same shape): refresh token set and client id or client secret empty → `ConfiguracaoInsegura` naming the missing variable. Called from `startup` like the others.
4. Register `func(avisar_confirmacao, keep_result=0)` in `WorkerSettings.functions`, importing the job from `mobia.workers.jobs.avisar_confirmacao`.

- [ ] **Step 4: Startup tests**

Read `tests/integration/test_worker_startup.py` and add, in its style: (a) without refresh token → `ctx["calendario"]` is `CalendarioNoop` and `agendamento.calendario_desligado` was logged; (b) with refresh token + id + secret → `GoogleCalendar`; (c) refresh token without secret → `ConfiguracaoInsegura`; (d) `ctx["email_ao_corretor"] is ctx["canais_de_notificacao"][0]`; (e) `"avisar_confirmacao"` is among the registered function names (if another test already asserts the list of registered jobs, extend that one instead of adding a new one).

- [ ] **Step 5: Run**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_agendador_de_confirmacao.py tests/integration/test_worker_startup.py -v --tb=short`
Expected: PASS.

- [ ] **Step 6: Gates and commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agendamento/agendador.py src/mobia/workers/jobs/avisar_confirmacao.py src/mobia/workers/main.py tests/unit/test_agendador_de_confirmacao.py tests/integration/test_worker_startup.py
git commit -m "feat(TEC-170): o job da confirmacao entra no worker, com o calendario desligado por credencial vazia

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Emendas ao SRS, comentários e status

**Files:**
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (três emendas aninhadas)
- Modify: `docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md` (`**Status:**` → `implementado`)
- Modify: any comment/docstring the listing flags as made false by Tasks 1–4

- [ ] **Step 1: The amendments**

Nested items, **never rewriting** the existing text, in the format of their siblings: `- **Emenda E-nn (TEC-170, 24/09/2026):** ...`, numbered after the last existing amendment under THAT rule (check the SRS). Accented. Short (3–5 sentences each). Code cited by anchor.

- Under **RN-12.1**: the address is title, code, bairro, cidade and UF of the imóvel, because the catalog has no street/number/CEP (the corretor gives the exact number); the corretor is notified by e-mail and not by WhatsApp, because the approved template carries only etiqueta, prioridade and link; the calendar event is created on the organizer account's calendar with the corretor invited, and the integration is off when `GOOGLE_CALENDAR_REFRESH_TOKEN` is empty. Nothing in the conversation confirms scheduling yet.
- Under **RN-16.1**: the trigger "agendamento confirmado" still has no caller — TEC-170 notifies the corretor with its own e-mail and does not open a handoff, because an open handoff silences the agent in that conversation until the corretor hands it back (decided 24/09/2026).
- Under **RN-17.1**, below its Emenda E-01 (TEC-190): TEC-170 is part of RF-12 and does not bring the four scheduling indicators back; they stay `null`/`disponivel: false`, because no production path creates agendamentos yet — counting them would say "zero visits scheduled" when the truth is "none recorded".

- [ ] **Step 2: Comments**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py` and read every `ALTERADO`/`VIZINHO`/`PROSA`/`NOMEIA` entry for the branch. Fix any sentence Tasks 1–4 made false. In particular, check comments that still say TEC-170 is future work: `grep -rn "TEC-170" src tests` — e.g. `domain/corretores/vocabulario.py` (`jornada_valida` docstring), `domain/agendamento/janelas.py`, `domain/humano`/`outbound` comments about per-day schedules. For each hit: still true → leave; false → rewrite to what is true now (per-day schedule is NOT delivered by TEC-170; say it is still missing, with no card number). Never invent a card number. Do not edit migrations' docstrings or `docs/superpowers/plans/*`.

- [ ] **Step 3: Status and checks**

Set the spec `**Status:**` to `implementado`. Run `./.venv/Scripts/python.exe scripts/comentarios_tocados.py --checar` (exit 0), `./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q`, and the three gates.

- [ ] **Step 4: Commit**

```bash
git add docs/srs/srs-agente-sdr-imobiliario-v1.0.md docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md <every src/tests file you edited>
git commit -m "docs(TEC-170): o SRS registra o que a confirmacao entrega e o que ficou de fora

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Final: suíte inteira, uma vez

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short -q`
If it comes back with hundreds of setup `ERROR`s or `CannotConnectNowError`, follow CLAUDE.md "Quando o `-n 8` derruba o Postgres" and run by blocks. Record the commit hash with the result.

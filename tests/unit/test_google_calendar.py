"""O adaptador do Google Calendar contra um transporte falso. TEC-170, D5.

Nenhuma chamada sai da maquina: `httpx.MockTransport` responde as duas URLs.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mobia.domain.agendamento.calendario import (
    CalendarioNoop,
    FalhaDeCalendario,
    GoogleCalendar,
)

SP = ZoneInfo("America/Sao_Paulo")
INICIO = datetime(2026, 8, 27, 15, 0, tzinfo=SP)
FIM = datetime(2026, 8, 27, 16, 0, tzinfo=SP)


@pytest.fixture(autouse=True)
def _credenciais(monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos) -> None:
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "segredo")
    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "agenda@imobiliaria.com")
    yield


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

    assert str(evento.url.path) == "/calendar/v3/calendars/agenda@imobiliaria.com/events"
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

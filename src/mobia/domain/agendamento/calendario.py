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
            agenda_encoded = quote(configuracao.google_calendar_id, safe="")
            corpo: dict[str, Any] = {
                "summary": titulo,
                "description": descricao,
                "start": {"dateTime": inicio.isoformat(), "timeZone": configuracao.followup_fuso},
                "end": {"dateTime": fim.isoformat(), "timeZone": configuracao.followup_fuso},
                "attendees": [{"email": convidado}],
            }
            resposta = await cliente.post(
                URL_DOS_EVENTOS.format(agenda=agenda_encoded),
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

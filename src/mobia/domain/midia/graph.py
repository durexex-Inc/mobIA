"""Buscar na Graph API a midia que o lead mandou. TEC-132, D3.

Dois passos, porque e assim que a Meta entrega: o `media_id` do envelope se
resolve numa URL temporaria, e a URL exige o MESMO bearer para baixar. **A URL
nunca vai para log**: ela e credencial de curta duracao. Por isso nenhuma
excecao daqui carrega a URL nem `str()` de uma excecao do httpx -- so o nome do
tipo ou o status HTTP.
"""

from typing import Any, NamedTuple

import httpx

from mobia.app.config import get_settings

# O mesmo carve-out e o mesmo timeout da entrega de mensagem: sao a mesma API,
# com o mesmo token, e o motivo escrito la vale aqui -- 408 e 429 sao a Meta
# pedindo para tentar depois, e trata-los como recusa fecharia a midia como
# FALHOU para sempre. O timeout do httpx e por operacao (conectar, ler um
# pedaco), nao do download inteiro: 10s entre pedacos nao corta um arquivo
# grande que esteja chegando.
from mobia.domain.outbound.whatsapp import CODIGOS_4XX_RETENTAVEIS, TIMEOUT_SEGUNDOS

__all__ = [
    "TIMEOUT_SEGUNDOS",
    "MidiaAcimaDoTeto",
    "MidiaDaMeta",
    "MidiaIndisponivel",
    "MidiaRecusada",
    "baixar",
    "resolver",
]


class MidiaIndisponivel(Exception):
    """Retentavel: 5xx, 408/429 ou erro de rede."""


class MidiaRecusada(Exception):
    """Permanente: a Meta recusou (midia expirada, token invalido)."""


class MidiaAcimaDoTeto(Exception):
    """O corpo passou do teto, mesmo que o `file_size` tenha dito outra coisa."""


class MidiaDaMeta(NamedTuple):
    url: str
    mime_type: str
    tamanho: int | None


def _cabecalhos() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().whatsapp_access_token}"}


def _conferir_status(status: int) -> None:
    if status >= 500 or status in CODIGOS_4XX_RETENTAVEIS:
        raise MidiaIndisponivel(f"http {status}")
    if status >= 400:
        raise MidiaRecusada(f"http {status}")
    if not 200 <= status < 300:
        # 3xx: o httpx nao segue redirecionamento por padrao, e seguir levaria
        # o bearer para outro host. Um redirect se repetiria na retentativa,
        # entao e recusa, nao indisponibilidade.
        raise MidiaRecusada(f"http {status}")


async def resolver(media_id: str, *, cliente: httpx.AsyncClient) -> MidiaDaMeta:
    url = f"{get_settings().whatsapp_api_base}/{media_id}"
    try:
        resposta = await cliente.get(url, headers=_cabecalhos())
    except httpx.RequestError as exc:
        raise MidiaIndisponivel(type(exc).__name__) from exc
    _conferir_status(resposta.status_code)
    try:
        corpo: dict[str, Any] = resposta.json()
        tamanho = corpo.get("file_size")
        return MidiaDaMeta(
            url=str(corpo["url"]),
            mime_type=str(corpo.get("mime_type") or ""),
            tamanho=int(tamanho) if tamanho is not None else None,
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        # 200 com corpo fora do formato: provavelmente um proxy no meio, e nao
        # uma resposta da Meta. Retentar e barato e o teto de tentativas
        # limita; recusar de primeira perderia a midia por um soluco.
        raise MidiaIndisponivel("resolucao fora do formato") from exc


async def baixar(url: str, *, teto: int, cliente: httpx.AsyncClient) -> bytes:
    pedacos: list[bytes] = []
    total = 0
    try:
        async with cliente.stream("GET", url, headers=_cabecalhos()) as resposta:
            _conferir_status(resposta.status_code)
            async for pedaco in resposta.aiter_bytes():
                total += len(pedaco)
                if total > teto:
                    # Aborta no meio: sair do `async with` fecha a conexao sem
                    # ler o resto do corpo.
                    raise MidiaAcimaDoTeto(f"mais de {teto} bytes")
                pedacos.append(pedaco)
    except httpx.RequestError as exc:
        raise MidiaIndisponivel(type(exc).__name__) from exc
    return b"".join(pedacos)

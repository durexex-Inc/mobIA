import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel, GuardedOutbound

log = structlog.get_logger(__name__)

# A Meta devolve este codigo quando passaram mais de 24h desde a ultima fala do
# lead e a mensagem livre deixa de ser permitida.
CODIGO_FORA_DA_JANELA = 131047

# 408 e 429 sao 4xx na faixa numerica, mas nao sao erro do cliente: o servidor
# esta pedindo para tentar de novo mais tarde, nao dizendo que o payload esta
# errado. Tratar qualquer um dos dois como EnvioRecusado prende a reserva e
# perde a resposta ao lead para sempre. Quem reintroduzir um `status >= 400`
# generico aqui reintroduz esse bug -- por isso o carve-out fica explicito.
CODIGOS_4XX_RETENTAVEIS = frozenset({408, 429})

TIMEOUT_SEGUNDOS = 10.0


class EnvioForaDaJanela(EnvioRecusado):
    """Passaram mais de 24h desde a ultima fala do lead.

    Herda de EnvioRecusado porque retentar nao ajuda -- so template aprovado
    entrega fora da janela, e template e outra historia. Mas e distinguivel de
    um 4xx comum porque nao e erro nosso: o turno termina PROCESSED com aviso,
    nao com erro de payload.
    """


class WhatsAppOutbound(GuardedOutbound):
    """Entrega de verdade pela Cloud API da Meta.

    Primeiro `_deliver` real do projeto -- ate a TEC-134 ele levantava
    NotImplementedError e o NoopOutbound so logava.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cliente: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(session_factory)
        self._cliente = cliente

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        settings = get_settings()
        # Monta url/corpo antes de abrir o cliente: se o payload vier sem uma
        # chave esperada, o KeyError estoura sem deixar um AsyncClient aberto
        # para tras.
        url = f"{settings.whatsapp_api_base}/{payload['de']}/messages"
        corpo = {
            "messaging_product": "whatsapp",
            "to": payload["para"],
            "type": "text",
            "text": {"body": payload["texto"]},
        }
        cliente = self._cliente or httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS)

        try:
            resposta = await cliente.post(
                url,
                json=corpo,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            )
        except httpx.RequestError as exc:
            # Nao sabemos se chegou. Retentar pode duplicar, e essa e a troca
            # que o spec escolheu de proposito: duplicata visivel e melhor que
            # silencio invisivel.
            raise EnvioRetentavel(type(exc).__name__) from exc
        finally:
            if self._cliente is None:
                await cliente.aclose()

        if resposta.status_code >= 500:
            raise EnvioRetentavel(f"http {resposta.status_code}")

        if resposta.status_code in CODIGOS_4XX_RETENTAVEIS:
            raise EnvioRetentavel(f"http {resposta.status_code}")

        if resposta.status_code >= 400:
            codigo = _codigo_do_erro(resposta)
            # Nunca `resposta.text` nem o corpo enviado: o primeiro pode ecoar
            # o payload e o segundo e a fala do agente para o lead.
            log.warning(
                "outbound.recusado",
                message_id=str(message_id),
                kind=kind,
                status=resposta.status_code,
                codigo=codigo,
            )
            if codigo == CODIGO_FORA_DA_JANELA:
                raise EnvioForaDaJanela(str(codigo))
            raise EnvioRecusado(f"http {resposta.status_code} codigo {codigo}")


def _codigo_do_erro(resposta: httpx.Response) -> int | None:
    """O codigo numerico da Meta, quando o corpo tiver o formato esperado."""
    try:
        return int(resposta.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None

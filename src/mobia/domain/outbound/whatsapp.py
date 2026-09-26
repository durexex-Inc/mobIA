import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.identidade.indice import IdentidadeAusente, revelar
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.outbound.port import (
    EnvioForaDaJanela,
    EnvioRecusado,
    EnvioRetentavel,
    GuardedOutbound,
)

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
        # TEC-203. O `para` e a chave do lead; o `wa_id` cru sai da identidade
        # aqui, no ultimo instante, e so existe na memoria deste envio.
        try:
            async with self._session_factory() as session:
                destino = await revelar(session, CANAL_WHATSAPP, payload["para"])
        except IdentidadeAusente as exc:
            log.warning("outbound.identidade_ausente", message_id=str(message_id), kind=kind)
            # Permanente: tentar de novo nao cria a identidade que falta.
            raise EnvioRecusado("identidade ausente") from exc
        # Monta url/corpo antes de abrir o cliente: se o payload vier sem uma
        # chave esperada, o KeyError estoura sem deixar um AsyncClient aberto
        # para tras.
        url = f"{settings.whatsapp_api_base}/{payload['de']}/messages"
        corpo: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": destino,
        }
        # TEC-162. `tipo` ausente e texto, e o default nao e comodidade: os
        # chamadores de antes desta card (`turno.py`, `_entregar_texto_fixo`,
        # os follow-ups) nao mandam a chave, e exigi-la deles quebraria toda
        # resposta que nao apresenta imovel.
        if payload.get("tipo") == "imagem":
            corpo["type"] = "image"
            corpo["image"] = {"link": payload["link"], "caption": payload["legenda"]}
        elif payload.get("tipo") == "template":
            # TEC-186, RN-13.6. Fora da janela de 24h a Meta so aceita template
            # aprovado -- este e o unico caminho de saida que ela nao recusa
            # com o codigo 131047. Diferente do texto e da imagem, um template
            # nunca levanta `EnvioForaDaJanela`: e ele que existe para nao
            # cair nela.
            #
            # `components` so entra QUANDO ha parametros: o template de convite
            # nao tem placeholder, e a Cloud API recusa um `components` de
            # corpo com lista de parametros vazia. `parametros_do_template`
            # devolve `[]` justamente nesse caso.
            template: dict[str, Any] = {
                "name": payload["template"],
                "language": {"code": payload["idioma"]},
            }
            parametros = payload.get("parametros") or []
            if parametros:
                template["components"] = [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": p} for p in parametros],
                    }
                ]
            corpo["type"] = "template"
            corpo["template"] = template
        else:
            corpo["type"] = "text"
            corpo["text"] = {"body": payload["texto"]}
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

    async def indicar_digitacao(
        self, *, provider_message_id: str, de: str, para: str | None
    ) -> None:
        # `para` e IGNORADO aqui, e a assinatura o recebe so porque o port e
        # um so para os dois canais (TEC-362). O indicador da Meta nao e um
        # envio para alguem: e uma anotacao sobre a mensagem RECEBIDA, entao
        # quem o identifica e o `wamid` dela mais o numero da imobiliaria. No
        # canal web `para` e a sessao, e la ele e tudo -- ver `WebIndicador`.
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

"""O adaptador de webhook HTTP da RN-16.5. TEC-180.

Molde de `domain/outbound/whatsapp.py`: timeout de modulo, cliente injetavel
para o teste, e um unico ponto onde a resposta do outro lado vira excecao
nossa.
"""

import json
import uuid
from typing import Any

import httpx
import structlog

from mobia.app.config import get_settings
from mobia.domain.crm.port import FalhaDeExportacao
from mobia.infra.signature import compute_signature

log = structlog.get_logger(__name__)

# O nome do cabecalho de assinatura e NOSSO, apesar de o calculo ser o mesmo de
# `infra/signature.py`. `X-Hub-Signature-256` e como a Meta assina o que ela nos
# manda; reusar o nome na saida faria um grep por ele misturar os dois sentidos
# do fluxo, e quem investigasse uma assinatura recusada nao saberia de qual
# ponta esta olhando.
CABECALHO_DE_ASSINATURA = "X-Mobia-Signature-256"

# A chave de idempotencia (D6). Nome padrao de mercado de proposito: o
# consumidor provavelmente ja sabe o que fazer com ele sem ler documentacao
# nossa.
CABECALHO_DE_IDEMPOTENCIA = "Idempotency-Key"


class CrmWebhook:
    """Entrega por POST JSON na URL configurada.

    **Qualquer coisa que nao seja 2xx vira `FalhaDeExportacao`**, inclusive
    4xx. E divergencia deliberada de `WhatsAppOutbound`, que separa recusa
    permanente de falha retentavel: la a distincao decide o desfecho de um
    turno que ja custou uma chamada paga ao modelo, e retentar um payload
    recusado pela Meta nunca entregaria. Aqui o consumidor e desconhecido --
    um 400 tanto pode ser payload invalido quanto um proxy mal configurado na
    frente do CRM, e um 401 e quase sempre segredo desatualizado, que alguem
    conserta e a proxima rodada da varredura entrega. Desistir na primeira
    seria a perda silenciosa que a RN-16.5 proibe; retentar custa tres POSTs.
    """

    nome = "webhook"

    def __init__(self, cliente: httpx.AsyncClient | None = None) -> None:
        self._cliente = cliente

    async def exportar(self, *, handoff_id: uuid.UUID, payload: dict[str, Any]) -> None:
        settings = get_settings()

        # `json=` faria o httpx serializar por dentro, e a assinatura precisa
        # ser calculada sobre os MESMOS bytes que vao no corpo. Serializar duas
        # vezes -- uma para assinar, outra para enviar -- abre a chance de os
        # dois resultados diferirem (ordem de chaves, separadores) e produzir
        # assinatura que o consumidor recusa, com um sintoma que so aparece do
        # outro lado do fio.
        corpo = json.dumps(payload).encode("utf-8")

        cabecalhos = {
            "Content-Type": "application/json",
            CABECALHO_DE_IDEMPOTENCIA: str(handoff_id),
        }
        if settings.crm_webhook_secret:
            cabecalhos[CABECALHO_DE_ASSINATURA] = compute_signature(
                settings.crm_webhook_secret, corpo
            )

        cliente = self._cliente or httpx.AsyncClient(timeout=settings.crm_timeout_segundos)
        try:
            resposta = await cliente.post(
                settings.crm_webhook_url, content=corpo, headers=cabecalhos
            )
        except httpx.HTTPError as falha:
            # `type(falha).__name__` e nao `str(falha)`: o texto de uma excecao
            # do httpx carrega a URL, e ela e segredo de configuracao. E este
            # sitio que garante o que o docstring de `FalhaDeExportacao`
            # promete sobre `motivo` -- ver a D5 do desenho e o
            # `_detalhe_para_a_coluna` da TEC-222.
            raise FalhaDeExportacao(type(falha).__name__) from falha
        finally:
            if self._cliente is None:
                await cliente.aclose()

        if resposta.status_code // 100 != 2:
            # O status entra na mensagem porque e numero, nao prosa de
            # terceiro: nao carrega URL, corpo nem PII, e e o unico fato que
            # separa "o CRM esta fora" de "o CRM recusou o que mandamos".
            raise FalhaDeExportacao(f"HTTP {resposta.status_code}")

import hashlib
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from mobia.api.deps import get_ingestion_service
from mobia.app.config import Settings, get_settings
from mobia.app.logging import correlation_id
from mobia.domain.messages.schemas import parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.infra.signature import SIGNATURE_HEADER, is_valid_signature

log = structlog.get_logger(__name__)
router = APIRouter(tags=["whatsapp"])


@router.get("/webhooks/whatsapp")
async def verify(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    """Handshake de registro do webhook na Meta."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.whatsapp_verify_token
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))

    log.warning("webhook.verify_rejected", reason="invalid_verify_token")
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/webhooks/whatsapp")
async def ingest(
    request: Request,
    settings: Settings = Depends(get_settings),
    service: IngestionService = Depends(get_ingestion_service),
) -> Response:
    """Recebe, valida, persiste e enfileira.

    Responde 200 em todo caminho que nao tem o que perder -- assinatura invalida,
    JSON malformado, envelope ilegivel, payload sem mensagem de entrada: a Meta
    re-tenta em nao-2xx, e quem forja assinatura nao deve conseguir provocar
    retry. A excecao e a falha ao persistir, que sobe e vira 500 de proposito
    para que a Meta re-entregue -- ver o comentario no fim desta funcao.
    Nenhuma chamada a provedor de LLM ocorre aqui.
    """
    correlation_id.set(str(uuid.uuid4()))

    body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)
    remote_ip = request.client.host if request.client else None
    payload_sha256 = hashlib.sha256(body).hexdigest()

    if not is_valid_signature(settings.whatsapp_app_secret, body, signature):
        log.warning(
            "webhook.rejected",
            reason="invalid_signature" if signature else "missing_signature",
            remote_ip=remote_ip,
            payload_sha256=payload_sha256,
        )
        return Response(status_code=200)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        log.warning(
            "webhook.rejected",
            reason="malformed_json",
            remote_ip=remote_ip,
            payload_sha256=payload_sha256,
        )
        return Response(status_code=200)

    try:
        parsed = parse_meta_envelope(payload)
    except Exception as exc:
        # So a interpretacao do envelope fica sob a rede de seguranca. Um 500
        # aqui faria a Meta re-entregar um payload que ninguem consegue ler, e
        # como provider_message_id so vira UNIQUE em TEC-125 uma re-entrega que
        # desse certo nasceria como segunda linha -- com message_id diferente,
        # que a guarda de outbound_dispatches nao casa. Payload assinado mas
        # malformado nao tem o que perder: 200 e o certo.
        log.exception(
            "webhook.error",
            reason=type(exc).__name__,
            detail=str(exc),
            payload_sha256=payload_sha256,
        )
        return Response(status_code=200)

    if not parsed:
        log.info("webhook.ignored", reason="no_inbound_messages")
        return Response(status_code=200)

    # `ingest` fica deliberadamente fora do try. Se o `_persist` levanta
    # (Postgres fora do ar, pool esgotado, statement timeout), nada foi gravado
    # -- ele commita o lote inteiro numa transacao so -- e portanto nao ha linha
    # para o sweeper achar. Engolir isso num 200 faria a Meta marcar a entrega
    # como bem-sucedida e a mensagem sumiria para sempre. Deixar subir vira 500
    # e a Meta re-entrega; sem risco de duplicata, justamente porque nada foi
    # escrito. Abaixo do `_persist` nao ha o que levantar: o `_try_enqueue` ja
    # engole as proprias excecoes.
    await service.ingest(parsed)

    return Response(status_code=200)

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

    Responde 200 em todos os caminhos, inclusive na recusa: a Meta re-tenta em
    nao-2xx, e quem forja assinatura nao deve conseguir provocar retry.
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
            reason="invalid_signature" if signature else "missing_or_invalid_signature",
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

    parsed = parse_meta_envelope(payload)
    if not parsed:
        log.info("webhook.ignored", reason="no_inbound_messages")
        return Response(status_code=200)

    await service.ingest(parsed)
    return Response(status_code=200)

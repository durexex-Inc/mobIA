import hashlib
import json

import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from mobia.api.deps import get_ingestion_service
from mobia.app.config import Settings, get_settings
from mobia.domain.messages.schemas import parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import motivo_do_erro_de_banco
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
        # aqui faria a Meta re-entregar um payload que ninguem consegue ler --
        # puro ruido, porque a re-entrega falharia no mesmo ponto. Payload
        # assinado mas malformado nao tem o que perder: 200 e o certo.
        # Sem `detail`: o envelope da Meta e entrada externa por definicao, e o
        # eco do texto de uma excecao sobre ele nao tem garantia de formato --
        # o parser pode encontrar qualquer coisa dentro de um JSON de terceiro.
        # `reason` (o nome da classe) basta para saber ONDE olhar. O
        # `log.exception` emite o traceback, que desde a TEC-293 leva pilha,
        # cadeia e tipo -- e nunca a mensagem, que era por onde o texto do
        # parser sobre o envelope de terceiro chegava ao log.
        log.exception(
            "webhook.error",
            reason=type(exc).__name__,
            payload_sha256=payload_sha256,
        )
        return Response(status_code=200)

    if not parsed:
        log.info("webhook.ignored", reason="no_inbound_messages")
        return Response(status_code=200)

    # A falha do `ingest` sobe deliberadamente. Se o `_persist` levanta
    # (Postgres fora do ar, pool esgotado, statement timeout), nada foi gravado
    # -- ele commita o lote inteiro numa transacao so -- e portanto nao ha linha
    # para o sweeper achar. Engolir isso num 200 faria a Meta marcar a entrega
    # como bem-sucedida e a mensagem sumiria para sempre. Deixar subir vira 500
    # e a Meta re-entrega; sem risco de duplicata, justamente porque nada foi
    # escrito. Abaixo do `_persist` nada levanta: o `_try_enqueue` engole tanto a
    # falha do enqueue quanto a da virada de status, porque de la em diante as
    # linhas ja estao commitadas e um 500 provocaria a re-entrega de um payload
    # ja gravado -- exatamente a duplicata que este desenho existe para evitar.
    # O `except` abaixo so registra e re-levanta: nao muda o 500, so garante que
    # a falha mais critica da rota nao saia apenas como traceback do uvicorn.
    try:
        await service.ingest(parsed)
    except Exception as exc:
        # `detail` vem curado por `motivo_do_erro_de_banco`, e desde a TEC-293
        # o `log.exception` abaixo nao contradiz mais essa curadoria: o
        # traceback leva pilha, cadeia e tipo, nunca a mensagem. Ate entao ele
        # despejava o `IntegrityError: ... DETAIL: ...` do asyncpg -- que
        # `hide_parameters` nao alcanca, porque a linha `DETAIL` e escrita pelo
        # servidor -- ao lado do `detail` curado, e o vazamento liquido deste
        # ponto era o mesmo de antes da curadoria.
        #
        # Isso vale so ate aqui. O `raise` logo abaixo poe a excecao para subir,
        # e quem a pega e o uvicorn -- fora do structlog, fora do
        # `_sanear_traceback` -- que a loga de novo crua, com a mensagem
        # inteira. A curadoria protege o evento `webhook.persist_failed`; nao
        # protege o que o uvicorn escreve depois dele.
        log.exception(
            "webhook.persist_failed",
            reason=type(exc).__name__,
            detail=motivo_do_erro_de_banco(exc),
            remote_ip=remote_ip,
            payload_sha256=payload_sha256,
        )
        raise

    return Response(status_code=200)

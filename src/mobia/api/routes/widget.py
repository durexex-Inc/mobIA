"""O canal web: WebSocket do widget do site. TEC-124, RF-01.

**Nao ha pipeline proprio aqui.** O endpoint monta um `ParsedMessage` e chama
o mesmo `IngestionService` do webhook com `channel=CANAL_WEB`. Com isso o
canal herda, sem escrever linha nenhuma: persistir antes de enfileirar, o rate
limit por numero, o debounce de rajada, o atalho que fura a janela para
opt-out e pedido de humano, e a contagem de duplicata descartada.

**Nenhuma chamada a modelo acontece dentro do ciclo da conexao**, pelo mesmo
motivo que a RN-01.2 escreve para o webhook.

O `id` do frame vira `provider_message_id`: e ele que faz o reenvio depois de
uma queda cair na UNIQUE `(channel, provider_message_id)` que ja existe --
dedup sem codigo novo, pelo mesmo mecanismo que absorve a reentrega da Meta.

**O id da sessao nunca viaja em URL.** Ele e portador anonimo -- quem o tiver
le aquela conversa --, e numa query string entraria em log de acesso, em
`Referer` e no historico do navegador. Por isso ele vai no primeiro frame, na
ida e na retomada.
"""

import asyncio
import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from mobia.api.deps import get_ingestion_service
from mobia.app.config import get_settings
from mobia.app.logging import correlation_id
from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.historico import historico_da_sessao
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.outbound.web import canal_da_sessao
from mobia.infra.db import get_sessionmaker, motivo_do_erro_de_banco

log = structlog.get_logger(__name__)
router = APIRouter(tags=["widget"])

TIPO_OLA = "ola"
TIPO_MENSAGEM = "mensagem"

# 1002 e o codigo de violacao de protocolo do RFC 6455. Frame fora de ordem,
# JSON invalido e sessao que nao e UUID caem todos aqui: sao cliente quebrado,
# nao erro nosso, e nao ha frame de erro que ajude quem os manda.
CODIGO_PROTOCOLO = 1002

# 1011 e "condicao inesperada no servidor" do RFC 6455: o banco ou o Redis
# fora, que nao e culpa de quem esta do outro lado.
CODIGO_INDISPONIVEL = 1011

# Quanto esperar o Redis confirmar o `SUBSCRIBE`. Sem confirmacao a volta nao e
# garantida, e anunciar a sessao seria prometer uma conversa que talvez so
# funcione num sentido.
SEGUNDOS_PARA_CONFIRMAR_ASSINATURA = 5.0


@router.websocket("/widget/chat")
async def chat(
    websocket: WebSocket,
    service: IngestionService = Depends(get_ingestion_service),
) -> None:
    correlation_id.set(str(uuid.uuid4()))
    await websocket.accept()

    identidade = await _identificar(websocket)
    if identidade is None:
        return
    sessao, retomada = identidade

    pool = getattr(websocket.app.state, "redis_pool", None)
    if pool is None:
        # Sem Redis nao ha volta possivel. A entrada ainda funcionaria, mas a
        # visitante falaria sozinha -- melhor recusar do que simular
        # atendimento.
        log.error("widget.sem_redis", sessao=sessao)
        await websocket.close(code=CODIGO_INDISPONIVEL)
        return

    # Uma conexao do pool por aba aberta, enquanto ela viver: e o preco do
    # pub/sub, e o que dimensiona o pool do Redis quando o widget escalar.
    assinatura = pool.pubsub()
    try:
        # **Assina ANTES de anunciar a sessao, e espera o Redis confirmar.**
        # Com a ordem inversa, uma resposta publicada logo depois do anuncio
        # podia chegar ao Redis antes do `SUBSCRIBE` -- e pub/sub nao guarda
        # nada para quem ainda nao ouve. Assim, quem recebeu o frame `sessao`
        # ja tem para onde a publicacao ir.
        await assinatura.subscribe(canal_da_sessao(sessao))
        if await assinatura.get_message(timeout=SEGUNDOS_PARA_CONFIRMAR_ASSINATURA) is None:
            log.error("widget.assinatura_sem_confirmacao", sessao=sessao)
            await websocket.close(code=CODIGO_INDISPONIVEL)
            return

        await _anunciar(websocket, sessao, retomada)
        log.info("widget.conectado", sessao=sessao, retomada=retomada)

        entrada = asyncio.create_task(_ler_do_lead(websocket, service, sessao))
        saida = asyncio.create_task(_escrever_do_agente(websocket, assinatura))
        try:
            # A primeira que terminar decide: a visitante fechou a aba, ou o
            # socket morreu escrevendo. A outra nao tem mais para quem falar.
            await asyncio.wait({entrada, saida}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for tarefa in (entrada, saida):
                tarefa.cancel()
            # `return_exceptions` para o cancelamento de uma nao esconder a
            # excecao da outra, nem vazar "Task exception was never
            # retrieved" no log.
            await asyncio.gather(entrada, saida, return_exceptions=True)
    finally:
        # Solta a conexao do pool. Sem isto, cada aba fechada vazaria uma
        # conexao do Redis para sempre.
        await assinatura.aclose()
        log.info("widget.desconectado", sessao=sessao)


async def _identificar(websocket: WebSocket) -> tuple[str, bool] | None:
    """O primeiro frame decide a identidade, e nada mais passa antes dele.

    Devolve a sessao e se ela e retomada, sem responder nada: o anuncio fica
    para depois da assinatura -- ver `chat`.
    """
    try:
        primeiro = await _receber_json(websocket)
    except WebSocketDisconnect:
        return None
    except json.JSONDecodeError:
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None

    if not isinstance(primeiro, dict) or primeiro.get("tipo") != TIPO_OLA:
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None

    bruto = primeiro.get("sessao")
    if bruto is None:
        sessao = str(uuid.uuid4())
        retomada = False
    else:
        try:
            # `str(UUID(...))` normaliza: maiuscula e chaves entram, e a
            # `conversation_key` gravada e sempre a mesma forma. Sem isso a
            # mesma sessao escrita de dois jeitos viraria duas conversas.
            sessao = str(uuid.UUID(str(bruto)))
        except ValueError:
            # Aceitar qualquer string aqui deixaria o cliente escolher a
            # `conversation_key` -- inclusive a de outra conversa.
            await websocket.close(code=CODIGO_PROTOCOLO)
            return None
        retomada = True

    return sessao, retomada


async def _anunciar(websocket: WebSocket, sessao: str, retomada: bool) -> None:
    await websocket.send_json({"tipo": "sessao", "sessao": sessao})

    if retomada:
        falas = await historico_da_sessao(
            get_sessionmaker(),
            canal=CANAL_WEB,
            sessao=sessao,
            limite=get_settings().historico_do_widget_mensagens,
        )
        await websocket.send_json(
            {
                "tipo": "historico",
                "mensagens": [
                    {"papel": fala.papel, "texto": fala.texto, "em": fala.em.isoformat()}
                    for fala in falas
                ],
            }
        )


async def _escrever_do_agente(websocket: WebSocket, assinatura: Any) -> None:
    """Repassa ao navegador o que o worker publicou para esta sessao."""
    async for evento in assinatura.listen():
        if evento.get("type") != "message":
            continue
        dado = evento["data"]
        await websocket.send_text(dado.decode() if isinstance(dado, bytes) else dado)


async def _ler_do_lead(websocket: WebSocket, service: IngestionService, sessao: str) -> None:
    teto = get_settings().tamanho_maximo_do_texto_do_widget

    while True:
        try:
            frame = await _receber_json(websocket)
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        if not isinstance(frame, dict) or frame.get("tipo") != TIPO_MENSAGEM:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        texto = str(frame.get("texto") or "")
        if not texto.strip():
            # Nao vira linha: um turno sobre texto vazio custaria chamada paga
            # ao modelo para responder ao nada.
            await websocket.send_json({"tipo": "erro", "motivo": "texto_vazio"})
            continue
        if len(texto) > teto:
            # Recusa SEM fechar: derrubar o socket transformaria um Ctrl+V
            # infeliz em perda da conversa inteira.
            await websocket.send_json({"tipo": "erro", "motivo": "texto_longo_demais"})
            continue

        # Sem `id` o cliente funciona, so nao ganha a dedup da UNIQUE.
        identificador = str(frame.get("id") or uuid.uuid4())
        try:
            await service.ingest(
                [
                    ParsedMessage(
                        provider_message_id=identificador,
                        sender_external_id=sessao,
                        recipient_external_id=REMETENTE_DO_WIDGET,
                        content_type=MessageContentType.TEXTO,
                        text_body=texto,
                        raw_payload=frame,
                    )
                ],
                channel=CANAL_WEB,
            )
        except Exception as exc:
            # **Aqui a falha NAO sobe, ao contrario do webhook.** La ela vira
            # 500 de proposito, para a Meta reentregar -- e o preco aceito e o
            # uvicorn logar a excecao crua, com a linha `DETAIL` do asyncpg,
            # por fora do saneamento da TEC-293 (ver `api/routes/whatsapp.py`).
            # O widget nao precisa pagar esse preco: o equivalente da
            # reentrega e o cliente reenviar com o mesmo `id`, e a UNIQUE
            # segura a duplicata. O 1011 e o sinal para ele reconectar; o
            # `recebido` nunca chega, entao ele sabe que aquela fala nao ficou.
            log.exception(
                "widget.persist_failed",
                sessao=sessao,
                reason=type(exc).__name__,
                detail=motivo_do_erro_de_banco(exc),
            )
            await websocket.close(code=CODIGO_INDISPONIVEL)
            return
        await websocket.send_json({"tipo": "recebido", "id": identificador})


async def _receber_json(websocket: WebSocket) -> Any:
    """Le um frame de texto e o interpreta.

    `receive_text` e nao `receive_json`: o do Starlette levanta
    `json.JSONDecodeError` do mesmo jeito, mas passar por aqui deixa o
    tratamento num lugar so.
    """
    return json.loads(await websocket.receive_text())

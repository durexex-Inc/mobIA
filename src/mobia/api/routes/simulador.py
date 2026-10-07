"""O simulador de WhatsApp: conversar com o agente sem a Cloud API da Meta.

Ferramenta de desenvolvimento. Existe porque ativar a integracao real (`
WHATSAPP_ACCESS_TOKEN`, numero aprovado, webhook publico) e um passo que nao
se quer dar so para testar o agente localmente.

**Nao fala com a Meta.** O canal da mensagem gravada e `CANAL_SIMULADOR`
("simulador"), nao `CANAL_WHATSAPP` -- usar o canal real faria o roteador de
saida (`RoteadorPorCanal`) escolher `WhatsAppOutbound`, que tenta entregar a
resposta do agente batendo na Cloud API de verdade (ver a pesquisa que
embasou este desenho). O canal do simulador tem o MESMO adaptador de saida do
widget web (`WebOutbound`/`WebIndicador`, registrados em `workers/main.py`):
publica a resposta num canal Redis pub/sub que este mesmo WebSocket escuta.

**A identidade e o telefone digitado, nao uma sessao anonima.** Ao contrario
do widget (`api/routes/widget.py`), que gera um UUID de sessao no primeiro
frame, aqui o primeiro frame traz o telefone -- normalizado pela mesma funcao
que o WhatsApp usa (`identidade/telefone.py::normalizar`) -- e ele proprio e a
`conversation_key` (via `chave_de`). Reconectar com o MESMO telefone sempre
retoma a mesma conversa, sem cookie nem sessao: e o analogo do wa_id da Meta
ser estavel entre o app do WhatsApp e reaberto.

**So roda fora de producao.** `settings.em_producao` fecha o handshake antes
do `accept` -- esta rota nao verifica Origin nem exige credencial nenhuma, e
e exatamente por isso que ela nao pode existir num ambiente real: qualquer um
que a alcance conversa com o agente em nome de qualquer telefone.

**Reaproveita os pedacos de `widget.py` que nao sao especificos de sessao
anonima** (`Atividade`, a vigia de ociosidade, a leitura/escrita de frame, os
codigos de fechamento) -- duplicar essas ~80 linhas so para trocar o nome do
canal seria o tipo de divergencia silenciosa que o projeto evita.
"""

import asyncio
import uuid
from contextlib import suppress

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from starlette.responses import Response

from mobia.api.central_do_widget import CentralIndisponivel, central_de
from mobia.api.deps import get_ingestion_service
from mobia.api.middleware import resolver_ip
from mobia.api.routes.widget import (
    CODIGO_INDISPONIVEL,
    CODIGO_PROTOCOLO,
    CODIGO_TENTE_MAIS_TARDE,
    TAMANHO_MAXIMO_DO_ID,
    Atividade,
    FrameInvalido,
    _escrever_do_agente,
    _falha_de,
    _receber_json,
    _vigiar_ociosidade,
)
from mobia.app.config import get_settings
from mobia.app.logging import correlation_id
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_IP
from mobia.domain.messages.canais import CANAL_SIMULADOR, REMETENTE_DO_SIMULADOR
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.historico import historico_da_sessao
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker, motivo_do_erro_de_banco
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_ip, consumir, segundos_ate_caber

log = structlog.get_logger(__name__)
router = APIRouter(tags=["simulador"])

TIPO_OLA = "ola"
TIPO_MENSAGEM = "mensagem"


async def _cabe_no_limite_por_ip(websocket: WebSocket) -> tuple[bool, str | None]:
    """Mesma guarda e mesmo teto de `widget.py`, com o nome da rota certo no log."""
    settings = get_settings()
    pool = getattr(websocket.app.state, "redis_pool", None)
    limite = settings.rate_limit_requisicoes_por_ip_por_minuto
    if limite <= 0:
        return True, None

    ip = resolver_ip(
        socket_host=websocket.client.host if websocket.client else None,
        forwarded_for=websocket.headers.get("x-forwarded-for"),
        confiar_em_forwarded_for=settings.confiar_em_forwarded_for,
    )
    if ip is None:
        return True, None

    chave = chave_de_ip(ip)
    consumo = await consumir(pool, chave=chave, limite=limite, janela_segundos=JANELA_DE_UM_MINUTO)
    if consumo.permitido:
        return True, None

    log.warning(
        "ratelimit.blocked",
        escopo=ESCOPO_IP,
        ip=ip,
        rota="/dev/simulador-whatsapp/chat",
        volume=consumo.volume,
        limite=limite,
    )
    await registrar_bloqueio(
        get_sessionmaker(),
        pool,
        escopo=ESCOPO_IP,
        chave=ip,
        channel="http",
        volume=consumo.volume,
        limite=limite,
    )
    return False, chave


async def _recusar_por_excesso(websocket: WebSocket, *, aguarde_segundos: int) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "tipo": "erro",
            "codigo": "muitas_tentativas",
            "mensagem": f"Muitas tentativas, aguarde {aguarde_segundos} s.",
            "aguardeSegundos": aguarde_segundos,
        }
    )
    await websocket.close(code=CODIGO_TENTE_MAIS_TARDE)


async def _recusar_por_producao(websocket: WebSocket) -> None:
    if "websocket.http.response" in websocket.scope.get("extensions", {}):
        await websocket.send_denial_response(Response(status_code=404))
        return
    await websocket.close()


async def _identificar(websocket: WebSocket) -> str | None:
    """O primeiro frame traz o telefone. Devolve a forma canonica, ou `None`."""
    try:
        primeiro = await _receber_json(websocket)
    except WebSocketDisconnect:
        return None
    except FrameInvalido:
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None

    if not isinstance(primeiro, dict) or primeiro.get("tipo") != TIPO_OLA:
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None

    bruto = primeiro.get("telefone")
    telefone = normalizar(str(bruto)) if isinstance(bruto, str) else None
    if telefone is None:
        await websocket.send_json(
            {"tipo": "erro", "codigo": "telefone_invalido", "mensagem": "Telefone invalido."}
        )
        await websocket.close(code=CODIGO_PROTOCOLO)
        return None
    return telefone


async def _anunciar(websocket: WebSocket, telefone: str, chave: str) -> None:
    await websocket.send_json({"tipo": "sessao", "telefone": telefone})
    falas = await historico_da_sessao(
        get_sessionmaker(),
        canal=CANAL_SIMULADOR,
        sessao=chave,
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


def _chave_do_id(chave: str, identificador: str) -> str:
    return f"{chave}:{identificador}"


async def _ler_do_lead(
    websocket: WebSocket,
    service: IngestionService,
    telefone: str,
    chave: str,
    atividade: Atividade,
) -> None:
    teto = get_settings().tamanho_maximo_do_texto_do_widget

    while True:
        try:
            frame = await _receber_json(websocket)
        except WebSocketDisconnect:
            return
        except FrameInvalido:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return
        atividade.tocar()

        if not isinstance(frame, dict) or frame.get("tipo") != TIPO_MENSAGEM:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        bruto_id = frame.get("id")
        if bruto_id is None:
            identificador = str(uuid.uuid4())
        elif isinstance(bruto_id, str) and 0 < len(bruto_id) <= TAMANHO_MAXIMO_DO_ID:
            identificador = bruto_id
        else:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        texto = str(frame.get("texto") or "")
        if not texto.strip():
            await websocket.send_json(
                {"tipo": "erro", "codigo": "texto_vazio", "messageId": identificador}
            )
            continue
        if len(texto) > teto:
            await websocket.send_json(
                {"tipo": "erro", "codigo": "texto_longo_demais", "messageId": identificador}
            )
            continue

        try:
            await service.ingest(
                [
                    ParsedMessage(
                        provider_message_id=_chave_do_id(chave, identificador),
                        sender_external_id=telefone,
                        recipient_external_id=REMETENTE_DO_SIMULADOR,
                        content_type=MessageContentType.TEXTO,
                        text_body=texto,
                        raw_payload={"tipo": TIPO_MENSAGEM, "id": bruto_id, "texto": texto},
                    )
                ],
                channel=CANAL_SIMULADOR,
            )
        except Exception as exc:
            log.exception(
                "simulador.persist_failed",
                telefone=telefone,
                reason=type(exc).__name__,
                detail=motivo_do_erro_de_banco(exc),
            )
            await websocket.close(code=CODIGO_INDISPONIVEL)
            return

        await websocket.send_json({"tipo": "ack", "messageId": identificador})


@router.websocket("/dev/simulador-whatsapp/chat")
async def chat(
    websocket: WebSocket,
    service: IngestionService = Depends(get_ingestion_service),
) -> None:
    correlation_id.set(str(uuid.uuid4()))

    if get_settings().em_producao:
        await _recusar_por_producao(websocket)
        return

    permitido, chave_do_limite = await _cabe_no_limite_por_ip(websocket)
    if not permitido:
        assert chave_do_limite is not None
        pool = getattr(websocket.app.state, "redis_pool", None)
        aguarde = await segundos_ate_caber(
            pool, chave=chave_do_limite, janela_segundos=JANELA_DE_UM_MINUTO
        )
        await _recusar_por_excesso(websocket, aguarde_segundos=aguarde)
        return

    await websocket.accept()

    telefone = await _identificar(websocket)
    if telefone is None:
        return
    chave = chave_de(CANAL_SIMULADOR, telefone)

    central = central_de(websocket.app)
    if central is None:
        log.error("simulador.sem_redis", telefone=telefone)
        await websocket.close(code=CODIGO_INDISPONIVEL)
        return

    try:
        fila = await central.abrir(chave)
    except CentralIndisponivel:
        log.error("simulador.central_indisponivel", telefone=telefone)
        await websocket.close(code=CODIGO_INDISPONIVEL)
        return

    try:
        async with get_sessionmaker()() as session:
            await registrar(session, CANAL_SIMULADOR, telefone)
            await session.commit()
        await _anunciar(websocket, telefone, chave)
        log.info("simulador.conectado", telefone=telefone)

        atividade = Atividade()
        entrada = asyncio.create_task(_ler_do_lead(websocket, service, telefone, chave, atividade))
        saida = asyncio.create_task(_escrever_do_agente(websocket, fila, atividade))
        vigia = asyncio.create_task(_vigiar_ociosidade(websocket, telefone, atividade))
        tarefas = (entrada, saida, vigia)
        try:
            feitas, _ = await asyncio.wait(set(tarefas), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for tarefa in tarefas:
                tarefa.cancel()
            await asyncio.gather(*tarefas, return_exceptions=True)
        falha = _falha_de(feitas)
        if falha is not None:
            raise falha
    except Exception as exc:
        log.exception(
            "simulador.falhou",
            telefone=telefone,
            reason=type(exc).__name__,
            detail=motivo_do_erro_de_banco(exc),
        )
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=CODIGO_INDISPONIVEL)
    finally:
        central.fechar(chave, fila)
        log.info("simulador.desconectado", telefone=telefone)

"""O canal web: WebSocket do widget do site. TEC-124, RF-01.

**Nao ha pipeline proprio aqui.** O endpoint monta um `ParsedMessage` e chama
o mesmo `IngestionService` do webhook com `channel=CANAL_WEB`. Com isso o
canal herda, sem escrever linha nenhuma: persistir antes de enfileirar, o rate
limit por numero, o debounce de rajada, o atalho que fura a janela para
opt-out e pedido de humano, e a contagem de duplicata descartada.

**Nenhuma chamada a modelo acontece dentro do ciclo da conexao**, pelo mesmo
motivo que a RN-01.2 escreve para o webhook.

O `id` do frame, prefixado pela sessao, vira `provider_message_id`: e ele que
faz o reenvio depois de uma queda cair na UNIQUE `(channel,
provider_message_id)` que ja existe -- dedup sem codigo novo, pelo mesmo
mecanismo que absorve a reentrega da Meta. O prefixo e o que impede o id de
um visitante de colidir com o de outro; ver `_chave_do_id`.

**O id da sessao nunca viaja em URL.** Ele e portador anonimo -- quem o tiver
le aquela conversa --, e numa query string entraria em log de acesso, em
`Referer` e no historico do navegador. Por isso ele vai no primeiro frame, na
ida e na retomada.
"""

import asyncio
import json
import math
import uuid
from contextlib import suppress
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from starlette.responses import Response

from mobia.api.central_do_widget import CentralIndisponivel, central_de
from mobia.api.deps import get_ingestion_service
from mobia.api.middleware import resolver_ip
from mobia.app.config import get_settings
from mobia.app.logging import correlation_id
from mobia.domain.consentimento.repositorio import registrar as registrar_consentimento
from mobia.domain.identidade.indice import chave_de
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.identidade.telefone import extrair_telefone
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import CHANNEL_HTTP, ESCOPO_IP
from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.historico import historico_da_sessao
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker, motivo_do_erro_de_banco
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_ip, consumir

log = structlog.get_logger(__name__)
router = APIRouter(tags=["widget"])

TIPO_OLA = "ola"
TIPO_MENSAGEM = "mensagem"
TIPO_CONSENTIMENTO = "consentimento"

# 1002 e o codigo de violacao de protocolo do RFC 6455. Frame fora de ordem,
# JSON invalido e sessao que nao e UUID caem todos aqui: sao cliente quebrado,
# nao erro nosso, e nao ha frame de erro que ajude quem os manda.
CODIGO_PROTOCOLO = 1002

# 1011 e "condicao inesperada no servidor" do RFC 6455: o banco ou o Redis
# fora, que nao e culpa de quem esta do outro lado.
CODIGO_INDISPONIVEL = 1011


# Teto do `id` que o cliente escolhe. A coluna e `String(255)` e a chave gravada
# leva a sessao na frente (36 caracteres e o separador), entao 128 deixa folga
# sem apertar nenhum formato razoavel -- um UUID tem 36.
TAMANHO_MAXIMO_DO_ID = 128

# Teto do aviso de privacidade que o cliente diz ter exibido. A coluna e
# `Text` e nao estoura, mas o frame e entrada externa: sem teto, um cliente
# quebrado grava megabytes numa tabela que existe para ser lida em auditoria.
# 4000 cabe qualquer aviso de privacidade real com folga larga.
TAMANHO_MAXIMO_DO_AVISO = 4000


@router.websocket("/widget/chat")
async def chat(
    websocket: WebSocket,
    service: IngestionService = Depends(get_ingestion_service),
) -> None:
    # **Este `set()` FICA, e o irmao dele em `whatsapp.py` saiu na TEC-368 --
    # a assimetria e obrigatoria, nao descuido.** O `CorrelacaoDeRequisicao`
    # preenche o `correlation_id` de toda rota HTTP, e por isso o webhook nao
    # precisa mais do seu. Aqui o escopo e `websocket`, e `BaseHTTPMiddleware`
    # devolve cedo para todo escopo que nao seja `http`: este handshake nunca
    # passa por middleware nenhum. Apagar por simetria com o webhook tira a
    # correlacao do widget inteiro, sem nada reprovar.
    correlation_id.set(str(uuid.uuid4()))

    pool = getattr(websocket.app.state, "redis_pool", None)
    if not await _cabe_no_limite_por_ip(websocket, pool):
        await _recusar_por_excesso(websocket)
        return

    await websocket.accept()

    identidade = await _identificar(websocket)
    if identidade is None:
        return
    sessao, retomada = identidade
    # TEC-203. O servidor trata a sessao pela chave dela, como toda conversa;
    # o navegador segue recebendo a sessao crua, que e a credencial dele. A
    # central assina pelo mesmo `canal_da_sessao(chave)` em que `WebOutbound`
    # publica -- o `para` do payload e o `conversation_key`, que e a chave.
    chave = chave_de(CANAL_WEB, sessao)

    central = central_de(websocket.app)
    if central is None:
        # Sem Redis nao ha volta possivel. A entrada ainda funcionaria, mas a
        # visitante falaria sozinha -- melhor recusar do que simular
        # atendimento.
        log.error("widget.sem_redis", sessao=sessao)
        await websocket.close(code=CODIGO_INDISPONIVEL)
        return

    try:
        # **Registra na central ANTES de anunciar a sessao.** `abrir` so
        # devolve a fila depois de a central estar ouvindo o Redis, entao quem
        # recebeu o frame `sessao` ja tem para onde a publicacao ir. Com a
        # ordem inversa, uma resposta publicada logo depois do anuncio podia
        # chegar antes de haver quem ouvisse -- e pub/sub nao guarda nada.
        fila = await central.abrir(chave)
    except CentralIndisponivel:
        log.error("widget.central_indisponivel", sessao=sessao)
        await websocket.close(code=CODIGO_INDISPONIVEL)
        return

    try:
        await _anunciar(websocket, sessao, chave, retomada)
        log.info("widget.conectado", sessao=sessao, retomada=retomada)

        entrada = asyncio.create_task(_ler_do_lead(websocket, service, sessao))
        saida = asyncio.create_task(_escrever_do_agente(websocket, fila))
        try:
            # A primeira que terminar decide: a visitante fechou a aba, ou o
            # socket morreu escrevendo. A outra nao tem mais para quem falar.
            feitas, _ = await asyncio.wait({entrada, saida}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for tarefa in (entrada, saida):
                tarefa.cancel()
            # O `gather` so recolhe: sem ele a tarefa cancelada vazaria "Task
            # exception was never retrieved" no log. Ele NAO e quem expoe a
            # falha -- `return_exceptions` a devolveria numa lista que
            # ninguem le. Quem expoe e a checagem logo abaixo, sobre a tarefa
            # que terminou primeiro.
            await asyncio.gather(entrada, saida, return_exceptions=True)
        falha = _falha_de(feitas)
        if falha is not None:
            raise falha
    except Exception as exc:
        # O anuncio (a leitura do historico) e as duas tarefas caem aqui. Sem
        # este ramo a excecao escapava do endpoint e o uvicorn a logava crua
        # -- ou, vinda de uma tarefa, sumia no `gather` e o socket fechava sem
        # codigo, com o cliente vendo 1006 e o servidor sem rastro nenhum.
        log.exception(
            "widget.falhou",
            sessao=sessao,
            reason=type(exc).__name__,
            detail=motivo_do_erro_de_banco(exc),
        )
        with suppress(RuntimeError, WebSocketDisconnect):
            # O socket pode ja ter ido embora; ai nao ha a quem avisar.
            await websocket.close(code=CODIGO_INDISPONIVEL)
    finally:
        # Sem isto a central guardaria a fila de toda aba que ja fechou.
        central.fechar(chave, fila)
        log.info("widget.desconectado", sessao=sessao)


async def _recusar_por_excesso(websocket: WebSocket) -> None:
    """Recusa o handshake com 429 e `Retry-After`, a mesma resposta do middleware.

    **Nao `close()` antes do `accept`.** Foi a primeira versao, com o codigo
    1013 ("tente mais tarde"), e o teste passava olhando o evento ASGI. So que
    o uvicorn transforma o fechamento antes do `accept` em HTTP **403** nas
    tres implementacoes de WebSocket, e o navegador ve `onclose` 1006: o
    cliente lia "proibido, nao tente de novo" onde devia ler "espere".

    `send_denial_response` precisa da extensao `websocket.http.response`, que o
    uvicorn anuncia. Um servidor que nao a anuncie cai no `close()`, e ai o 403
    e o melhor que se consegue -- continua recusando, so que com a palavra
    errada.
    """
    if "websocket.http.response" in websocket.scope.get("extensions", {}):
        await websocket.send_denial_response(
            Response(
                status_code=429,
                headers={"Retry-After": str(math.ceil(JANELA_DE_UM_MINUTO))},
            )
        )
        return
    await websocket.close()


def _falha_de(feitas: set[asyncio.Task[None]]) -> BaseException | None:
    """A excecao de verdade de quem terminou primeiro, se houve uma.

    `WebSocketDisconnect` nao conta: e a visitante indo embora, o fim normal
    de toda conversa, e logar isso como falha sujaria o log a cada aba fechada.
    """
    for tarefa in feitas:
        if tarefa.cancelled():
            continue
        excecao = tarefa.exception()
        if excecao is not None and not isinstance(excecao, WebSocketDisconnect):
            return excecao
    return None


async def _cabe_no_limite_por_ip(websocket: WebSocket, pool: Any) -> bool:
    """O limite da RNF-16 aplicado ao aperto de mao.

    **Mora aqui, e nao no middleware, porque o middleware nao alcanca.**
    `RateLimitPorIP` e `BaseHTTPMiddleware`, e essa classe devolve cedo para
    todo escopo que nao seja `http`: o handshake de um `ws://` nunca passa por
    ela. Ate a TEC-124 o comentario de `create_app` dizia o contrario -- que
    aplicar o middleware por omissao evitava esquecer o widget --, e era
    exatamente esse o erro que ele deixava acontecer. A Emenda E-01 da RNF-16
    esta certa ao escrever "toda rota HTTP restante": o widget nao e uma.

    Mesmo limite e mesma janela do middleware, de proposito: dois tetos para o
    mesmo IP seriam duas coisas para manter em sincronia.
    """
    settings = get_settings()
    limite = settings.rate_limit_requisicoes_por_ip_por_minuto
    if limite <= 0:
        return True

    ip = resolver_ip(
        socket_host=websocket.client.host if websocket.client else None,
        forwarded_for=websocket.headers.get("x-forwarded-for"),
        confiar_em_forwarded_for=settings.confiar_em_forwarded_for,
    )
    if ip is None:
        return True

    consumo = await consumir(
        pool, chave=chave_de_ip(ip), limite=limite, janela_segundos=JANELA_DE_UM_MINUTO
    )
    if consumo.permitido:
        return True

    log.warning(
        "ratelimit.blocked",
        escopo=ESCOPO_IP,
        ip=ip,
        rota="/widget/chat",
        volume=consumo.volume,
        limite=limite,
    )
    await registrar_bloqueio(
        get_sessionmaker(),
        pool,
        escopo=ESCOPO_IP,
        chave=ip,
        channel=CHANNEL_HTTP,
        volume=consumo.volume,
        limite=limite,
    )
    return False


async def _identificar(websocket: WebSocket) -> tuple[str, bool] | None:
    """O primeiro frame decide a identidade, e nada mais passa antes dele.

    Devolve a sessao e se ela e retomada, sem responder nada: o anuncio fica
    para depois do registro na central -- ver `chat`.
    """
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


async def _anunciar(websocket: WebSocket, sessao: str, chave: str, retomada: bool) -> None:
    await websocket.send_json({"tipo": "sessao", "sessao": sessao})

    if retomada:
        falas = await historico_da_sessao(
            get_sessionmaker(),
            canal=CANAL_WEB,
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


async def _registrar_consentimento(
    websocket: WebSocket, frame: dict[str, Any], sessao: str
) -> None:
    """Grava o consentimento de marketing e confirma. TEC-363, RN-FE-20.2.

    **Nenhuma recusa aqui fecha o socket**, ao contrario do frame
    desconhecido. Derrubar transformaria um aviso mal formado -- ou um banco
    indisponivel -- em perda da conversa inteira, que e o oposto do que esta
    rota existe para proteger. E o mesmo criterio do `texto_longo_demais`.

    **A recusa da visitante (`marketing: false`) NAO e uma dessas recusas**:
    ela e gravada, porque e evidencia de que o aviso foi exibido e de que a
    resposta foi nao. Ver a D3 do desenho.
    """
    chave = chave_de(CANAL_WEB, sessao)
    marketing = frame.get("marketing")
    if not isinstance(marketing, bool):
        # `str()` ou truthiness aceitariam `"nao"` e `0` como resposta, e uma
        # string nao vazia viraria consentimento. Num registro que serve de
        # prova, coagir e pior que recusar.
        await websocket.send_json({"tipo": "erro", "motivo": "consentimento_invalido"})
        return

    texto = str(frame.get("textoExibido") or "")
    if not texto.strip():
        # Sem o texto nao ha evidencia: o registro diria "aceitou" sem dizer
        # aceitou o que. Gravar assim seria fingir que ha prova.
        await websocket.send_json({"tipo": "erro", "motivo": "aviso_ausente"})
        return
    if len(texto) > TAMANHO_MAXIMO_DO_AVISO:
        await websocket.send_json({"tipo": "erro", "motivo": "aviso_longo_demais"})
        return

    try:
        await registrar_consentimento(
            get_sessionmaker(),
            channel=CANAL_WEB,
            conversation_key=chave,
            marketing=marketing,
            texto_exibido=texto,
            exibido_em=_instante_do_cliente(frame.get("exibidoEm")),
        )
    except Exception as exc:
        log.exception(
            "widget.consentimento_falhou",
            sessao=sessao,
            reason=type(exc).__name__,
            detail=motivo_do_erro_de_banco(exc),
        )
        await websocket.send_json({"tipo": "erro", "motivo": "consentimento_nao_registrado"})
        return

    # O ack nao esta no texto da card, e existe porque sem ele o cliente ou
    # assume que deu certo -- e perde registros em silencio -- ou reenvia
    # sempre. Frame proprio e nao `recebido`, que carrega um `id` de mensagem
    # que consentimento nao tem.
    log.info("widget.consentimento_registrado", sessao=sessao, marketing=marketing)
    await websocket.send_json({"tipo": "consentimento_registrado"})


def _instante_do_cliente(bruto: Any) -> datetime | None:
    """O `exibidoEm` do frame, quando ele for ISO-8601 legivel.

    Ilegivel vira `None` em vez de recusar o consentimento: o carimbo e
    diagnostico, e a coluna que serve de evidencia e o `created_at` do
    Postgres. Perder o registro por causa de um campo auxiliar seria trocar o
    que importa pelo que nao importa.
    """
    if not isinstance(bruto, str):
        return None
    try:
        return datetime.fromisoformat(bruto)
    except ValueError:
        return None


async def _escrever_do_agente(websocket: WebSocket, fila: asyncio.Queue[str]) -> None:
    """Repassa ao navegador o que o worker publicou para esta sessao."""
    while True:
        await websocket.send_text(await fila.get())


async def _ler_do_lead(websocket: WebSocket, service: IngestionService, sessao: str) -> None:
    teto = get_settings().tamanho_maximo_do_texto_do_widget
    chave = chave_de(CANAL_WEB, sessao)

    while True:
        try:
            frame = await _receber_json(websocket)
        except WebSocketDisconnect:
            return
        except FrameInvalido:
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        if not isinstance(frame, dict):
            await websocket.close(code=CODIGO_PROTOCOLO)
            return

        if frame.get("tipo") == TIPO_CONSENTIMENTO:
            await _registrar_consentimento(websocket, frame, sessao)
            continue

        # Todo frame que nao e `mensagem` nem `consentimento` continua
        # derrubando com 1002: e cliente quebrado, e nao ha frame de erro que
        # ajude quem o manda.
        if frame.get("tipo") != TIPO_MENSAGEM:
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

        bruto_id = frame.get("id")
        if bruto_id is None:
            # Sem `id` o cliente funciona, so nao ganha a dedup da UNIQUE.
            identificador = str(uuid.uuid4())
        elif isinstance(bruto_id, str) and 0 < len(bruto_id) <= TAMANHO_MAXIMO_DO_ID:
            identificador = bruto_id
        else:
            # Coagir com `str()` aceitaria `5` e `true` como ids; e um id acima
            # do teto estourava `DataError` na coluna e virava 1011 -- um
            # codigo de erro de SERVIDOR sobre o qual o cliente reenviaria o
            # mesmo id para sempre.
            await websocket.close(code=CODIGO_PROTOCOLO)
            return
        try:
            gravadas = await service.ingest(
                [
                    ParsedMessage(
                        provider_message_id=_chave_do_id(sessao, identificador),
                        sender_external_id=sessao,
                        recipient_external_id=REMETENTE_DO_WIDGET,
                        content_type=MessageContentType.TEXTO,
                        text_body=texto,
                        # So as chaves do protocolo, e nao o frame inteiro:
                        # o `texto` tem teto, uma chave extra nao tinha
                        # nenhum alem dos 16 MB do uvicorn, e sessao e de
                        # graca -- gravar tudo deixava encher a coluna de lixo.
                        raw_payload={"tipo": TIPO_MENSAGEM, "id": bruto_id, "texto": texto},
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

        # TEC-129, D3. So quando a linha e NOVA: um reenvio que a UNIQUE
        # descartou volta vazio de `ingest`, e o vinculo da primeira vez ja
        # foi tentado. E so depois do `ingest`, porque o vinculo tem FK para a
        # mensagem que o sustenta.
        telefone = extrair_telefone(texto) if gravadas else None
        if telefone is not None:
            try:
                criou = await vincular_sessao(
                    get_sessionmaker(),
                    channel=CANAL_WEB,
                    conversation_key=chave,
                    telefone=telefone,
                    message_id=gravadas[0],
                )
            except Exception as exc:
                # A mensagem JA esta persistida, e e ela a promessa desta rota.
                # Fechar o socket aqui faria o cliente reconectar e reenviar um
                # id que a UNIQUE descarta -- e o vinculo nunca mais seria
                # tentado. Perder o vinculo e o custo menor: o WhatsApp dessa
                # pessoa so nao herda o que ela disse no site.
                log.exception(
                    "widget.vinculo_falhou",
                    sessao=sessao,
                    reason=type(exc).__name__,
                    detail=motivo_do_erro_de_banco(exc),
                )
            else:
                if not criou:
                    # Sessao ja vinculada: o primeiro telefone vale. O numero
                    # nao vai no log -- a mascara de PII cobre corridas de
                    # digitos, mas nao ha por que confiar nela para isto.
                    log.info("widget.vinculo_mantido", sessao=sessao)
        # `recebido` confirma o ID, e nao o conteudo: um reenvio com o mesmo id
        # e descartado pela UNIQUE e ainda assim confirmado, que e o que torna
        # o reenvio idempotente. O custo e que um cliente que reuse um id para
        # texto DIFERENTE ve a confirmacao e perde o texto novo -- defeito do
        # cliente, mas silencioso deste lado.
        await websocket.send_json({"tipo": "recebido", "id": identificador})


def _chave_do_id(sessao: str, identificador: str) -> str:
    """O `provider_message_id` de uma mensagem do widget: o id DENTRO da sessao.

    O id vem do cliente, e a UNIQUE `(channel, provider_message_id)` e global
    ao canal. Gravado cru, o `"m-1"` de um visitante colidia com o `"m-1"` de
    outro, e o segundo perdia a mensagem recebendo `recebido`. Prefixado pela
    sessao, a dedup continua fazendo o que existe para fazer -- absorver o
    reenvio da MESMA pagina depois de uma queda -- e so isso.
    """
    return f"{sessao}:{identificador}"


class FrameInvalido(Exception):
    """O frame nao e texto JSON legivel. Quem pega fecha com 1002."""


async def _receber_json(websocket: WebSocket) -> Any:
    """Le um frame de texto e o interpreta, ou levanta `FrameInvalido`.

    **`receive` e nao `receive_text`.** O do Starlette faz `message["text"]`, e
    um frame BINARIO so traz `bytes`: o `KeyError` escapava das duas leituras
    -- antes do cumprimento como traceback cru do uvicorn, depois dele matando
    a tarefa de entrada sem fechar o socket. Aqui o frame sem texto vira o
    mesmo erro de protocolo que o JSON quebrado.

    `RecursionError` entra junto com `ValueError` (de que `JSONDecodeError` e
    subclasse): e o que `json.loads` levanta para aninhamento profundo, e ele
    escapava pelo mesmo caminho.
    """
    mensagem = await websocket.receive()
    if mensagem["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(mensagem.get("code", 1000))
    texto = mensagem.get("text")
    if texto is None:
        raise FrameInvalido("frame binario")
    try:
        return json.loads(texto)
    except (ValueError, RecursionError) as exc:
        raise FrameInvalido(type(exc).__name__) from exc

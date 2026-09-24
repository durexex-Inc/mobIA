"""Os middlewares HTTP: limite por IP (TEC-205, RNF-16) e correlacao (TEC-368).

O limitador foi o primeiro middleware do projeto -- ate a TEC-205 `create_app`
so fazia `include_router` e `/health`. Ate a TEC-368 o `correlation_id` era
setado dentro de dois handlers, e so deles; agora quem o preenche e o
`CorrelacaoDeRequisicao`, para toda rota HTTP.

**A ordem em que os dois entram em `create_app` importa, e esta explicada la.**
"""

import math
import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mobia.app.config import get_settings
from mobia.app.logging import correlation_id
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import CHANNEL_HTTP, ESCOPO_IP
from mobia.infra.db import get_sessionmaker
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_ip, consumir

log = structlog.get_logger(__name__)

CABECALHO_DE_CORRELACAO = "X-Request-Id"

# A MESMA forma que o BFF aceita em `idDeRequisicao`
# (`frontend/src/lib/servidor/bff.ts`). Cobre UUID, ULID e os ids de
# rastreamento usuais, sem deixar passar quebra de linha nem texto livre.
#
# **As duas expressoes tem de continuar iguais, e nenhum gate liga uma a
# outra** -- sao linguagens diferentes. Se este lado ficasse mais estrito, ele
# descartaria ids que o BFF propagou, e os dois lados logariam ids diferentes
# para a MESMA requisicao: quem depurasse concluiria que sao requisicoes
# distintas. O que existe contra isso e o teste de borda dos dois lados com os
# mesmos valores (200 aceito, 201 substituido).
_FORMA_DO_ID = re.compile(r"\A[A-Za-z0-9._:-]{1,200}\Z")


def _id_de_requisicao(entrada: str | None) -> str:
    """O id que vale para esta requisicao.

    Entrada malformada e SUBSTITUIDA por um id novo, e nao recusada: ninguem
    deve perder a requisicao por causa de um cabecalho de diagnostico.
    Propaga-la sem olhar seria deixar entrada nao confiavel escrever no log.
    """
    if entrada and _FORMA_DO_ID.match(entrada):
        return entrada
    return str(uuid.uuid4())


class CorrelacaoDeRequisicao(BaseHTTPMiddleware):
    """Preenche `correlation_id` em toda requisicao HTTP (TEC-368, RNF-34).

    Com o ContextVar preenchido aqui, todo evento do structlog passa a carregar
    o id sem que handler nenhum precise saber disso -- e o processador
    `_add_correlation_id`, em `app/logging.py`, que o injeta.

    **Nao ha rota isenta**, ao contrario do limitador: correlacao nao recusa
    ninguem e custa um `uuid4`, entao nao existe o caso de "quem precisa ficar
    de fora".

    **Nao cobre o WebSocket do widget.** `BaseHTTPMiddleware` devolve cedo para
    todo escopo que nao seja `http`, entao o handshake de `/widget/chat` nunca
    passa por aqui -- e por isso o `correlation_id.set()` de
    `api/routes/widget.py` continua existindo.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        identificador = _id_de_requisicao(request.headers.get(CABECALHO_DE_CORRELACAO))

        # `reset` no `finally` e nao so `set`: na pratica o uvicorn roda cada
        # requisicao na sua propria task e as contextvars ja sao copiadas por
        # task, mas "na pratica" nao e a garantia que se quer num id que vai
        # para o log, e o custo de estar certo e uma linha.
        token = correlation_id.set(identificador)
        try:
            resposta = await call_next(request)
        finally:
            correlation_id.reset(token)

        # Devolvido tambem na resposta: sem isso, para achar o id no log era
        # preciso ja saber qual e, que e circular.
        resposta.headers[CABECALHO_DE_CORRELACAO] = identificador
        return resposta


# `chave` em `rate_limit_events` e String(64). O header e entrada externa: sem
# teto, um `X-Forwarded-For` longo viraria erro de INSERT na hora de registrar
# justamente o abuso que a coluna existe para guardar.
_TAMANHO_MAXIMO_DA_CHAVE = 64


def resolver_ip(
    *,
    socket_host: str | None,
    forwarded_for: str | None,
    confiar_em_forwarded_for: bool,
) -> str | None:
    """O endereco que o limitador conta.

    Sem confiar (o default), e o socket: nao forjavel, correto no deploy de
    hoje, que nao tem proxy. Confiando, e o ULTIMO salto de `X-Forwarded-For`
    -- o ultimo, e nao o primeiro, porque e o unico que o proxy imediato
    escreveu e portanto o unico que o cliente nao controla. Confiar no
    primeiro deixaria qualquer cliente escapar do limite com um header
    forjado, que e exatamente o abuso que esta card existe para conter.

    Devolve None quando nao ha endereco nenhum. Quem chama deixa passar: e o
    mesmo fail-open do limitador.
    """
    if confiar_em_forwarded_for and forwarded_for:
        saltos = [salto.strip() for salto in forwarded_for.split(",")]
        ultimo = next((salto for salto in reversed(saltos) if salto), None)
        if ultimo:
            return ultimo[:_TAMANHO_MAXIMO_DA_CHAVE]
    if socket_host:
        return socket_host[:_TAMANHO_MAXIMO_DA_CHAVE]
    return None


# Isentas, e cada uma por uma razao propria.
#
# `/webhooks/whatsapp`: o trafego chega todo do IP da Meta. Cem requisicoes por
# minuto ali nao conteria abuso, derrubaria operacao -- e derrubaria da pior
# forma, porque o handler responde 200 em todo caminho de rejeicao justamente
# para a Meta nao re-entregar. Um 429 e nao-2xx e provocaria o retry que o
# desenho da TEC-122 existe para evitar.
#
# `/health`: um probe de liveness que batesse acima do limite receberia 429 e
# o orquestrador reiniciaria o processo. O limitador derrubando exatamente o
# que ele deveria proteger.
#
# A comparacao e por igualdade exata sobre `request.url.path`. Montar o app
# sob um prefixo -- um ingress com rewrite, por exemplo -- faria as duas
# isencoes pararem de casar em silencio: nenhum erro, so `/health` deixando
# de ser isento, que e justamente o modo de falha caro que a isencao acima
# existe para evitar.
ROTAS_ISENTAS = frozenset({"/webhooks/whatsapp", "/health"})


class RateLimitPorIP(BaseHTTPMiddleware):
    """Cem requisicoes por minuto por IP, fora as rotas isentas.

    Recusa com 429 em vez de adiar, ao contrario do limite por numero: aqui a
    requisicao e sincrona e nao ha o que adiar sem deixar o cliente pendurado.
    A assimetria esta registrada na emenda E-01 a RNF-16.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        limite = settings.rate_limit_requisicoes_por_ip_por_minuto

        if limite <= 0 or request.url.path in ROTAS_ISENTAS:
            return await call_next(request)

        ip = resolver_ip(
            socket_host=request.client.host if request.client else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            confiar_em_forwarded_for=settings.confiar_em_forwarded_for,
        )
        if ip is None:
            return await call_next(request)

        pool = getattr(request.app.state, "redis_pool", None)
        consumo = await consumir(
            pool, chave=chave_de_ip(ip), limite=limite, janela_segundos=JANELA_DE_UM_MINUTO
        )
        if consumo.permitido:
            return await call_next(request)

        log.warning(
            "ratelimit.blocked",
            escopo=ESCOPO_IP,
            ip=ip,
            rota=request.url.path,
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
        return Response(
            status_code=429, headers={"Retry-After": str(math.ceil(JANELA_DE_UM_MINUTO))}
        )

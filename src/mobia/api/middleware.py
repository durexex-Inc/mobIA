"""O limite de requisicoes por IP (TEC-205, RNF-16).

Primeiro middleware do projeto. Ate a TEC-205 `create_app` so fazia
`include_router`, e ate o `correlation_id` era setado dentro do handler.
"""

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mobia.app.config import get_settings
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import CHANNEL_HTTP, ESCOPO_IP
from mobia.infra.db import get_sessionmaker
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_ip, consumir

log = structlog.get_logger(__name__)

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
        return Response(status_code=429, headers={"Retry-After": "60"})

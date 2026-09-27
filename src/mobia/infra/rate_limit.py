"""Limitador de volume por janela deslizante, em Redis (TEC-205, RNF-16).

Uma funcao, dois escopos: 20 mensagens por minuto por numero e 100
requisicoes por minuto por IP saem do mesmo `consumir`, mudando limite e
chave. Quem decide o que fazer com o `Consumo` e quem chama -- a ingestao
adia, o middleware recusa com 429.

**Janela deslizante e nao janela fixa.** `INCR`/`EXPIRE` por minuto de relogio
seria mais barato e mediria a coisa errada: uma rajada que cruza a borda do
minuto passa com ate o dobro do limite, e o teste do vigesimo primeiro envio
passaria a depender de onde a borda caiu. O criterio de aceite da card fala em
"no ultimo minuto", que e literalmente o que o ZSET mede.

**O relogio entra por parametro.** Sem isso, todo teste de borda teria de
dormir. Producao nunca passa `agora`.

Este e o primeiro modulo do repo a escrever chave Redis a mao -- ate aqui so
existia o namespace `arq:`, da propria biblioteca. O prefixo e `ratelimit:`.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from time import time

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

PREFIXO = "ratelimit"

# A janela dos dois limites da RNF-16. Vive aqui e nao em `Settings` porque
# nao e configuracao: e a unidade em que o requisito esta escrito ("por
# minuto"). O que e configuravel e o limite, nao a janela.
JANELA_DE_UM_MINUTO = 60.0


@dataclass(frozen=True)
class Consumo:
    """O veredito e o volume que o produziu.

    `volume` inclui a requisicao recem-avaliada: com limite 20, a vigesima
    primeira devolve `volume=21`. E esse numero que a tabela de eventos grava
    como "o volume que disparou o limite".
    """

    permitido: bool
    volume: int


def chave_de_numero(channel: str, conversation_key: str) -> str:
    return f"{PREFIXO}:numero:{channel}:{conversation_key}"


def chave_de_ip(ip: str) -> str:
    return f"{PREFIXO}:ip:{ip}"


def chave_de_guarda(escopo: str, chave: str) -> str:
    """A chave que garante UMA linha de evento por chave por janela.

    Nao reaproveita a chave do zset: aquela e um zset e esta e uma string, e o
    Redis recusaria o `SET` sobre o tipo errado com WRONGTYPE.
    """
    return f"{PREFIXO}:evento:{escopo}:{chave}"


async def consumir(
    pool: Redis | None,
    *,
    chave: str,
    limite: int,
    janela_segundos: float,
    agora: float | None = None,
) -> Consumo:
    """Conta a requisicao na janela e diz se ela cabe.

    Fail-open em toda falha -- pool ausente, Redis fora do ar. O precedente e a
    moderacao (`domain/messages/bloqueio.py`), que deixa passar quando o
    provedor nao responde: um guarda indisponivel nao pode virar a negacao de
    servico que ele existia para evitar.
    """
    if limite <= 0 or pool is None:
        return Consumo(permitido=True, volume=0)

    instante = time() if agora is None else agora

    try:
        pipe = pool.pipeline(transaction=True)
        # Inclusivo no limite inferior: o evento com score exatamente
        # `instante - janela` ja completou a janela e sai.
        pipe.zremrangebyscore(chave, "-inf", instante - janela_segundos)
        # Membro unico por requisicao. Usar o timestamp como membro colapsaria
        # duas requisicoes do mesmo instante numa so -- e e exatamente na
        # rajada que isso aconteceria.
        pipe.zadd(chave, {str(uuid.uuid4()): instante})
        # O `ZADD` acima e incondicional -- toda requisicao entra, inclusive
        # a bloqueada -- entao sem este corte uma rajada de 50.000 req/min
        # deixaria 50.000 membros vivos por ate `janela_segundos` na MESMA
        # chave, no mesmo Redis que hospeda `arq:queue` e `arq:job:*`: o
        # limitador sob ataque derrubaria a fila que ele existe para
        # proteger. A pergunta que este modulo responde e "houve mais de
        # `limite` requisicoes na janela?", e essa pergunta se decide
        # olhando so a (limite+1)-esima mais recente -- guardar mais membros
        # do que `limite + 1` nao acrescenta informacao nenhuma ao veredito.
        # Por rank e nao por score: mantem exatamente os `limite + 1` mais
        # recentes, que e o que o `ZCARD` abaixo precisa ver.
        pipe.zremrangebyrank(chave, 0, -(limite + 2))
        pipe.zcard(chave)
        # `ceil` e nao `int`: truncar 0.5 para 0 faria o EXPIRE apagar a chave
        # imediatamente e o limite nunca prenderia.
        pipe.expire(chave, math.ceil(janela_segundos))
        resultado = await pipe.execute()
    except RedisError as exc:
        log.warning("ratelimit.indisponivel", erro=type(exc).__name__)
        return Consumo(permitido=True, volume=0)

    volume = int(resultado[3])
    return Consumo(permitido=volume <= limite, volume=volume)


# TEC-346, D1. O que a visitante le quando nao da para calcular: a janela
# inteira, que e o teto do que ela pode ter de esperar.
ESPERA_PADRAO_EM_SEGUNDOS = math.ceil(JANELA_DE_UM_MINUTO)


def espera_para_caber(scores: Sequence[float], *, janela_segundos: float, agora: float) -> int:
    """Segundos ate um pedido novo caber, dados os scores do zset em ordem crescente.

    O zset guarda os `limite + 1` mais recentes -- o pedido barrado incluso,
    porque `consumir` adiciona antes de contar. O proximo cabe quando, somado a
    ele mesmo, o volume nao passa de `limite`: sobram no maximo `limite - 1`
    antigos, e para isso os dois mais velhos precisam ter saido da janela.

    Pura, para ser testada sem Redis. Nunca menos de 1: "aguarde 0 s" seria
    convite a tentar ja, e a contagem pode estar no limite exato.
    """
    if len(scores) < 2:
        return ESPERA_PADRAO_EM_SEGUNDOS
    return max(1, math.ceil(scores[1] + janela_segundos - agora))


async def segundos_ate_caber(
    pool: Redis | None,
    *,
    chave: str,
    janela_segundos: float,
    agora: float | None = None,
) -> int:
    """Le os dois scores mais velhos e devolve a espera. Redis fora: o padrao."""
    if pool is None:
        return ESPERA_PADRAO_EM_SEGUNDOS
    instante = time() if agora is None else agora
    try:
        pares = await pool.zrange(chave, 0, 1, withscores=True)
    except RedisError as exc:
        log.warning("ratelimit.indisponivel", erro=type(exc).__name__)
        return ESPERA_PADRAO_EM_SEGUNDOS
    return espera_para_caber(
        [float(score) for _, score in pares], janela_segundos=janela_segundos, agora=instante
    )

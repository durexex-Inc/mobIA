import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from mobia.app.config import get_settings
from mobia.infra.tls import exigir_redis_com_tls

PROCESS_MESSAGE_JOB = "process_message"
BAIXAR_MIDIA_JOB = "baixar_midia"


def redis_settings() -> RedisSettings:
    settings = get_settings()
    redis = RedisSettings.from_dsn(settings.redis_url)
    if settings.em_producao:
        exigir_redis_com_tls(settings.redis_url)
        # `from_dsn` liga `ssl` para rediss://; o que falta e exigir que o
        # certificado valha para o host. O default do ARQ nao verifica.
        redis.ssl_cert_reqs = "required"
        redis.ssl_check_hostname = True
    return redis


async def create_redis_pool() -> ArqRedis:
    return await create_pool(redis_settings())


async def enqueue_process_message(
    pool: ArqRedis, message_id: uuid.UUID, *, atraso_segundos: float = 0.0
) -> bool:
    """Enfileira o processamento de uma mensagem.

    Usa `_job_id` derivado do message_id: o ARQ recusa o segundo enqueue enquanto
    o job estiver pendente, entao o sweeper nao multiplica trabalho. Devolve False
    quando o job ja estava na fila.

    O ARQ tambem recusa o enqueue quando a chave de *resultado* do mesmo job id
    existe. Por isso `process_message` e registrado com `keep_result=0` em
    `workers/main.py`: sem isso, o resultado de um job que terminou bloquearia
    todo re-enqueue do sweeper pela hora seguinte.

    `atraso_segundos` e a janela de debounce da RN-01.6 (TEC-128). O default e
    zero e nao a janela configurada de proposito: quem atrasa e a ingestao, que
    e o unico ponto onde uma rajada pode estar se formando. O sweeper -- um
    caminho de RECUPERACAO, onde a janela se fechou ha minutos -- e o opt-out
    continuam chamando sem argumento e continuam enfileirando para agora.
    """
    job = await pool.enqueue_job(
        PROCESS_MESSAGE_JOB,
        str(message_id),
        _job_id=f"msg:{message_id}",
        # `or None` e nao o valor cru: `_defer_by=0.0` faria o ARQ somar zero ao
        # score, que da no mesmo -- mas passar None deixa explicito no codigo
        # que "sem atraso" e ausencia de defer, nao defer de duracao nula.
        _defer_by=atraso_segundos or None,
    )
    return job is not None


async def enqueue_baixar_midia(pool: ArqRedis, message_id: uuid.UUID) -> bool:
    """Enfileira o download da midia de uma mensagem. TEC-132, D3.

    Mesmo `_job_id` estavel do `process_message`, pela mesma razao: a varredura
    de pendentes re-enfileira sem multiplicar trabalho enquanto o job estiver
    na fila. E `baixar_midia` e registrado com `keep_result=0` em
    `workers/main.py` pelo mesmo motivo do irmao.
    """
    job = await pool.enqueue_job(BAIXAR_MIDIA_JOB, str(message_id), _job_id=f"midia:{message_id}")
    return job is not None

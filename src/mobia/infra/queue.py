import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from mobia.app.config import get_settings

PROCESS_MESSAGE_JOB = "process_message"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


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

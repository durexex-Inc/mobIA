import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from mobia.app.config import get_settings

PROCESS_MESSAGE_JOB = "process_message"
SWEEP_STALLED_JOB = "sweep_stalled"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def create_redis_pool() -> ArqRedis:
    return await create_pool(redis_settings())


async def enqueue_process_message(pool: ArqRedis, message_id: uuid.UUID) -> bool:
    """Enfileira o processamento de uma mensagem.

    Usa `_job_id` derivado do message_id: o ARQ recusa o segundo enqueue enquanto
    o job estiver pendente, entao o sweeper nao multiplica trabalho. Devolve False
    quando o job ja estava na fila.

    O ARQ tambem recusa o enqueue quando a chave de *resultado* do mesmo job id
    existe. Por isso `process_message` e registrado com `keep_result=0` em
    `workers/main.py`: sem isso, o resultado de um job que terminou bloquearia
    todo re-enqueue do sweeper pela hora seguinte.
    """
    job = await pool.enqueue_job(
        PROCESS_MESSAGE_JOB, str(message_id), _job_id=f"msg:{message_id}"
    )
    return job is not None

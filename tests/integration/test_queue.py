import uuid

from mobia.infra.queue import PROCESS_MESSAGE_JOB, enqueue_process_message


async def test_enfileira_job_de_processamento(redis_pool) -> None:
    message_id = uuid.uuid4()
    assert await enqueue_process_message(redis_pool, message_id) is True

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1
    assert jobs[0].function == PROCESS_MESSAGE_JOB
    assert jobs[0].args == (str(message_id),)


async def test_mesmo_id_nao_entra_duas_vezes_na_fila(redis_pool) -> None:
    message_id = uuid.uuid4()
    assert await enqueue_process_message(redis_pool, message_id) is True
    assert await enqueue_process_message(redis_pool, message_id) is False
    assert len(await redis_pool.queued_jobs()) == 1

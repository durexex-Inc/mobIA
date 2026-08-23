import uuid

from mobia.infra.queue import PROCESS_MESSAGE_JOB, enqueue_process_message
from mobia.workers.main import WorkerSettings


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


async def test_chave_de_resultado_bloqueia_o_reenqueue(redis_pool) -> None:
    """Documenta o mecanismo que obriga process_message a rodar com keep_result=0.

    O enqueue_job do ARQ recusa quando a chave do job OU a de resultado existe.
    Com _job_id fixo em msg:<id>, o resultado retido de um job que terminou
    transformaria todo re-enqueue do sweeper em no-op silencioso.
    """
    message_id = uuid.uuid4()
    await redis_pool.set(f"arq:result:msg:{message_id}", b"fantasma")

    assert await enqueue_process_message(redis_pool, message_id) is False
    assert await redis_pool.queued_jobs() == []


def test_process_message_registrado_sem_reter_resultado() -> None:
    """A configuracao que fecha o buraco acima, nos dois niveis que o ARQ le."""
    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == PROCESS_MESSAGE_JOB
    )
    assert registrada.keep_result_s == 0
    # O finish_failed_job ignora a configuracao por funcao e le so a do worker.
    assert WorkerSettings.keep_result == 0

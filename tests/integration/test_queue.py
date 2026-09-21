import uuid
from datetime import UTC, datetime

from mobia.domain.handoff.agendador import GERAR_RESUMO_JOB
from mobia.infra.queue import PROCESS_MESSAGE_JOB, enqueue_process_message
from mobia.workers.jobs.notificar import NOTIFICAR_JOB
from mobia.workers.jobs.sweep_sla import SWEEP_SLA_JOB
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


def test_gerar_resumo_registrado_com_o_nome_esperado() -> None:
    """Amarra GERAR_RESUMO_JOB (usado por AgendadorArq para montar o `_job_id`)
    ao nome que WorkerSettings de fato registra. Renomear a corrotina sem
    mexer aqui produziria jobs que nenhum worker sabe rodar, sem sintoma na
    suite -- mesmo molde de test_process_message_registrado_sem_reter_resultado."""
    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == GERAR_RESUMO_JOB
    )
    assert registrada.keep_result_s == 0


def test_notificar_corretor_registrado_com_o_nome_esperado() -> None:
    """Amarra NOTIFICAR_JOB (usado por `gerar_resumo` para enfileirar) ao nome
    que WorkerSettings de fato registra. Renomear a corrotina sem mexer aqui
    produziria um job que nenhum worker sabe rodar, sem sintoma na suite --
    mesmo molde de test_gerar_resumo_registrado_com_o_nome_esperado."""
    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == NOTIFICAR_JOB
    )
    assert registrada.keep_result_s == 0


def test_sweep_sla_registrado_com_o_nome_esperado() -> None:
    """Amarra SWEEP_SLA_JOB ao nome que WorkerSettings de fato registra.

    Renomear a corrotina sem mexer aqui produziria um job de cron que nenhum
    worker sabe rodar, sem sintoma na suite -- mesmo molde de
    test_notificar_corretor_registrado_com_o_nome_esperado.
    """
    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == SWEEP_SLA_JOB
    )
    assert registrada.keep_result_s == 0


async def test_atraso_vira_job_diferido(redis_pool) -> None:
    """O atraso vira score futuro no zset da fila, que e como o ARQ difere."""
    message_id = uuid.uuid4()
    antes_ms = datetime.now(UTC).timestamp() * 1000

    assert await enqueue_process_message(redis_pool, message_id, atraso_segundos=6.0) is True

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1
    assert jobs[0].score is not None
    # Folga generosa dos dois lados: o que se prova e que o job nao esta
    # pronto para rodar agora, nao a precisao do relogio.
    assert 5_000 < jobs[0].score - antes_ms < 7_000


async def test_sem_atraso_o_job_nasce_pronto(redis_pool) -> None:
    """O default preserva o comportamento de hoje: sweeper e opt-out contam com ele."""
    message_id = uuid.uuid4()
    antes_ms = datetime.now(UTC).timestamp() * 1000

    assert await enqueue_process_message(redis_pool, message_id) is True

    jobs = await redis_pool.queued_jobs()
    assert jobs[0].score is not None
    assert jobs[0].score - antes_ms < 1_000


async def test_atraso_zero_e_o_mesmo_que_nenhum(redis_pool) -> None:
    """Janela zero desliga o debounce -- o caminho de fuga da D8 do desenho."""
    message_id = uuid.uuid4()
    antes_ms = datetime.now(UTC).timestamp() * 1000

    assert await enqueue_process_message(redis_pool, message_id, atraso_segundos=0.0) is True

    jobs = await redis_pool.queued_jobs()
    assert jobs[0].score is not None
    assert jobs[0].score - antes_ms < 1_000

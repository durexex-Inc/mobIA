"""O job da indexacao esta registrado nos DOIS lugares.

Registrar so em `functions` deixa o job chamavel e nunca chamado; so em
`cron_jobs`, o ARQ nao acha a funcao. O par e o que faz o cron existir.
"""

from mobia.workers.jobs.indexar_catalogo import indexar_catalogo
from mobia.workers.main import WorkerSettings


def test_o_job_esta_em_functions() -> None:
    nomes = {
        getattr(funcao, "name", None) or getattr(funcao, "__name__", None)
        for funcao in WorkerSettings.functions
    }
    assert "indexar_catalogo" in nomes


def test_o_job_esta_em_cron_jobs_a_cada_30_segundos() -> None:
    agendados = [
        job
        for job in WorkerSettings.cron_jobs
        if getattr(job.coroutine, "__name__", None) == indexar_catalogo.__name__
    ]
    assert len(agendados) == 1
    assert agendados[0].second == {0, 30}

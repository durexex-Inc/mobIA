from typing import Any

from arq import cron, func

from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.domain.agente.classificador import ClassificadorAnthropic
from mobia.domain.context.resumo import ContadorAnthropic, ResumidorAnthropic
from mobia.domain.outbound.whatsapp import WhatsAppOutbound
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.queue import redis_settings
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.sweep_stalled import sweep_stalled


async def startup(ctx: dict[str, Any]) -> None:
    """Monta o contexto compartilhado pelos jobs.

    `ctx["redis"]` nao entra aqui: o proprio ARQ ja gravou `ctx['redis'] =
    self.pool` imediatamente antes de chamar este hook, e sobrescrever so abriria
    um segundo pool redundante.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = get_sessionmaker()
    ctx["settings"] = settings
    ctx["session_factory"] = session_factory
    ctx["outbound"] = WhatsAppOutbound(session_factory)
    ctx["classificador"] = ClassificadorAnthropic()
    ctx["resumidor"] = ResumidorAnthropic()
    ctx["contador"] = ContadorAnthropic()


async def shutdown(ctx: dict[str, Any]) -> None:
    """O pool do Redis e do ARQ, que o fecha depois deste hook."""
    await dispose_engine()


class WorkerSettings:
    """Configuracao do worker ARQ.

    `keep_result = 0` nao e cosmetico. O `enqueue_job` do ARQ
    (`arq/connections.py`) recusa o enqueue quando **a chave do job ou a chave
    de resultado** existe: `if await pipe.exists(job_key, result_key_prefix +
    job_id)`. Como `enqueue_process_message` fixa `_job_id = msg:<id>`, um job
    que terminou deixaria `arq:result:msg:<id>` viva por 3600s (default) e todo
    re-enqueue do sweeper naquela hora viraria no-op silencioso -- queimando as
    cinco tentativas e abandonando a mensagem. A deduplicacao de job em voo, que
    e o motivo de o `_job_id` existir, mora na chave do *job*, que o `finish_job`
    apaga; essa continua valendo.

    O ajuste esta nos dois niveis de proposito: o `func(..., keep_result=0)`
    cobre o caminho normal do `run_job`, e o `keep_result` da classe cobre o
    `finish_failed_job` (`arq/worker.py`), que ignora a configuracao por funcao
    e usa so a do worker.
    """

    functions = [func(process_message, keep_result=0), sweep_stalled]
    cron_jobs = [cron(sweep_stalled, second={0, 30}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = 5
    job_timeout = 60
    keep_result = 0

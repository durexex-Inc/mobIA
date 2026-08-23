from typing import Any

from arq import cron

from mobia.app.config import get_settings
from mobia.app.logging import configure_logging
from mobia.domain.outbound.noop import NoopOutbound
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.queue import create_redis_pool, redis_settings
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.sweep_stalled import sweep_stalled


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = get_sessionmaker()
    ctx["settings"] = settings
    ctx["session_factory"] = session_factory
    ctx["outbound"] = NoopOutbound(session_factory)
    ctx["redis"] = await create_redis_pool()


async def shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("redis")
    if pool is not None:
        await pool.aclose()
    await dispose_engine()


class WorkerSettings:
    functions = [process_message, sweep_stalled]
    cron_jobs = [cron(sweep_stalled, second={0, 30}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = 5
    job_timeout = 60

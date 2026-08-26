from typing import Any

from arq import cron, func

from mobia.app.config import ConfiguracaoInsegura, get_settings
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

    # Sem token, `WhatsAppOutbound` funcionaria -- ate a primeira entrega, que
    # a Meta recusa com 401. Isso vira `EnvioRecusado` (permanente), o turno
    # devolve "sem_resposta" e a linha fecha em PROCESSED, que e terminal: o
    # sweeper nunca reenfileira. Cada lead que escrever antes de alguem notar
    # a configuracao faltando perde a resposta pra sempre, sem alarme alem de
    # uma linha de log. Falhar aqui, antes de `ctx["outbound"]` existir e
    # antes de qualquer job rodar, e o mesmo raciocinio de `get_client()` para
    # ANTHROPIC_API_KEY -- so que ali a chamada falha sozinha; aqui, sem esta
    # guarda, ela nao falhava, so descartava em silencio.
    if not settings.whatsapp_access_token:
        raise ConfiguracaoInsegura(
            "WHATSAPP_ACCESS_TOKEN nao configurado. Sem ele toda entrega volta "
            "401 da Meta -- falha permanente que fecha a mensagem sem "
            "retentativa, em silencio. Defina no .env ou no ambiente antes de "
            "subir o worker."
        )

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

    # 240s, e a relacao com `sweep_inflight_after_seconds = 300` e o que fixa
    # este numero: tem de ser **estritamente menor** que a janela do sweeper,
    # senao o sweeper reenfileira um turno que ainda esta em voo e a mesma
    # conversa roda duas vezes em paralelo. Os 60s vieram da TEC-122, quando o
    # job era claim + ACK. Hoje o turno faz `count_tokens` (as vezes -- so
    # quando a estimativa barata fica perto do teto), `resumir` (as vezes, a
    # cada ~40 mensagens, max_tokens=2000), `classificar` (sempre,
    # max_tokens=1500), desde a TEC-135 `desambiguar` (so no turno ambiguo,
    # max_tokens=300) e o POST para a Meta -- um turno com dobra ja passava de
    # 60s sem nada estar errado.
    #
    # Nao ha folga garantida nem nestes 240s: `resumir` + `classificar` sozinhos
    # ja somam o pior caso do cliente Anthropic (120s cada, ver
    # `infra/anthropic.py`) igual ao teto, e o turno ambiguo acrescenta
    # `desambiguar` depois dos dois -- 360s no pior caso, sem contar
    # `count_tokens` nem o POST. Isso nao e hipotetico: qualquer chamada perto
    # do seu proprio pior caso, nao so uma pane total, ja e o suficiente para
    # a soma passar do teto. Ver a secao "Lacunas conhecidas" do spec do
    # TEC-135 -- subir `job_timeout` exige medir a taxa real de retentativa
    # antes, nao e uma correcao que este comentario decide sozinho.
    #
    # Estourar aqui nao e so custo: o ARQ cancela a corrotina, e
    # `asyncio.CancelledError` e BaseException -- o `except Exception` de
    # `process_message` nao pega. A linha nunca vira FAILED, `attempts` nao
    # sobe, e se o cancelamento cair depois da reserva commitada o sweeper
    # reenfileira, a guarda suprime a reentrega e a mensagem fecha em
    # PROCESSED sem o lead ter recebido nada. Ver tambem o `timeout` explicito
    # do cliente em `infra/anthropic.py`: ele existe para que uma chamada
    # lenta vire erro tipado (recuperavel) antes de virar cancelamento.
    job_timeout = 240
    keep_result = 0

from typing import Any

from arq import cron, func

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.app.logging import configure_logging
from mobia.domain.agente.classificador import ClassificadorAnthropic
from mobia.domain.context.resumo import ContadorAnthropic, ResumidorAnthropic
from mobia.domain.handoff.agendador import AgendadorArq
from mobia.domain.handoff.resumo import RedatorAnthropic
from mobia.domain.notificacao.canais import EmailRegistrado, WhatsAppRegistrado
from mobia.domain.outbound.whatsapp import WhatsAppOutbound
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.moderacao import ModeradorAnthropic
from mobia.infra.queue import redis_settings
from mobia.workers.jobs.gerar_resumo import gerar_resumo
from mobia.workers.jobs.importar_catalogo import importar_catalogo
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo
from mobia.workers.jobs.notificar import notificar_corretor
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.sweep_followups import sweep_followups
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

    # TEC-157, D10. Mesma forma da guarda acima, e o mesmo motivo de ela
    # existir aqui e nao so no `get_client()`: sem chave, o
    # `ConfiguracaoInsegura` que ele levanta cairia DENTRO do `except
    # Exception` do laco de lotes da varredura, que loga e segue. Nenhuma
    # linha seria indexada nunca, o retorno da passagem ociosa jamais
    # dispararia, e sobraria um aviso por lote a cada 30 segundos, para
    # sempre -- ruido que some no log em vez de parar o deploy.
    #
    # A varredura tem hoje um retorno antecipado que avisa UMA vez, mas ele e
    # a metade de desenvolvimento da D10: o catalogo simplesmente fica sem
    # vetor e a busca perde o termo de similaridade, ordenando so por
    # aderencia de preco (emenda E-02 a RN-08.2, TEC-158) -- nunca vazio nem
    # erro. Em producao a resposta certa e nao subir.
    if settings.em_producao and not settings.openai_api_key:
        raise ConfiguracaoInsegura(
            "OPENAI_API_KEY nao configurada e ENVIRONMENT="
            f"{settings.environment}. Sem ela nenhum imovel e indexado e a "
            "busca semantica perde o termo de similaridade (60% do score) e "
            "ordena so por aderencia de preco, com um aviso por lote a cada 30 "
            "segundos como unico sintoma. Defina no .env ou no ambiente antes "
            "de subir o worker."
        )

    session_factory = get_sessionmaker()
    ctx["settings"] = settings
    ctx["session_factory"] = session_factory
    ctx["outbound"] = WhatsAppOutbound(session_factory)
    ctx["classificador"] = ClassificadorAnthropic()
    ctx["resumidor"] = ResumidorAnthropic()
    ctx["contador"] = ContadorAnthropic()
    ctx["moderador"] = ModeradorAnthropic()
    ctx["redator"] = RedatorAnthropic()
    ctx["agendador"] = AgendadorArq(ctx["redis"])
    # Os dois adaptadores de `canais.py` REGISTRAM e nao entregam -- ver o
    # docstring do modulo. E' o `startup` que decide a implementacao, no mesmo
    # raciocinio de `outbound`/`redator`/etc acima; o teste troca a chave sem
    # tocar no job.
    ctx["canais_de_notificacao"] = (EmailRegistrado(), WhatsAppRegistrado())


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

    # `importar_catalogo` entra sem `func(..., keep_result=0)`: o resultado do
    # job nao carrega nada -- o relatorio mora em `importacoes`, e e de la que
    # o GET o le. Nao entra em `cron_jobs` tambem: importacao e disparada por
    # quem envia o arquivo, nunca por relogio.
    functions = [
        func(process_message, keep_result=0),
        sweep_stalled,
        sweep_followups,
        importar_catalogo,
        indexar_catalogo,
        # `keep_result=0` pela mesma razao do `process_message`: o `_job_id` e
        # fixo por handoff, e uma chave de resultado sobrevivente bloquearia
        # um reenqueue futuro em silencio. Nao protege a rota da D8 -- ela
        # chama `gerar_resumo` em processo e nunca enfileira, entao nao ha
        # regeneracao por fila para recusar.
        func(gerar_resumo, keep_result=0),
        # `keep_result=0` pelo mesmo motivo dos dois acima: `gerar_resumo`
        # enfileira este job com `_job_id=f"notificar:{handoff_id}"` (fixo por
        # handoff) para nao duplicar o aviso se uma retentativa do ARQ rodar o
        # job do resumo de novo -- uma chave de resultado sobrevivente
        # bloquearia esse reenqueue em silencio. Nao entra em `cron_jobs`: quem
        # dispara este job e sempre `gerar_resumo`, nunca o relogio.
        func(notificar_corretor, keep_result=0),
    ]
    cron_jobs = [
        cron(sweep_stalled, second={0, 30}, run_at_startup=False),
        # De 30 em 30 segundos, como a `sweep_stalled` e nao como a
        # `sweep_followups`: o pre-filtro nao devolve nada quando nao ha
        # pendencia, entao a passagem ociosa e barata -- e a janela entre
        # importar e poder buscar e exatamente o que a indexacao eventual
        # custou. Encurta-la e o uso mais obvio de um cron barato.
        cron(indexar_catalogo, second={0, 30}, run_at_startup=False),
        # De 5 em 5 minutos, e nao de 30 em 30 segundos como o irmao: o menor
        # intervalo da RN-13.1 e de DUAS HORAS, entao precisao de segundos nao
        # compra nada e custa uma varredura que agrega `messages` a cada
        # passagem. O erro maximo de disparo fica em cinco minutos sobre uma
        # janela de duas horas.
        cron(
            sweep_followups,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
    ]
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
    # `asyncio.CancelledError` e BaseException -- nenhum `except Exception` a
    # pega. Ate a TEC-227 isso significava perder a mensagem em silencio: a
    # linha nunca virava FAILED, `attempts` nao subia, e um cancelamento
    # depois da reserva commitada fazia o sweeper reenfileirar, a guarda
    # suprimir a reentrega e a mensagem fechar em PROCESSED sem o lead ter
    # recebido nada.
    #
    # Agora `process_message` tem uma clausula propria para `CancelledError`
    # (marca FAILED, incrementa `attempts`, loga `message.cancelled` e
    # repropaga) e o `GuardedOutbound` libera a reserva. **Estourar continua
    # sendo ruim** -- custa uma passada inteira do turno, chamadas pagas ao
    # modelo inclusas, e pode duplicar a entrega se o cancelamento cair depois
    # de o POST ter chegado a Meta. So deixou de ser invisivel.
    #
    # Ver tambem o `timeout` explicito do cliente em `infra/anthropic.py`: ele
    # existe para que uma chamada lenta vire erro tipado (recuperavel) antes
    # de virar cancelamento.
    job_timeout = 240

    # SIGTERM: espera os jobs em voo terminarem em vez de cancela-los na hora.
    # Com valor nao-zero o arq troca `handle_sig` por
    # `handle_sig_wait_for_completion` (`arq/worker.py`), que para de pegar job
    # novo (`allow_pick_jobs = False`), espera ate este prazo e **so entao**
    # cancela o que sobrou. E carencia, nao garantia.
    #
    # 250 > `job_timeout` nao e folga arbitraria: e a invariante inteira. Sendo
    # maior, a drenagem cabe o orcamento completo do turno, e nenhum deploy
    # cancela um job por conta propria -- ele termina, ou estoura os 240s dele,
    # que e falha de verdade e conta certo em `attempts`. Antes disto todo
    # SIGTERM cancelava todo job em voo, e cada restart queimava uma das cinco
    # `sweep_max_attempts` sem ter havido falha de processamento nenhuma.
    #
    # **Exige do deploy uma carencia SIGTERM->SIGKILL acima de ~265s**: os 250
    # da drenagem, mais os 10 de `SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO` para o
    # job que a janela nao salvou escrever seu FAILED, mais os hooks de
    # shutdown (`dispose_engine` e o pool do Redis). Se o SIGKILL chegar antes
    # de tudo isso, o processo morre sem
    # `CancelledError`: a clausula de `process_message` nao roda, nada escreve
    # FAILED, e a linha fica em PROCESSING com `attempts` congelado -- pior que
    # cancelar na hora, que ao menos registra. Nenhum teste cobre isso; a
    # config de deploy nao mora neste repo. Ver a secao TEC-232 do README.
    #
    # A clausula de `CancelledError` da TEC-227 continua sendo a rede embaixo:
    # o cancelamento pos-janela ainda acontece, e ai ele e legitimo.
    job_completion_wait = 250

    keep_result = 0

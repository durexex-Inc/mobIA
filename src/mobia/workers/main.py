from typing import Any

import structlog
from arq import cron, func

from mobia.app.config import ConfiguracaoInsegura, get_settings
from mobia.app.logging import configure_logging
from mobia.domain.agendamento.agendador import AgendadorDeAvisosArq
from mobia.domain.agendamento.calendario import CalendarioNoop, GoogleCalendar
from mobia.domain.agente.classificador import ClassificadorAnthropic
from mobia.domain.context.resumo import ContadorAnthropic, ResumidorAnthropic
from mobia.domain.crm.webhook import CrmWebhook
from mobia.domain.handoff.agendador import AgendadorArq
from mobia.domain.handoff.recuperacao import ReenfileiradorArq
from mobia.domain.handoff.resumo import RedatorAnthropic
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.midia.armazem import armazem_da_config
from mobia.domain.outbound.email import EmailSmtp
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebIndicador, WebOutbound
from mobia.domain.outbound.whatsapp import WhatsAppIndicador, WhatsAppOutbound
from mobia.domain.outbound.whatsapp_notificacao import WhatsAppTemplate
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.moderacao import ModeradorAnthropic
from mobia.infra.queue import redis_settings
from mobia.workers.jobs.avisar_cancelamento import avisar_cancelamento
from mobia.workers.jobs.avisar_confirmacao import avisar_confirmacao
from mobia.workers.jobs.baixar_midia import MAXIMO_DE_TENTATIVAS, baixar_midia
from mobia.workers.jobs.exportar_crm import exportar_crm
from mobia.workers.jobs.gerar_resumo import gerar_resumo
from mobia.workers.jobs.importar_catalogo import importar_catalogo
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo
from mobia.workers.jobs.notificar import notificar_corretor
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.sweep_conversas_inativas import sweep_conversas_inativas
from mobia.workers.jobs.sweep_crm_pendentes import sweep_crm_pendentes
from mobia.workers.jobs.sweep_followups import sweep_followups
from mobia.workers.jobs.sweep_importacoes_travadas import sweep_importacoes_travadas
from mobia.workers.jobs.sweep_lembretes import sweep_lembretes
from mobia.workers.jobs.sweep_midias_pendentes import sweep_midias_pendentes
from mobia.workers.jobs.sweep_remarcacoes import sweep_remarcacoes
from mobia.workers.jobs.sweep_sla import sweep_sla
from mobia.workers.jobs.sweep_stalled import sweep_stalled

log = structlog.get_logger(__name__)


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

    # TEC-280. Incondicional, como a de WHATSAPP_ACCESS_TOKEN e nao como a de
    # OPENAI_API_KEY acima, que so recusa em producao: condicionar ao ambiente
    # deixaria a maquina de quem desenvolve convivendo com o defeito que esta
    # card existe para matar. Notificacao descartada em silencio nao e menos
    # defeito por acontecer em dev -- e so menos visivel, que e pior.
    #
    # O remetente entra na mesma guarda porque host sem remetente nao entrega:
    # o servidor recusa o envelope sem MAIL FROM, e a falha apareceria so na
    # primeira notificacao, que e tarde.
    if not settings.smtp_host or not settings.smtp_remetente:
        raise ConfiguracaoInsegura(
            "SMTP_HOST ou SMTP_REMETENTE nao configurado. Sem os dois a "
            "notificacao de handoff nao chega ao corretor, e o lead fica "
            "esperando sem que ninguem saiba. Suba o Mailpit do "
            "docker-compose e defina os dois no .env antes de subir o worker."
        )

    # TEC-170, D5. Com o refresh token preenchido, id e segredo do cliente
    # passam a ser obrigatorios: sem eles o Google recusa a troca de token na
    # primeira tentativa de criar um evento, dentro do `except FalhaDeCalendario`
    # de `_criar_evento`, que loga e segue -- o sintoma seria um aviso por
    # agendamento confirmado, nao uma recusa na subida. Um laco e nao duas
    # guardas identicas: a mensagem muda so no nome da variavel que falta.
    if settings.google_calendar_refresh_token:
        for nome, valor in (
            ("GOOGLE_CALENDAR_CLIENT_ID", settings.google_calendar_client_id),
            ("GOOGLE_CALENDAR_CLIENT_SECRET", settings.google_calendar_client_secret),
        ):
            if not valor:
                raise ConfiguracaoInsegura(
                    f"{nome} nao configurado com GOOGLE_CALENDAR_REFRESH_TOKEN "
                    "preenchido. Sem ele o Google recusa a troca do refresh "
                    "token, e o evento nunca e criado -- so um aviso por "
                    "agendamento confirmado. Defina os dois no .env ou no "
                    "ambiente antes de subir o worker."
                )

    session_factory = get_sessionmaker()
    ctx["settings"] = settings
    ctx["session_factory"] = session_factory
    # TEC-124. Roteador e nao instancia unica: o adaptador sai do canal da
    # linha, e nenhum dos sitios de chamada precisa saber que ha dois.
    ctx["outbound"] = RoteadorPorCanal(
        session_factory,
        {
            CANAL_WHATSAPP: WhatsAppOutbound(session_factory),
            # Mesmo `ctx["redis"]` do agendador logo abaixo -- o ARQ ja o
            # gravou antes deste hook, e um segundo pool seria redundante.
            CANAL_WEB: WebOutbound(session_factory, ctx["redis"]),
        },
    )
    # TEC-274 e TEC-124. Dicionario e nao instancia unica: no web os dois
    # campos que fariam `indicador_de_digitacao` desistir estao preenchidos, e
    # o `WhatsAppIndicador` dispararia um POST para a Meta com um UUID de
    # sessao no lugar do wamid. Sem `session_factory`: as guardas do indicador
    # moram no agendador (`domain/outbound/presenca.py`), nao no adaptador. A
    # guarda de `WHATSAPP_ACCESS_TOKEN` logo acima cobre o do WhatsApp -- sem
    # token, ele tambem levaria 401.
    ctx["indicadores"] = {
        CANAL_WHATSAPP: WhatsAppIndicador(),
        # A lacuna da TEC-124 fechou na TEC-362: `IndicadorDePresencaPort`
        # ganhou `para`, que no web e a sessao, e com ela da para publicar.
        # Mesmo `ctx["redis"]` do `WebOutbound` logo acima, pela mesma razao.
        CANAL_WEB: WebIndicador(ctx["redis"]),
    }
    ctx["classificador"] = ClassificadorAnthropic()
    ctx["resumidor"] = ResumidorAnthropic()
    ctx["contador"] = ContadorAnthropic()
    ctx["moderador"] = ModeradorAnthropic()
    ctx["redator"] = RedatorAnthropic()
    ctx["agendador"] = AgendadorArq(ctx["redis"])
    # TEC-371 e TEC-372. O turno confirma ou cancela agendamento e
    # enfileira o aviso depois do commit. Mesmo `ctx["redis"]` dos outros.
    ctx["agendador_de_avisos"] = AgendadorDeAvisosArq(ctx["redis"])
    # Mesmo `ctx["redis"]` do `agendador` acima -- ver o docstring do
    # `startup` no topo do modulo: o ARQ ja o gravou antes deste hook, e um
    # segundo pool seria redundante.
    ctx["reenfileirador"] = ReenfileiradorArq(ctx["redis"])
    # O de e-mail entrega (TEC-280); o de WhatsApp ainda REGISTRA e nao
    # entrega, porque depende de template aprovado pela Meta -- ver o docstring
    # de `canais.py`. E' o `startup` que decide a implementacao, no mesmo
    # raciocinio de `outbound`/`redator`/etc acima; o teste troca a chave sem
    # tocar no job.
    ctx["canais_de_notificacao"] = (EmailSmtp(), WhatsAppTemplate())
    # TEC-132, D1. Disco ou S3 conforme `midia_armazem`; a validacao de que
    # "s3" veio com bucket ja rodou quando `get_settings()` montou a config.
    #
    # Em producao com o armazem local, avisa e SOBE, ao contrario das guardas
    # acima: o S3 de producao (bucket, credenciais, politica) e da TEC-219, e
    # recusar aqui travaria todo deploy ate la. O custo aceito e a midia ficar
    # no disco do container, que some com ele -- o aviso existe para isso nao
    # acontecer sem ninguem saber.
    if settings.em_producao and settings.midia_armazem == "local":
        log.warning("midia.armazem_local_em_producao", diretorio=settings.midia_diretorio)
    ctx["armazem"] = armazem_da_config(settings)
    #
    # TEC-170. Uma instancia so, guardada tambem em `ctx["email_ao_corretor"]`:
    # e a mesma porta que `avisar_confirmacao` usa para o aviso ao corretor, e
    # a guarda de SMTP acima ja validou host e remetente para ela -- uma
    # segunda instancia seria equivalente, nao mais segura.
    email = EmailSmtp()
    ctx["canais_de_notificacao"] = (email, WhatsAppTemplate())
    ctx["email_ao_corretor"] = email

    # TEC-180. `None` e nao um adaptador que registra e nao entrega: o repo
    # apagou os dois dubles que ja teve (`EmailRegistrado` na TEC-280, o
    # registrador de WhatsApp na TEC-281), com a razao escrita em
    # `domain/notificacao/canais.py`. Ver a D1 do desenho.
    #
    # **Nao ha guarda que recuse subir**, ao contrario do SMTP logo acima: a
    # exportacao e `Should` no MoSCoW e a card declara o contorno da POC
    # ("trabalhar direto no dashboard"), entao uma guarda tornaria uma
    # integracao opcional pre-requisito para rodar o sistema. O que substitui a
    # guarda e este aviso -- uma linha por subida do worker, nao uma por
    # handoff. Ver a emenda E-02 a RN-16.5 e a D2 do desenho.
    if settings.crm_webhook_url:
        ctx["crm"] = CrmWebhook()
    else:
        ctx["crm"] = None
        log.warning(
            "crm.exportacao_desligada",
            motivo="CRM_WEBHOOK_URL nao configurada; nenhum lead sera exportado",
        )

    # TEC-170, D5. A flag e a credencial vazia, na convencao do CRM logo
    # acima: sem refresh token o worker sobe com o Noop e avisa uma vez por
    # subida. Com o token, id e segredo sao obrigatorios -- ver a guarda.
    if settings.google_calendar_refresh_token:
        ctx["calendario"] = GoogleCalendar()
    else:
        ctx["calendario"] = CalendarioNoop()
        log.warning(
            "agendamento.calendario_desligado",
            motivo="GOOGLE_CALENDAR_REFRESH_TOKEN nao configurado; nenhum evento sera criado",
        )


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
        # `keep_result=0` NAO e pelo mesmo motivo dos dois acima. La, a chave
        # de resultado sobrevivente bloquearia um reenqueue LEGITIMO -- um
        # recurso que se perderia. Aqui e o oposto: `gerar_resumo` enfileira
        # este job com `_job_id=f"notificar:{handoff_id}"` (fixo por handoff)
        # para tentar nao duplicar o aviso se uma retentativa do ARQ rodar o
        # job do resumo de novo, mas a chave de resultado sumindo ao terminar
        # e o que ABRE espaco para a duplicata, nao o que a impede -- e a L3
        # do desenho, declarada e nao corrigida (ver o comentario do `_job_id`
        # em `workers/jobs/gerar_resumo.py`). Nao entra em `cron_jobs`: quem
        # dispara este job e `gerar_resumo` ao terminar, ou `recuperar_sem_prazo`
        # pela varredura -- nunca um `cron` deste job.
        func(notificar_corretor, keep_result=0),
        # `keep_result=0` pela mesma razao do `notificar_corretor` acima: o
        # `_job_id` e fixo por agendamento (`confirmacao:<id>`, ver
        # `AgendadorDeAvisosArq`), e uma chave de resultado sobrevivente
        # bloquearia em silencio um reenqueue legitimo. Nao entra em
        # `cron_jobs`: nenhum caminho de producao ainda enfileira este job
        # (ver o docstring de `domain/agendamento/confirmacao.py`), e nao ha
        # relogio que deva disparar um aviso de confirmacao.
        func(avisar_confirmacao, keep_result=0),
        # TEC-372, mesmo raciocinio do `avisar_confirmacao` logo acima: o
        # `_job_id` e fixo por agendamento (`cancelamento:<id>`), e uma
        # chave de resultado sobrevivente bloquearia um reenqueue
        # legitimo. Fora de `cron_jobs`: quem o dispara e o turno, ao ler
        # a resposta do lead ao lembrete -- nao ha relogio envolvido.
        func(avisar_cancelamento, keep_result=0),
        # `keep_result=0` pela mesma razao do `WorkerSettings.keep_result` da
        # classe (ver o docstring dela): o resultado deste job (um `int`) nao
        # serve para nada depois que o log saiu, e nao ha motivo para pagar a
        # retencao padrao do arq. Entra em `cron_jobs` tambem, como
        # `sweep_followups` -- e o relogio que dispara este job, nunca um
        # enqueue manual.
        func(sweep_sla, keep_result=0),
        sweep_importacoes_travadas,
        # `keep_result=0` pela mesma razao do `sweep_sla`: o resultado (um
        # `int`) nao serve para nada depois que o log saiu. Entra em
        # `cron_jobs` tambem -- e o relogio que dispara este job, nunca um
        # enqueue manual.
        func(sweep_conversas_inativas, keep_result=0),
        # TEC-180. `keep_result=0` pela razao do `gerar_resumo`: o `_job_id` e
        # fixo por handoff (`crm:<id>`), e uma chave de resultado sobrevivente
        # bloquearia em silencio o reenqueue que a varredura faz a cada rodada
        # nova -- justamente o mecanismo do terceiro cenario do Gherkin.
        #
        # **Sem `max_tries` proprio, de proposito.** As tres tentativas da
        # RN-16.5 se contam em `handoffs.crm_tentativas`, nao aqui: com
        # `max_tries=3`, a terceira falha estouraria o teto do ARQ e ele
        # encerraria o job SEM chamar a corrotina -- nada marcaria a linha e
        # nada emitiria o alerta. Ver o cabecalho de
        # `workers/jobs/exportar_crm.py`, que cita a fonte do arq, e a D3 do
        # desenho. O global de 5 fica valendo como rede para o worker morrer no
        # meio de uma tentativa.
        func(exportar_crm, keep_result=0),
        # `keep_result=0` pela mesma razao do `sweep_sla`: o resultado (um
        # `int`) nao serve para nada depois que o log saiu.
        func(sweep_crm_pendentes, keep_result=0),
        # TEC-132. `keep_result=0` pela mesma razao do `process_message`: o
        # `_job_id` e fixo (`midia:<id>`, ver `enqueue_baixar_midia`), e uma
        # chave de resultado sobrevivente faria o re-enqueue da
        # `sweep_midias_pendentes` virar no-op silencioso. `max_tries` e o
        # mesmo numero que o job consulta para decidir, na ultima tentativa,
        # gravar FALHOU em vez de pedir outro `Retry` -- se os dois divergirem,
        # o ARQ desiste antes do job gravar e a linha fica PENDENTE ate a
        # varredura.
        func(baixar_midia, keep_result=0, max_tries=MAXIMO_DE_TENTATIVAS),
        # `keep_result=0` pela mesma razao do `sweep_sla`: o resultado (um
        # `int`) nao serve para nada depois que o log saiu. Entra em
        # `cron_jobs` tambem -- e o relogio que dispara este job.
        func(sweep_midias_pendentes, keep_result=0),
        # TEC-171. `keep_result=0` pela mesma razao do `sweep_sla`: o resultado
        # (um `int`) nao serve para nada depois que o log saiu. Entra em
        # `cron_jobs` tambem -- e o relogio que dispara este job, nunca um
        # enqueue manual. **Sem `_job_id` e sem `max_tries` proprio**: nao ha
        # enfileiramento por id nenhum aqui, e o teto de retentativa de um
        # lembrete e a FAIXA em que ele e devido (`lembrete_devido`), nao uma
        # contagem -- quando a faixa fecha, a linha deixa de aparecer na
        # consulta.
        func(sweep_lembretes, keep_result=0),
        # TEC-172. `keep_result=0` e as mesmas razoes do `sweep_lembretes`
        # logo acima, inclusive a ausencia de `max_tries`: o teto de
        # retentativa de um convite e a FAIXA em que ele e devido
        # (`convite_devido`), nao uma contagem.
        func(sweep_remarcacoes, keep_result=0),
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
        # De 5 em 5 minutos, como o `sweep_followups` acima e pela mesma
        # razao: o menor prazo de aceite da RN-16.3 e de QUINZE MINUTOS
        # (`PRAZO_QUENTE_MINUTOS` em `handoff/sla.py`), entao precisao de
        # segundos nao compra nada e custa uma varredura a mais a cada
        # passagem. O erro maximo de disparo fica em cinco minutos sobre uma
        # janela de quinze.
        cron(
            sweep_sla,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
        # De 5 em 5 minutos, como o `sweep_followups` e o `sweep_sla` acima, e
        # nao de 30 em 30 segundos como a `sweep_stalled`. O limite desta
        # varredura e de TRINTA MINUTOS
        # (`sweep_importacao_travada_after_seconds`), entao precisao de
        # segundos nao compra nada e custaria uma varredura a cada passagem.
        # O erro maximo de disparo fica em cinco minutos sobre uma janela de
        # trinta.
        cron(
            sweep_importacoes_travadas,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
        # **Uma vez por dia**, e nao de cinco em cinco minutos como os
        # irmaos acima. A janela desta regra e de TRINTA DIAS: a diferenca
        # entre fechar as 3h e fechar as 3h30 nao existe para ninguem, e a
        # consulta agrega `messages` INTEIRA -- nao uma fila curta como a da
        # `sweep_stalled` --, entao cada passagem e cara. Rodar de hora em
        # hora multiplicaria esse custo por 24 para antecipar um registro que
        # ninguem le em tempo real.
        #
        # **E o atraso e inofensivo por construcao** (D3 do desenho): quem
        # impede a transcricao velha de entrar no prompt e o turno, pelo
        # relogio, nao este cron. Uma passagem perdida atrasa a escrituracao,
        # nunca o comportamento.
        #
        # As 3h da manha, horario do runner: e quando a fila de
        # `process_message` esta mais vazia, e esta varredura toma locks em
        # `conversas`.
        cron(sweep_conversas_inativas, hour={3}, minute={0}, run_at_startup=False),
        # TEC-180. **De 15 em 15 minutos**, e nao de 5 em 5 como os irmaos: a
        # cadencia aqui e a de uma rodada de retentativa contra um sistema que
        # ja falhou tres vezes, nao a de um prazo a cumprir. Mais frequente so
        # multiplicaria POSTs contra um CRM que esta fora, e o custo de esperar
        # um quarto de hora a mais por um lead num CRM e nulo -- o corretor ja
        # foi avisado pela RN-16.2, que tem prazo de 60 segundos e caminho
        # proprio.
        #
        # `run_at_startup=False` como todos os outros: uma reinicializacao de
        # worker nao e evento que justifique varrer.
        cron(sweep_crm_pendentes, minute={0, 15, 30, 45}, run_at_startup=False),
        # TEC-132, D3. De 5 em 5 minutos, como `sweep_followups`, `sweep_sla` e
        # `sweep_importacoes_travadas` acima: o prazo para
        # supor o enfileiramento perdido e de DEZ MINUTOS (`REENFILEIRAR_APOS`
        # em `sweep_midias_pendentes.py`), entao precisao de segundos nao
        # compra nada. O pior caso fica em quinze minutos entre a ingestao e o
        # re-enqueue -- e ninguem espera pela midia, o turno nao depende dela.
        cron(
            sweep_midias_pendentes,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
        # TEC-171, RN-12.2. De 5 em 5 minutos, como os quatro acima e nao de 30
        # em 30 segundos como a `sweep_stalled`: a MENOR faixa desta regra e de
        # DUAS HORAS (a do lembrete de 2h, `lembrete_devido`), entao precisao de
        # segundos nao compra nada e custaria uma varredura por passagem. O erro
        # maximo de disparo fica em cinco minutos sobre uma janela de duas
        # horas.
        #
        # **E a passagem ociosa e barata por treze das vinte e quatro horas**: a
        # guarda de horario (RN-13.3) roda ANTES da consulta e devolve sem tocar
        # o banco.
        #
        # `run_at_startup=False` como todos os outros.
        cron(
            sweep_lembretes,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
        # TEC-172, RN-12.3. De 5 em 5 minutos como a irma, e com folga ainda
        # maior: a faixa deste convite e de SETE DIAS, entao o erro maximo de
        # disparo e desprezivel sobre ela. Roda nesta cadencia e nao numa mais
        # esparsa porque a passagem ociosa e barata -- a guarda de horario
        # devolve antes da consulta por treze das vinte e quatro horas.
        cron(
            sweep_remarcacoes,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = 5

    # 240s, e a relacao com `sweep_inflight_after_seconds = 300` e o que fixa
    # este numero -- mas a relacao tem QUATRO termos, nao dois, desde a
    # TEC-128 (que acrescentou o terceiro) e a TEC-205 (que acrescentou o
    # quarto). `sweep_inflight_after_seconds` mede `COALESCE(queued_at,
    # created_at)` (`sweep_stalled.py`), e `queued_at` e carimbado na
    # INGESTAO -- antes da janela de debounce da RN-01.6, que e incondicional
    # (D1 do desenho: TODA mensagem espera `debounce_de_rajada_segundos`
    # antes de o job comecar, nao so a que integra rajada). Desde a TEC-205 a
    # mensagem tambem pode esperar `atraso_de_backoff_segundos` no lugar do
    # debounce, quando ela e o excedente do rate limit por numero -- e e o
    # MAIOR dos dois atrasos que define o pior caso, nao a soma dos dois,
    # porque uma mensagem so passa por um ou por outro. A invariante e
    # `max(debounce_de_rajada_segundos, atraso_de_backoff_segundos) +
    # job_timeout < sweep_inflight_after_seconds`
    # (`test_job_timeout_cabe_dentro_da_janela_do_sweeper`,
    # `test_worker_startup.py`); com os defaults de hoje
    # (max(6, 30) + 240 = 270 < 300) a folga e de 30s, nao mais os 54s de
    # antes da TEC-205 -- e tanto `debounce_de_rajada_segundos` quanto
    # `atraso_de_backoff_segundos` sao configuracao de produto que pode ser
    # mexida, entao subir qualquer um dos dois demais reabre esta conta sem
    # que `job_timeout` sozinho avise. Sem a janela na conta,
    # `job_timeout` **estritamente menor** que a janela do sweeper faria o
    # sweeper reenfileirar um turno que ainda esta em voo e a mesma
    # conversa rodaria duas vezes em paralelo. Os 60s vieram da TEC-122, quando o
    # job era claim + ACK. Hoje o turno faz `count_tokens` (as vezes -- so
    # quando a estimativa barata fica perto do teto), `resumir` (as vezes, a
    # cada ~40 mensagens, max_tokens=2000), `reagir` (so depois de um turno que
    # apresentou imoveis, max_tokens=300), `classificar` ou
    # `qualificar_investidor` (sempre, max_tokens=1500), desde a TEC-135
    # `desambiguar` (so no turno ambiguo, max_tokens=300) e o POST para a Meta
    # -- lista de QUAIS chamadas existem, nao de quantas vezes cada uma roda
    # (`count_tokens` e `resumir` repetem por volta do laco de montagem, ver
    # abaixo) -- um turno com dobra ja passava de 60s sem nada estar errado.
    #
    # **Ate a TEC-228 nao havia folga, e a versao anterior deste comentario
    # subcontava o proprio buraco.** Ela dizia 360s somando tres chamadas a
    # 120s; o turno paga CINCO fatias, e duas delas fazem duas requisicoes cada
    # quando o modelo usa a busca -- o numero real era 840s contra estes 240.
    #
    # **E o maior termo nao era nem da Anthropic.** O embed da busca
    # (`infra/embeddings.py`) tinha 50s com retentativa, e um turno busca ate
    # duas vezes: 200s sozinho, mais que todas as chamadas de modelo somadas.
    #
    # **A conta fecha desde a TEC-290, e com reserva de banco de pe.** A
    # TEC-229 corrigiu o grafo e a soma foi a 327s: `montar_contexto` chama
    # `resumir` e `count_tokens` dentro de um laco que roda ate
    # `contexto_max_iteracoes`, e o pior caso crescia junto com essa
    # configuracao. A TEC-290 deu a fase um deadline agregado
    # (`Settings.contexto_deadline_de_montagem_segundos`), e ela parou de
    # crescer. Com os valores de hoje:
    #
    #   167s  Anthropic (`segundos_do_modelo_no_pior_turno`), dos quais
    #          35s sao o deadline da fase de montagem, uma vez so
    #    20s  embed da busca, 2 buscas x 10s, sem retentativa
    #    10s  moderacao das duas pontas
    #    10s  POST para a Meta
    #   ----
    #   207s  contra estes 240 -- folga de 33s, acima dos 30 reservados ao banco
    #
    # `test_o_pior_turno_cabe_no_job_timeout` e `test_a_folga_paga_o_banco`
    # montam essa soma importando cada termo do modulo dele; e onde a conta
    # INTEIRA esta escrita -- cada modulo so conhece a propria parcela, e foi
    # somar uma parcela achando que era o todo que produziu o 360s de tres
    # versoes atras deste comentario.
    #
    # **A folga e de 33s contra um minimo de 30, e isso e apertado de
    # proposito.** Subir qualquer teto por chamada reabre a conta. A TEC-290
    # escolheu o deadline agregado entre tres caminhos justamente para nao
    # mexer neste numero: subi-lo exigiria subir
    # `sweep_inflight_after_seconds` junto, e com ele a carencia
    # SIGTERM->SIGKILL exigida do deploy, que nao mora neste repo. Ver
    # `docs/superpowers/specs/2026-09-19-tec-290-orcamento-agregado-da-montagem-design.md`.
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
    # Ver tambem os tetos explicitos em `infra/anthropic.py`: eles existem
    # para que uma chamada lenta vire erro tipado (recuperavel) antes de virar
    # cancelamento.
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

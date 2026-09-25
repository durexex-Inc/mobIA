import base64
import logging
import signal
import uuid

import pytest

from mobia.app.config import ConfiguracaoInsegura
from mobia.domain.agendamento.calendario import CalendarioNoop, GoogleCalendar
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebIndicador, WebOutbound
from mobia.domain.outbound.whatsapp import WhatsAppIndicador, WhatsAppOutbound
from mobia.workers.jobs import avisar_confirmacao as job_da_confirmacao
from mobia.workers.main import startup


async def test_startup_monta_saida_e_indicador_por_canal(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """TEC-124, D5. Cada canal com o seu adaptador, e o web sem indicador.

    Le `_portas` direto porque o que se testa aqui e a MONTAGEM: sem banco e
    sem rede, nao ha comportamento observavel do roteador que diga qual
    adaptador ele recebeu. O que o roteador faz com o dicionario esta em
    `test_roteador_de_canal.py`.
    """
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    ctx: dict = {"redis": object()}

    await startup(ctx)

    portas = ctx["outbound"]._portas
    assert set(portas) == {CANAL_WHATSAPP, CANAL_WEB}
    assert isinstance(portas[CANAL_WHATSAPP], WhatsAppOutbound)
    assert isinstance(portas[CANAL_WEB], WebOutbound)
    assert isinstance(ctx["indicadores"][CANAL_WHATSAPP], WhatsAppIndicador)
    # Deixou de ser `IndicadorNoop` na TEC-362: a lacuna da TEC-124 fechou
    # quando o port ganhou `para`, que no web e a sessao.
    assert isinstance(ctx["indicadores"][CANAL_WEB], WebIndicador)
    assert "indicador" not in ctx


async def test_startup_recusa_subir_sem_token_da_meta(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Sem token, `WhatsAppOutbound` so falharia na primeira entrega -- com
    401 virando EnvioRecusado (permanente) e a linha fechando em PROCESSED,
    terminal, sem retentativa. A guarda barra isso antes de qualquer job
    rodar, nao depois de a primeira mensagem ser descartada em silencio.
    """
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "")

    with pytest.raises(ConfiguracaoInsegura, match="WHATSAPP_ACCESS_TOKEN"):
        await startup({})


async def test_startup_sobe_com_token_configurado(
    monkeypatch: pytest.MonkeyPatch,
    caches_de_cliente_limpos: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    # TEC-280: a guarda de SMTP e incondicional, entao todo teste que chega ate
    # a asercao precisa dos dois preenchidos -- nunca confiando no .env local.
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")

    # `redis` entra a mao aqui porque este teste chama `startup` direto, sem o
    # ARQ em volta -- em producao e o proprio ARQ que grava `ctx["redis"]`
    # antes de chamar o hook (ver o docstring de `startup`). Um objeto
    # qualquer basta: `AgendadorArq.__init__` so guarda a referencia, nunca
    # conecta, e a fixture `redis_pool` chamaria `get_settings()` cedo demais
    # -- antes do `monkeypatch.setenv` acima -- e deixaria o cache de
    # `Settings` sem o token, furando este proprio teste.
    ctx: dict = {"redis": object()}
    with caplog.at_level(logging.WARNING):
        await startup(ctx)

    assert isinstance(ctx["outbound"], RoteadorPorCanal)
    assert "classificador" in ctx
    assert "resumidor" in ctx
    assert "contador" in ctx
    assert "agendador" in ctx
    assert "reenfileirador" in ctx
    # TEC-170, D5: sem GOOGLE_CALENDAR_REFRESH_TOKEN (default vazio) o worker
    # sobe com o Noop e avisa uma vez, na mesma convencao do CRM acima.
    assert isinstance(ctx["calendario"], CalendarioNoop)
    assert "agendamento.calendario_desligado" in caplog.text
    # Mesma instancia de EmailSmtp que `canais_de_notificacao` usa -- o job de
    # confirmacao precisa da MESMA porta, ja validada pela guarda de SMTP
    # acima, e nao de uma segunda instancia equivalente.
    assert ctx["email_ao_corretor"] is ctx["canais_de_notificacao"][0]


async def test_startup_liga_o_calendario_google_com_credenciais_completas(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh-de-teste")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id-de-teste")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "segredo-de-teste")

    ctx: dict = {"redis": object()}
    await startup(ctx)

    assert isinstance(ctx["calendario"], GoogleCalendar)


async def test_o_job_da_confirmacao_le_do_ctx_as_chaves_que_o_startup_grava(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """TEC-170. O job le quatro chaves do `ctx`, e uma grafada diferente do
    `startup` so levantaria `KeyError` no primeiro agendamento confirmado.
    Aqui o `ctx` e o que o `startup` de verdade montou, e a funcao de dominio
    e trocada por um espiao so para ver o que chegou nela."""
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    ctx: dict = {"redis": object()}
    await startup(ctx)

    recebido: dict = {}

    async def _espiao(session_factory, **portas) -> None:
        recebido.update(portas, session_factory=session_factory)

    monkeypatch.setattr(job_da_confirmacao, "_avisar_confirmacao", _espiao)
    agendamento_id = uuid.uuid4()

    assert await job_da_confirmacao.avisar_confirmacao(ctx, str(agendamento_id)) == "avisado"

    assert recebido["agendamento_id"] == agendamento_id
    assert recebido["session_factory"] is ctx["session_factory"]
    assert recebido["outbound"] is ctx["outbound"]
    assert recebido["email"] is ctx["email_ao_corretor"]
    assert recebido["calendario"] is ctx["calendario"]


async def test_startup_recusa_subir_com_refresh_token_sem_client_secret(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Com o refresh token preenchido, id e segredo do cliente passam a ser
    obrigatorios -- sem isso o Google recusaria o token na primeira tentativa
    de criar um evento, silenciosamente para quem nao esta olhando o log do
    job."""
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh-de-teste")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id-de-teste")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "")

    with pytest.raises(ConfiguracaoInsegura, match="GOOGLE_CALENDAR_CLIENT_SECRET"):
        await startup({})


async def test_startup_recusa_subir_com_refresh_token_sem_client_id(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh-de-teste")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "segredo-de-teste")

    with pytest.raises(ConfiguracaoInsegura, match="GOOGLE_CALENDAR_CLIENT_ID"):
        await startup({})


async def test_o_worker_nao_sobe_sem_host_de_smtp(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Sem SMTP, a notificacao volta a ser descartada em silencio.

    Mesma razao da guarda de WHATSAPP_ACCESS_TOKEN logo acima dela: o defeito
    nao e a entrega falhar, e ninguem ficar sabendo que ela falhou.
    """
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "")

    with pytest.raises(ConfiguracaoInsegura, match="SMTP_HOST"):
        await startup({})


async def test_o_worker_nao_sobe_sem_remetente(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Host sem remetente nao entrega: o provedor recusa envelope sem MAIL FROM."""
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "")

    with pytest.raises(ConfiguracaoInsegura, match="SMTP_REMETENTE"):
        await startup({})


def _producao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Producao COM os outros segredos proprios.

    Sem isto os validators de `Settings` recusariam antes, pela chave de cifra
    e pelo token de catalogo de desenvolvimento, e o teste passaria pelo
    motivo errado.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "token-de-catalogo-proprio")
    # TEC-201: a terceira guarda do mesmo tipo. Sem isto ela dispara primeiro e
    # o teste passaria pelo motivo errado -- exatamente o que o docstring acima
    # ja dizia das outras duas.
    monkeypatch.setenv("JWT_SEGREDO", "segredo-de-jwt-proprio-com-32-bytes-ou-mais")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")


async def test_startup_recusa_subir_em_producao_sem_a_chave_de_embedding(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """D10, a metade "recusa em producao".

    Sem a chave o `get_client()` so levantaria dentro do `except Exception` do
    laco de lotes da varredura, que loga e segue: nenhum imovel seria indexado
    nunca, a busca semantica perderia o termo de similaridade e ordenaria so
    por aderencia de preco, e o unico sintoma seria um aviso por lote a cada
    30 segundos. A guarda barra antes de qualquer job rodar.
    """
    _producao(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(ConfiguracaoInsegura, match="OPENAI_API_KEY"):
        await startup({})


async def test_startup_sobe_em_desenvolvimento_sem_a_chave_de_embedding(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """A outra metade da D10: fora de producao a ausencia nao trava ninguem.

    "Falhar alto" e "nao poluir o log a cada 30 segundos" nao cabem juntos num
    cron -- em desenvolvimento quem avisa e a varredura, uma unica vez.
    """
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    # TEC-280: mesma razao do teste "sobe" acima -- a guarda de SMTP e
    # incondicional e este teste precisa chegar ate a asercao.
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")

    # Mesmo motivo do outro teste "sobe": sem o ARQ em volta, `ctx["redis"]`
    # nao existe sozinho, e um objeto qualquer basta -- ver o comentario la.
    ctx: dict = {"redis": object()}
    await startup(ctx)

    assert ctx["settings"].openai_api_key in (None, "")


def test_sweep_followups_esta_registrado_no_cron_de_cinco_em_cinco_minutos() -> None:
    """O entregavel inteiro da TEC-183 e "roda sozinho a cada 5 minutos" --
    sem este teste, apagar a entrada `cron(...)` nao quebra nada na suite, e a
    cadencia para de disparar em producao sem que nenhum teste perceba.

    `functions` e o que o worker aceita executar por enqueue explicito, pelo
    nome -- pinar essa lista aqui nao e sobre o cron rodar ou nao, e sobre a
    funcao continuar disponivel para quem quiser a enfileirar a mao. Quem de
    fato agenda a execucao periodica e `cron_jobs`: `Worker.__init__`
    (`arq/worker.py`) faz `self.functions.update({cj.name: cj for cj in
    self.cron_jobs})`, entao um cron job se auto-registra sob `cron:<nome>` --
    apagar a entrada de `functions` NAO pararia a cadencia de disparar, so
    tiraria o enqueue manual. O conjunto de minutos e o de cinco em cinco que
    o comentario do registro em `workers/main.py` justifica."""
    from mobia.workers.jobs.sweep_followups import sweep_followups
    from mobia.workers.main import WorkerSettings

    assert sweep_followups in WorkerSettings.functions

    candidatos = [job for job in WorkerSettings.cron_jobs if job.coroutine is sweep_followups]
    assert len(candidatos) == 1
    assert candidatos[0].minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}


def test_sweep_importacoes_travadas_esta_registrado_no_cron_de_cinco_em_cinco_minutos() -> None:
    """O entregavel inteiro da TEC-261 e "roda sozinho a cada 5 minutos" --
    sem este teste, apagar a entrada `cron(...)` nao quebra nada na suite: os
    quatro testes de `test_sweep_importacoes_travadas.py` chamam a funcao
    direto, sem passar pelo `WorkerSettings`. O sintoma silencioso seria
    importacao presa em PROCESSANDO para sempre, exatamente o defeito que
    esta card existe para matar.

    `functions` e o que o worker aceita executar por enqueue explicito, pelo
    nome -- pinar essa lista aqui nao e sobre o cron rodar ou nao, e sobre a
    funcao continuar disponivel para quem quiser a enfileirar a mao. Quem de
    fato agenda a execucao periodica e `cron_jobs`, no mesmo mecanismo que o
    teste irmao de `sweep_followups` acima descreve. O conjunto de minutos e
    o de cinco em cinco que o comentario do registro em `workers/main.py`
    justifica.
    """
    from mobia.workers.jobs.sweep_importacoes_travadas import sweep_importacoes_travadas
    from mobia.workers.main import WorkerSettings

    assert sweep_importacoes_travadas in WorkerSettings.functions

    candidatos = [
        job for job in WorkerSettings.cron_jobs if job.coroutine is sweep_importacoes_travadas
    ]
    assert len(candidatos) == 1
    assert candidatos[0].minute == {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}


def test_job_timeout_cabe_dentro_da_janela_do_sweeper() -> None:
    """Tres numeros sao acoplados, e moram em dois arquivos diferentes.

    `sweep_inflight_after_seconds` mede `COALESCE(queued_at, created_at)`
    (`sweep_stalled.py`) -- e `queued_at` e carimbado na INGESTAO, antes da
    janela de debounce da RN-01.6 (TEC-128). O orcamento real entre o carimbo
    e o fim do turno nao e so `job_timeout`: e `debounce_de_rajada_segundos +
    job_timeout`, porque toda mensagem espera a janela antes de o job sequer
    comecar (D1 do desenho da TEC-128 -- o debounce e incondicional). Sem a
    janela na conta, `job_timeout` sozinho caber dentro do sweeper nao
    garante nada: com os defaults de hoje 240 < 300 tambem seria verdade se a
    janela fosse 59s, e mesmo assim o sweeper reenfileiraria um turno ainda em
    voo -- a mesma conversa rodaria duas vezes em paralelo, pagando duas
    classificacoes.

    **A outra metade desta invariante -- o turno real caber no `job_timeout` --
    NAO esta aqui**, e ja esteve. Ate a TEC-229 este teste tambem afirmava
    `TIMEOUT_SEGUNDOS * 2 <= job_timeout`, supondo duas chamadas ao provedor
    por turno. O turno faz cinco fatias, duas delas com duas requisicoes e
    duas com um numero derivado de `contexto_max_iteracoes` -- e
    `TIMEOUT_SEGUNDOS` nem governa chamada do turno, e o piso de quem nao pede
    teto proprio (`followup/prosa.py`, `handoff/resumo.py`). A assercao passava
    por empate exato quando foi escrita e, depois que a TEC-228 zerou
    `MAX_TENTATIVAS`, passou a passar com folga de 2x sobre um numero que nao
    mede nada do turno.

    A conta do turno mora em `tests/unit/test_orcamento_do_turno.py`, que soma
    os quatro clientes externos importando cada teto de quem o define. Nao
    reconstrua o grafo de chamadas aqui: dois dos cinco testes daquele arquivo
    estao `xfail` porque a conta nao fecha, mas `test_o_orcamento_estourado_nao_piora`
    e verde e afirma `job_timeout >= 240`, mais forte que qualquer piso que
    este teste poderia declarar aqui.

    A TEC-205 acrescentou o terceiro candidato a espera: `atraso_de_backoff_segundos`
    (30s por default) substitui a janela de debounce no caminho do excedente do
    rate limit. Com os defaults de hoje a folga cai de 54s para 30s --
    max(6, 30) + 240 = 270 < 300. Subir o backoff sem olhar este teste reabre a
    conta.
    """
    from mobia.app.config import get_settings
    from mobia.workers.main import WorkerSettings

    settings = get_settings()
    # Desde a TEC-205 o atraso que antecede o job nem sempre e a janela de
    # debounce: o excedente do rate limit por numero e enfileirado com
    # `atraso_de_backoff_segundos` no lugar dela. Quem precisa caber e o MAIOR
    # dos dois, porque e ele que define o pior caso entre o carimbo de
    # `queued_at` (feito na ingestao, antes de qualquer espera) e o fim do
    # turno.
    espera_maxima_antes_do_job = max(
        settings.debounce_de_rajada_segundos,
        settings.atraso_de_backoff_segundos,
    )
    assert (
        espera_maxima_antes_do_job + WorkerSettings.job_timeout
        < settings.sweep_inflight_after_seconds
    )


def test_job_completion_wait_passa_do_job_timeout() -> None:
    """A invariante que faz o deploy nunca cancelar um job por conta propria.

    `job_completion_wait` maior que `job_timeout` significa que a drenagem
    sempre cabe o orcamento inteiro do turno: no SIGTERM o job termina, ou
    estoura o proprio `job_timeout`, que e falha de verdade e conta certo em
    `attempts`. Inverter a relacao -- subir o `job_timeout` sem subir a
    drenagem, o jeito provavel de isto quebrar -- traz de volta o deploy que
    cancela turno em voo e queima uma das cinco tentativas por restart.
    """
    from mobia.workers.main import WorkerSettings

    assert WorkerSettings.job_completion_wait > WorkerSettings.job_timeout


async def test_arq_instala_o_handler_que_drena_no_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O `job_completion_wait` chegar ao `Worker` nao e obvio nem barulhento.

    O arq monta o worker com `get_kwargs`, que filtra
    `WorkerSettings.__dict__` pela assinatura do `Worker` e **descarta em
    silencio** o que nao casa. Renomear o atributo, ou transforma-lo em
    property, faz a configuracao virar no-op sem erro nenhum -- e o deploy
    volta a cancelar job em voo. Por isso o teste olha o handler que o arq de
    fato registra no SIGTERM, e nao o valor da constante, que passaria intacto
    nesse caso.

    O espiao tambem e o que torna o teste portavel: no Windows o
    `loop.add_signal_handler` levanta `NotImplementedError` e o arq engole,
    entao inspecionar o loop de verdade so valeria no Linux do CI.
    """
    from arq.worker import Worker, create_worker

    from mobia.workers.main import WorkerSettings

    registrados: dict[signal.Signals, str] = {}
    monkeypatch.setattr(
        Worker,
        "_add_signal_handler",
        lambda self, signum, handler: registrados.__setitem__(signum, handler.__name__),
    )

    create_worker(WorkerSettings)

    assert registrados[signal.SIGTERM] == "handle_sig_wait_for_completion"
    assert registrados[signal.SIGINT] == "handle_sig_wait_for_completion"

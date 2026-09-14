import base64
import signal

import pytest

from mobia.app.config import ConfiguracaoInsegura
from mobia.domain.outbound.whatsapp import WhatsAppOutbound
from mobia.workers.main import startup


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
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")

    # `redis` entra a mao aqui porque este teste chama `startup` direto, sem o
    # ARQ em volta -- em producao e o proprio ARQ que grava `ctx["redis"]`
    # antes de chamar o hook (ver o docstring de `startup`). Um objeto
    # qualquer basta: `AgendadorArq.__init__` so guarda a referencia, nunca
    # conecta, e a fixture `redis_pool` chamaria `get_settings()` cedo demais
    # -- antes do `monkeypatch.setenv` acima -- e deixaria o cache de
    # `Settings` sem o token, furando este proprio teste.
    ctx: dict = {"redis": object()}
    await startup(ctx)

    assert isinstance(ctx["outbound"], WhatsAppOutbound)
    assert "classificador" in ctx
    assert "resumidor" in ctx
    assert "contador" in ctx
    assert "agendador" in ctx
    assert "reenfileirador" in ctx


def _producao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Producao COM os outros segredos proprios.

    Sem isto os validators de `Settings` recusariam antes, pela chave de cifra
    e pelo token de catalogo de desenvolvimento, e o teste passaria pelo
    motivo errado.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "token-de-catalogo-proprio")
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
    """Os dois numeros sao acoplados e moram em arquivos diferentes.

    `job_timeout` >= `sweep_inflight_after_seconds` faria o sweeper
    reenfileirar um turno ainda em voo: a mesma conversa rodaria duas vezes em
    paralelo, pagando duas classificacoes. E o timeout tem de ser maior que o
    turno real (count_tokens + resumir + classificar + POST na Meta), senao o
    ARQ cancela e `CancelledError` escapa do `except Exception` de
    `process_message`.
    """
    from mobia.app.config import get_settings
    from mobia.infra.anthropic import MAX_TENTATIVAS, TIMEOUT_SEGUNDOS
    from mobia.workers.main import WorkerSettings

    assert WorkerSettings.job_timeout < get_settings().sweep_inflight_after_seconds
    assert WorkerSettings.job_timeout >= 180
    # As duas chamadas pesadas do turno com dobra (resumir + classificar) tem
    # de caber no pior caso do cliente, senao a falha tipada nunca acontece --
    # o ARQ cancela antes, e cancelamento nao e recuperavel.
    pior_caso_por_chamada = TIMEOUT_SEGUNDOS * (1 + MAX_TENTATIVAS)
    assert pior_caso_por_chamada * 2 <= WorkerSettings.job_timeout


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

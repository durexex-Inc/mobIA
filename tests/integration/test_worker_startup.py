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

    ctx: dict = {}
    await startup(ctx)

    assert isinstance(ctx["outbound"], WhatsAppOutbound)
    assert "classificador" in ctx
    assert "resumidor" in ctx
    assert "contador" in ctx


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
    from mobia.workers.main import WorkerSettings

    assert WorkerSettings.job_timeout < get_settings().sweep_inflight_after_seconds
    assert WorkerSettings.job_timeout >= 180

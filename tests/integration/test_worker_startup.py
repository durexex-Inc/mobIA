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

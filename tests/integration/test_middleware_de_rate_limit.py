"""O limite de 100 req/min por IP, e de quem ele nao vale (TEC-205)."""

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.limites.models import ESCOPO_IP, RateLimitEvent


async def test_dentro_do_limite_passa(client, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "5")
    get_settings.cache_clear()

    for _ in range(5):
        assert (await client.get("/health")).status_code == 200


async def test_o_excedente_recebe_429_com_retry_after(client, monkeypatch) -> None:
    """429 aqui e seguro justamente porque o webhook da Meta esta isento."""
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "3")
    get_settings.cache_clear()

    for _ in range(3):
        await client.get("/docs")
    resposta = await client.get("/docs")

    assert resposta.status_code == 429
    assert resposta.headers["Retry-After"] == "60"


async def test_o_webhook_da_meta_nao_e_limitado(client, monkeypatch) -> None:
    """O trafego dali chega todo do IP da Meta: 100/min nao conteria abuso,
    derrubaria operacao -- e derrubaria com 429, que e nao-2xx e faria a Meta
    re-entregar, exatamente o retry que o desenho da TEC-122 evita.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(20):
        resposta = await client.post("/webhooks/whatsapp", content=b"{}")
        assert resposta.status_code != 429


async def test_health_nao_e_limitado(client, monkeypatch) -> None:
    """Probe de liveness batendo acima do limite receberia 429 e o orquestrador
    reiniciaria o processo -- o limitador derrubando o que devia proteger.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    for _ in range(10):
        assert (await client.get("/health")).status_code == 200


async def test_o_bloqueio_por_ip_vira_evento(client, session, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(6):
        await client.get("/docs")

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.escopo == ESCOPO_IP
    assert linha.limite == 2
    assert linha.volume == 3
    assert linha.message_id is None


async def test_limite_zero_desliga_o_middleware(client, session, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "0")
    get_settings.cache_clear()

    for _ in range(50):
        assert (await client.get("/docs")).status_code == 200
    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0

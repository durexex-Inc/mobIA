"""O limite de 100 req/min por IP, e de quem ele nao vale (TEC-205)."""

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.limites.models import ESCOPO_IP, RateLimitEvent


async def test_dentro_do_limite_passa(client, monkeypatch, caches_de_cliente_limpos) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "5")
    get_settings.cache_clear()

    for _ in range(5):
        assert (await client.get("/health")).status_code == 200


async def test_o_excedente_recebe_429_com_retry_after(
    client, monkeypatch, caches_de_cliente_limpos
) -> None:
    """429 aqui e seguro justamente porque o webhook da Meta esta isento."""
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "3")
    get_settings.cache_clear()

    for _ in range(3):
        await client.get("/docs")
    resposta = await client.get("/docs")

    assert resposta.status_code == 429
    assert resposta.headers["Retry-After"] == "60"


async def test_o_webhook_da_meta_nao_e_limitado(
    client, monkeypatch, caches_de_cliente_limpos
) -> None:
    """O trafego dali chega todo do IP da Meta: 100/min nao conteria abuso,
    derrubaria operacao -- e derrubaria com 429, que e nao-2xx e faria a Meta
    re-entregar, exatamente o retry que o desenho da TEC-122 evita.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(20):
        resposta = await client.post("/webhooks/whatsapp", content=b"{}")
        assert resposta.status_code != 429


async def test_health_nao_e_limitado(client, monkeypatch, caches_de_cliente_limpos) -> None:
    """Probe de liveness batendo acima do limite receberia 429 e o orquestrador
    reiniciaria o processo -- o limitador derrubando o que devia proteger.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    for _ in range(10):
        assert (await client.get("/health")).status_code == 200


async def test_o_bloqueio_por_ip_vira_evento(
    client, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(6):
        await client.get("/docs")

    linha = (await session.execute(select(RateLimitEvent))).scalar_one()
    assert linha.escopo == ESCOPO_IP
    assert linha.limite == 2
    assert linha.volume == 3
    assert linha.message_id is None


async def test_x_forwarded_for_da_cota_propria_por_ip(
    client, monkeypatch, caches_de_cliente_limpos
) -> None:
    """O fio entre `resolver_ip` (testado isolado em
    `tests/unit/test_resolucao_de_ip.py`) e o `dispatch` do middleware nao era
    exercitado por nada: os seis vizinhos deste arquivo rodam todos com
    `CONFIAR_EM_FORWARDED_FOR` no default `False`. Um erro de grafia no nome
    do header nao reprovaria um teste sequer, e o sintoma em producao seria
    silencioso -- o limite por IP virando limite global por proxy.

    Duas cotas do mesmo socket (o transporte ASGI de teste sempre usa o
    mesmo), distinguidas so pelo `X-Forwarded-For`: uma estoura, a outra
    continua livre. Se as duas cotas fossem a mesma -- o bug que este teste
    existe para prender --, a sexta requisicao do segundo IP tambem levaria
    429.
    """
    monkeypatch.setenv("CONFIAR_EM_FORWARDED_FOR", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "5")
    get_settings.cache_clear()

    for _ in range(5):
        resposta = await client.get("/docs", headers={"X-Forwarded-For": "203.0.113.10"})
        assert resposta.status_code == 200
    estourou = await client.get("/docs", headers={"X-Forwarded-For": "203.0.113.10"})
    assert estourou.status_code == 429

    for _ in range(5):
        resposta = await client.get("/docs", headers={"X-Forwarded-For": "203.0.113.20"})
        assert resposta.status_code == 200


async def test_limite_zero_desliga_o_middleware(
    client, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "0")
    get_settings.cache_clear()

    for _ in range(50):
        assert (await client.get("/docs")).status_code == 200
    assert (
        await session.execute(select(func.count()).select_from(RateLimitEvent))
    ).scalar_one() == 0

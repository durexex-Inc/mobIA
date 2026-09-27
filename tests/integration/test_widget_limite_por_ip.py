"""O handshake do widget conta contra o limite por IP. TEC-124, D7; RNF-16.

`RateLimitPorIP` e `BaseHTTPMiddleware`, e essa classe devolve cedo para todo
escopo que nao seja `http`: sem a contagem dentro do endpoint, o `ws://` nunca
era contado. Estes testes sao o que reprova se ela sumir.
"""

from sqlalchemy import select

from mobia.app.config import get_settings
from mobia.domain.limites.models import ESCOPO_IP, RateLimitEvent


async def test_handshake_acima_do_limite_recebe_muitas_tentativas_e_1013(
    ws_cliente, session, monkeypatch, caches_de_cliente_limpos
) -> None:
    """TEC-346, D1: o navegador nao le status de handshake recusado.

    A TEC-124 respondia HTTP 429 com `Retry-After` antes do `accept`. Para um
    navegador isso e so `onclose` 1006, igual a qualquer queda de rede. Agora o
    servidor aceita, diz quanto esperar num frame e fecha com 1013 ("Try
    Again Later"), que a pagina consegue ler.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "2")
    get_settings.cache_clear()

    for _ in range(2):
        async with ws_cliente(ip="198.51.100.9") as ws:
            await ws.aceitar()

    async with ws_cliente(ip="198.51.100.9") as ws:
        await ws.aceitar()
        frame = await ws.receber()
        fechamento = await ws.evento()

    assert frame["tipo"] == "erro"
    assert frame["codigo"] == "muitas_tentativas"
    assert 1 <= frame["aguardeSegundos"] <= 60
    assert frame["mensagem"] == f"Muitas tentativas, aguarde {frame['aguardeSegundos']} s."
    assert fechamento["type"] == "websocket.close"
    assert fechamento["code"] == 1013

    evento = (
        await session.execute(select(RateLimitEvent).where(RateLimitEvent.chave == "198.51.100.9"))
    ).scalar_one()
    assert evento.escopo == ESCOPO_IP
    assert evento.limite == 2
    assert evento.volume == 3


async def test_outro_ip_nao_e_afetado(ws_cliente, monkeypatch, caches_de_cliente_limpos) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    async with ws_cliente(ip="198.51.100.10") as ws:
        await ws.aceitar()
    async with ws_cliente(ip="198.51.100.11") as ws:
        await ws.aceitar()


async def test_limite_zero_desliga(ws_cliente, monkeypatch, caches_de_cliente_limpos) -> None:
    # Mesmo contrato do middleware: 0 desliga, e nao "recusa tudo".
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "0")
    get_settings.cache_clear()

    for _ in range(3):
        async with ws_cliente(ip="198.51.100.12") as ws:
            await ws.aceitar()

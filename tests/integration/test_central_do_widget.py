"""Uma assinatura no Redis por processo, e nao uma por aba. TEC-124, revisao final.

Com uma assinatura por aba, cada conexao anonima segurava uma conexao do pool
do Redis enquanto vivesse -- e o limite por IP conta handshakes por minuto, nao
conexoes simultaneas. Um IP so esgotaria o `maxclients` do MESMO Redis que e a
fila do ARQ, derrubando o WhatsApp junto com o widget.
"""

import asyncio
import json
from typing import Any

from mobia.domain.outbound.web import PREFIXO_DA_SESSAO, canal_da_sessao


async def _abrir(ws_cliente) -> tuple[Any, str]:
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": None})
    return ws, (await ws.receber())["sessao"]


async def _ate(condicao, *, segundos: float = 10.0) -> None:
    """Espera uma condicao assincrona virar verdade, com teto."""

    async def _esperar() -> None:
        while not await condicao():
            await asyncio.sleep(0.05)

    await asyncio.wait_for(_esperar(), timeout=segundos)


async def test_tres_abas_seguram_uma_assinatura_so(ws_cliente, redis_pool) -> None:
    abas = [await _abrir(ws_cliente) for _ in range(3)]
    try:
        assert await redis_pool.pubsub_numpat() == 1
        for _, sessao in abas:
            assert await redis_pool.pubsub_numsub(canal_da_sessao(sessao)) == [
                (canal_da_sessao(sessao).encode(), 0)
            ]
    finally:
        for ws, _ in abas:
            await ws.__aexit__()


async def test_a_desconexao_tira_a_aba_da_central(ws_cliente, app_do_widget) -> None:
    # Le o estado da central porque nao ha comportamento observavel de fora:
    # uma fila esquecida so apareceria como memoria crescendo devagar.
    ws, sessao = await _abrir(ws_cliente)
    assert sessao in app_do_widget.state.central_do_widget._filas
    await ws.__aexit__()

    assert sessao not in app_do_widget.state.central_do_widget._filas


async def test_a_central_se_reconecta_depois_de_perder_o_redis(ws_cliente, redis_pool) -> None:
    """A conexao de pub/sub morre (restart, failover) e a aba aberta volta a receber.

    `CLIENT KILL TYPE pubsub` e a forma mais proxima de uma queda real: o
    servidor fecha o socket, e o cliente descobre no proximo `listen`.
    """
    ws, sessao = await _abrir(ws_cliente)
    try:
        await redis_pool.execute_command("CLIENT", "KILL", "TYPE", "pubsub")

        async def _reassinou() -> bool:
            return await redis_pool.pubsub_numpat() == 1

        # Primeiro cai para zero, depois volta: sem esperar a volta, o publish
        # abaixo poderia cair no intervalo em que ninguem ouve.
        await _ate(_reassinou)
        await redis_pool.publish(
            canal_da_sessao(sessao),
            json.dumps({"tipo": "mensagem", "texto": "voltei", "kind": "resposta"}),
        )
        assert (await ws.receber())["texto"] == "voltei"
    finally:
        await ws.__aexit__()


def test_o_padrao_cobre_so_o_namespace_do_widget() -> None:
    # Um padrao largo demais (`*`) faria a central receber tambem o que o
    # ARQ e o limitador publicam no mesmo Redis.
    from mobia.api.central_do_widget import PADRAO

    assert PADRAO == f"{PREFIXO_DA_SESSAO}:*"

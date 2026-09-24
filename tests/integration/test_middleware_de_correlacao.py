"""O `X-Request-Id` lido na entrada e levado ao log (TEC-368, RNF-34).

Os eventos sao lidos por `caplog` e nao por captura de stdout: o
`configure_logging` manda o structlog para o logging da stdlib
(`structlog.stdlib.LoggerFactory`), entao a linha JSON ja renderizada chega
como mensagem de um `LogRecord`. Capturar stdout seria fragil -- o
`basicConfig` prende o handler ao `sys.stdout` do momento em que roda, e o
pytest troca esse objeto.
"""

import json
import logging
import re

from mobia.app.config import get_settings
from mobia.app.logging import correlation_id

_UUID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

CABECALHO = "X-Request-Id"


def _eventos(caplog) -> list[dict]:
    """As linhas de log que sao JSON do structlog, ja decodificadas."""
    eventos = []
    for registro in caplog.records:
        try:
            eventos.append(json.loads(registro.getMessage()))
        except (json.JSONDecodeError, TypeError):
            continue
    return eventos


async def test_o_id_de_entrada_volta_no_cabecalho_da_resposta(client) -> None:
    resposta = await client.get("/health", headers={CABECALHO: "req-do-bff-123"})

    assert resposta.status_code == 200
    assert resposta.headers[CABECALHO] == "req-do-bff-123"


async def test_a_requisicao_sem_o_cabecalho_ganha_um_id(client) -> None:
    """Toda requisicao HTTP passa a ter correlacao, e nao so as que vem do BFF."""
    resposta = await client.get("/health")

    assert _UUID.match(resposta.headers[CABECALHO])


async def test_o_id_de_entrada_chega_ao_evento_de_log(client, caplog) -> None:
    """O criterio de aceite central: o id que o BFF mandou aparece no log daqui.

    Prova, de passagem, algo que so um teste pode afirmar com honestidade: o
    `set()` feito ANTES de `call_next` e visto DENTRO do handler, apesar de o
    `BaseHTTPMiddleware` rodar o app de baixo numa task separada.
    """
    with caplog.at_level(logging.INFO):
        await client.post(
            "/webhooks/whatsapp",
            content=b"{}",
            headers={CABECALHO: "req-que-atravessa"},
        )

    correlacionados = [e for e in _eventos(caplog) if e.get("correlation_id")]
    assert correlacionados, "nenhum evento de log saiu com correlation_id"
    assert all(e["correlation_id"] == "req-que-atravessa" for e in correlacionados)


async def test_id_malformado_e_substituido_e_a_requisicao_segue(client, caplog) -> None:
    """A requisicao NAO e recusada: e cabecalho de diagnostico, nao credencial."""
    with caplog.at_level(logging.INFO):
        resposta = await client.post(
            "/webhooks/whatsapp", content=b"{}", headers={CABECALHO: "tem espaco"}
        )

    assert resposta.status_code == 200
    assert _UUID.match(resposta.headers[CABECALHO])

    correlacionados = [e for e in _eventos(caplog) if e.get("correlation_id")]
    assert correlacionados
    assert all(e["correlation_id"] != "tem espaco" for e in correlacionados)


async def test_o_id_nao_vaza_para_a_requisicao_seguinte(client) -> None:
    """O `reset` do token no `finally`, exercitado."""
    primeira = await client.get("/health", headers={CABECALHO: "id-da-primeira"})
    segunda = await client.get("/health")

    assert primeira.headers[CABECALHO] == "id-da-primeira"
    assert segunda.headers[CABECALHO] != "id-da-primeira"
    # E o ContextVar volta ao default fora do ciclo da requisicao.
    assert correlation_id.get() == ""


async def test_correlacao_envolve_o_limitador(
    client, monkeypatch, caches_de_cliente_limpos, caplog
) -> None:
    """A ordem dos dois `add_middleware` em `create_app`, travada por teste.

    O `RateLimitPorIP` emite `ratelimit.blocked` e devolve 429 **sem chamar
    `call_next`**. Se a correlacao estivesse por dentro dele, ela nao rodaria
    nesse caminho: o evento de bloqueio -- exatamente o que alguem vai depurar
    -- sairia sem `correlation_id`, e o 429 sem o cabecalho.

    Trocar as duas linhas de `create_app` de lugar nao reprova em nenhum dos
    tres gates estaticos. Reprova aqui.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    await client.get("/docs")
    with caplog.at_level(logging.WARNING):
        bloqueada = await client.get("/docs", headers={CABECALHO: "req-que-levou-429"})

    assert bloqueada.status_code == 429
    assert bloqueada.headers[CABECALHO] == "req-que-levou-429"

    bloqueios = [e for e in _eventos(caplog) if e.get("event") == "ratelimit.blocked"]
    assert bloqueios, "o evento de bloqueio nao saiu"
    assert all(e.get("correlation_id") == "req-que-levou-429" for e in bloqueios)

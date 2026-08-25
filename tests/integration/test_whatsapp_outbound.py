import uuid

import httpx
import pytest

from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
from mobia.domain.outbound.whatsapp import EnvioForaDaJanela, WhatsAppOutbound
from mobia.infra.db import get_sessionmaker

PAYLOAD = {"para": "5511911112222", "de": "222222222", "texto": "Ola! Em qual regiao voce procura?"}


def cliente_que_responde(resposta: httpx.Response) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _: resposta))


def cliente_que_estoura(erro: Exception) -> httpx.AsyncClient:
    def _levanta(_: httpx.Request) -> httpx.Response:
        raise erro

    return httpx.AsyncClient(transport=httpx.MockTransport(_levanta))


async def entregar(cliente: httpx.AsyncClient) -> None:
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente)
    await outbound._deliver(uuid.uuid4(), "reply", PAYLOAD)


async def test_entrega_bem_sucedida_nao_levanta(session) -> None:
    await entregar(
        cliente_que_responde(httpx.Response(200, json={"messages": [{"id": "wamid.X"}]}))
    )


async def test_erro_de_rede_e_retentavel(session) -> None:
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_estoura(httpx.ConnectError("sem rota")))


async def test_5xx_e_retentavel(session) -> None:
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_responde(httpx.Response(503, json={})))


async def test_429_e_retentavel(session) -> None:
    """429 e 4xx na faixa numerica, mas e o servidor pedindo para tentar depois.

    Nao e o cliente que errou -- classificar como permanente perde a resposta
    ao lead para sempre.
    """
    with pytest.raises(EnvioRetentavel):
        await entregar(
            cliente_que_responde(
                httpx.Response(429, json={"error": {"code": 4, "message": "rate limit"}})
            )
        )


async def test_408_e_retentavel(session) -> None:
    """Mesmo raciocinio do 429: timeout do servidor nao e payload invalido."""
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_responde(httpx.Response(408, json={})))


async def test_4xx_comum_e_recusa_permanente(session) -> None:
    """Payload invalido nao melhora com retentativa."""
    with pytest.raises(EnvioRecusado) as exc_info:
        await entregar(
            cliente_que_responde(
                httpx.Response(400, json={"error": {"code": 100, "message": "invalido"}})
            )
        )

    # A classificacao de tres vias e o ponto central desta tarefa: um 4xx
    # comum precisa cair no tipo base, nunca no subtipo de janela expirada.
    assert type(exc_info.value) is EnvioRecusado


async def test_fora_da_janela_de_24h_tem_excecao_propria(session) -> None:
    """Codigo 131047 da Meta: passaram mais de 24h desde a ultima fala do lead.

    Precisa ser distinguivel de um 4xx comum porque o turno termina como
    PROCESSED com log de aviso, nao como erro de payload.
    """
    with pytest.raises(EnvioForaDaJanela):
        await entregar(
            cliente_que_responde(
                httpx.Response(400, json={"error": {"code": 131047, "message": "reengagement"}})
            )
        )


async def test_erro_da_meta_nao_carrega_o_texto_no_log(session, caplog) -> None:
    """O texto enviado e fala do agente para o lead, e nao pode ir para o log."""
    import logging

    with caplog.at_level(logging.WARNING):
        with pytest.raises(EnvioRecusado):
            await entregar(
                cliente_que_responde(
                    httpx.Response(400, json={"error": {"code": 100, "message": "invalido"}})
                )
            )

    assert "Em qual regiao" not in caplog.text

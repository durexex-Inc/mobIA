"""O handshake do widget so passa da origem do painel. TEC-365.

O `frame-ancestors` da TEC-345 impede outro site de embutir o iframe, mas nao
impede outra pagina de abrir o WebSocket direto. Estes testes sao o que
reprova se a checagem do `Origin` sumir.
"""

from conftest import ORIGEM_DO_PAINEL_NOS_TESTES, eventos_de_log

from mobia.app.config import get_settings


async def test_origem_do_painel_e_aceita(ws_cliente) -> None:
    """Primeiro cenario da card."""
    async with ws_cliente(origem=ORIGEM_DO_PAINEL_NOS_TESTES) as ws:
        await ws.aceitar()


async def test_origem_desconhecida_recebe_403_e_fica_no_log(ws_cliente, caplog) -> None:
    """Segundo cenario da card: recusado antes do `accept`, e registrado."""
    async with ws_cliente(origem="https://copia-do-site.com", ip="198.51.100.40") as ws:
        status, _ = await ws.recusa()
    assert status == 403

    ((nivel, corpo),) = eventos_de_log(caplog, "widget.origem_recusada")
    assert nivel == "WARNING"
    assert corpo["origem"] == "https://copia-do-site.com"
    # A mascara de PII do log cobre corridas de digitos, entao o IP chega
    # mascarado; o que se afirma e que ele esta la, com o final legivel.
    assert corpo["ip"].endswith("0.40")


async def test_sem_origin_e_recusado(ws_cliente, caplog) -> None:
    """Todo navegador manda `Origin`; quem nao manda nao e o iframe."""
    async with ws_cliente(origem=None) as ws:
        status, _ = await ws.recusa()
    assert status == 403
    ((_, corpo),) = eventos_de_log(caplog, "widget.origem_recusada")
    assert corpo["origem"] is None


async def test_origem_longa_vai_truncada_ao_log(ws_cliente, caplog) -> None:
    async with ws_cliente(origem="https://" + "a" * 5000 + ".com") as ws:
        status, _ = await ws.recusa()
    assert status == 403
    ((_, corpo),) = eventos_de_log(caplog, "widget.origem_recusada")
    assert len(corpo["origem"]) == 200


async def test_lista_vazia_recusa_ate_o_painel(ws_cliente, monkeypatch) -> None:
    """D2: sem `ORIGENS_DO_WIDGET`, nenhuma conversa conecta."""
    monkeypatch.setenv("ORIGENS_DO_WIDGET", "")
    get_settings.cache_clear()

    async with ws_cliente(origem=ORIGEM_DO_PAINEL_NOS_TESTES) as ws:
        status, _ = await ws.recusa()
    assert status == 403


async def test_a_recusa_conta_no_limite_por_ip(ws_cliente, monkeypatch) -> None:
    """D3: a checagem vem depois do limite, entao a tentativa recusada consome
    o balde -- e quem martela de outra pagina acaba na recusa por limite, que
    desde a TEC-346 e `muitas_tentativas` seguido de 1013, e nao mais 429."""
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "1")
    get_settings.cache_clear()

    async with ws_cliente(origem="https://copia-do-site.com", ip="198.51.100.41") as ws:
        status, _ = await ws.recusa()
    assert status == 403
    async with ws_cliente(origem="https://copia-do-site.com", ip="198.51.100.41") as ws:
        await ws.aceitar()
        frame = await ws.receber()
        fechamento = await ws.evento()
    assert frame["codigo"] == "muitas_tentativas"
    assert fechamento["type"] == "websocket.close"
    assert fechamento["code"] == 1013

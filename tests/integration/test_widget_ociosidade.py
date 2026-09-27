"""O servidor fecha o socket ocioso do widget, e a conversa volta. TEC-366.

O prazo real e de 30 minutos (`widget_ociosidade_segundos`); aqui ele e
encurtado pelo ambiente, e o que se afirma e a regra -- sem trafego pelo
prazo inteiro, o servidor fecha com `CODIGO_OCIOSA`; com trafego, nao --, e
que a sessao fechada assim se retoma com o historico.
"""

import asyncio

from conftest import eventos_de_log  # type: ignore[import-not-found]

from mobia.api.routes.widget import CODIGO_OCIOSA
from mobia.app.config import get_settings


async def _cumprimentar(ws, sessao: str | None = None) -> str:
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    frame = await ws.receber()
    assert frame["tipo"] == "sessao"
    return str(frame["sessao"])


def _prazo(monkeypatch, segundos: float) -> None:
    monkeypatch.setenv("WIDGET_OCIOSIDADE_SEGUNDOS", str(segundos))
    get_settings.cache_clear()


async def test_conexao_ociosa_e_fechada_pelo_servidor(ws_cliente, monkeypatch, caplog) -> None:
    """Primeiro cenario da card, com o codigo documentado."""
    _prazo(monkeypatch, 0.3)

    with caplog.at_level("INFO"):
        async with ws_cliente() as ws:
            await _cumprimentar(ws)
            assert await ws.fechamento() == CODIGO_OCIOSA

    (evento,) = eventos_de_log(caplog, "widget.ociosa")
    assert evento.corpo["segundos"] == 0.3


async def test_trafego_adia_o_fechamento(ws_cliente, monkeypatch) -> None:
    """Cada frame recomeca o prazo: quem conversa nao e derrubado.

    Tres mensagens espacadas de 0,3 s atravessam 0,9 s de conexao com um
    prazo de 0,5 s -- fechar pela idade da conexao, e nao pela do ultimo
    frame, derrubaria a segunda. So depois que elas param e que o socket cai.
    """
    _prazo(monkeypatch, 0.5)

    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        for indice in range(3):
            await asyncio.sleep(0.3)
            await ws.enviar({"tipo": "mensagem", "id": f"m-{indice}", "texto": "ainda aqui"})
            assert (await ws.receber())["tipo"] == "ack"
        assert await ws.fechamento() == CODIGO_OCIOSA


async def test_retomar_depois_do_fechamento_por_ociosidade(ws_cliente, monkeypatch) -> None:
    """Segundo cenario da card: a sessao volta, e o historico com ela."""
    _prazo(monkeypatch, 0.3)

    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "antes de dormir"})
        assert (await ws.receber())["tipo"] == "ack"
        assert await ws.fechamento() == CODIGO_OCIOSA

    async with ws_cliente() as ws:
        assert await _cumprimentar(ws, sessao) == sessao
        historico = await ws.receber()

    assert historico["tipo"] == "historico"
    assert [(fala["papel"], fala["texto"]) for fala in historico["mensagens"]] == [
        ("lead", "antes de dormir")
    ]


def test_o_prazo_padrao_e_de_trinta_minutos() -> None:
    """RN-FE-17.7: os mesmos 30 minutos do sono do cliente (TEC-347, D4)."""
    get_settings.cache_clear()
    assert get_settings().widget_ociosidade_segundos == 30 * 60

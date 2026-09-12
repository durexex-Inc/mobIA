"""A porta de entrada da regeneracao (D8) e o link da RN-15.5."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.handoff import resumo as resumo_mod
from mobia.domain.handoff.resumo import MARCADORES, link_da_transcricao

TOKEN = "token-de-teste"


def _resumo_valido() -> str:
    return "\n".join(f"{marcador}\ntexto padrao de teste." for marcador in MARCADORES)


def _resumo_invalido() -> str:
    """Falta o ultimo marcador: `validar()` reprova e `gerar_resumo` devolve False.

    E o texto que faz o redator FALHAR sem o handoff sumir -- o unico jeito de
    chegar ao ramo 502 da rota em vez do 404.
    """
    return "\n".join(f"{marcador}\ntexto padrao de teste." for marcador in MARCADORES[:-1])


class _ClienteFalso:
    """Duble minimo do AsyncAnthropic. Mesmo molde de test_handoff_redator.py."""

    def __init__(self, texto: str) -> None:
        resposta = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=texto)],
            usage=SimpleNamespace(input_tokens=900, output_tokens=400),
            stop_reason="end_turn",
        )
        self.messages = SimpleNamespace(create=AsyncMock(return_value=resposta))


async def _cliente_com_redator(monkeypatch, redis_pool, *, texto_do_redator: str):
    """O corpo comum de `cliente_http` e `cliente_http_redator_falha`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app()`. O redator real
    fala com a Anthropic -- substituir `get_client` pela referencia que
    `resumo.py` guardou (mesmo molde de `tests/unit/test_handoff_redator.py`)
    isola o teste da rede sem precisar tornar o redator injetavel na rota.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    monkeypatch.setattr(resumo_mod, "get_client", lambda: _ClienteFalso(texto_do_redator))
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


@pytest.fixture
async def cliente_http(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde do `app_com_token` de `test_busca_endpoint.py`, com redator valido."""
    async for cliente in _cliente_com_redator(
        monkeypatch, redis_pool, texto_do_redator=_resumo_valido()
    ):
        yield cliente


@pytest.fixture
async def cliente_http_redator_falha(
    monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool
):
    """Mesmo app de `cliente_http`, mas o redator devolve um resumo invalido.

    Existe so para o teste do ramo 502: o handoff precisa estar no banco e
    `gerar_resumo` precisa devolver False por falha do redator, nao por
    handoff ausente.
    """
    async for cliente in _cliente_com_redator(
        monkeypatch, redis_pool, texto_do_redator=_resumo_invalido()
    ):
        yield cliente


async def test_sem_token_e_403(cliente_http) -> None:
    resposta = await cliente_http.post(f"/api/v1/handoffs/{uuid.uuid4()}/resumo")
    assert resposta.status_code == 403


async def test_handoff_inexistente_e_404(cliente_http) -> None:
    """O uuid nunca foi gravado -- este e o ramo "handoff nao existe" da rota.

    Nao confundir com `test_falha_do_redator_e_502_e_nao_404` logo abaixo: la
    o handoff EXISTE e quem falha e o redator. Sao os dois ramos que
    `gerar_resumo -> False` esconde atras do mesmo booleano, e a rota so os
    distingue com o SELECT que este teste prova estar certo.
    """
    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/resumo", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "handoff nao existe"


async def test_falha_do_redator_e_502_e_nao_404(
    cliente_http_redator_falha, semear_lead_completo
) -> None:
    """O handoff existe; quem falhou foi o redator (RN-15.1, bloco ausente).

    Sem este teste, um regressor que colapsasse os dois ramos em 404 para
    sempre atravessaria a suite inteira sem sintoma -- e o 502 e a informacao
    que diz a quem chama "tente de novo" em vez de "esse handoff nao existe".
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    resposta = await cliente_http_redator_falha.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 502
    assert resposta.json()["detail"] == "resumo nao pode ser gerado"


async def test_regenera_e_devolve_o_resumo_com_o_link(cliente_http, semear_lead_completo) -> None:
    """Primeiro cenario do Gherkin: os seis blocos, o limite e o link."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resumo"]) <= 1500
    # O link e campo separado, e nao conteudo do resumo -- ver a D10.
    assert corpo["link"].endswith("/conversas/whatsapp/5511911112222")
    assert corpo["link"] not in corpo["resumo"]


def test_o_link_nao_e_composto_pelo_modelo() -> None:
    assert link_da_transcricao("whatsapp", "5511911112222").endswith(
        "/conversas/whatsapp/5511911112222"
    )

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


class _ClienteFalso:
    """Duble minimo do AsyncAnthropic. Mesmo molde de test_handoff_redator.py."""

    def __init__(self) -> None:
        resposta = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=_resumo_valido())],
            usage=SimpleNamespace(input_tokens=900, output_tokens=400),
            stop_reason="end_turn",
        )
        self.messages = SimpleNamespace(create=AsyncMock(return_value=resposta))


@pytest.fixture
async def cliente_http(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde do `app_com_token` de `tests/integration/test_busca_endpoint.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app()`. O redator real
    fala com a Anthropic -- substituir `get_client` pela referencia que
    `resumo.py` guardou (mesmo molde de `tests/unit/test_handoff_redator.py`)
    isola o teste da rede sem precisar tornar o redator injetavel na rota.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    monkeypatch.setattr(resumo_mod, "get_client", lambda: _ClienteFalso())
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_sem_token_e_403(cliente_http) -> None:
    resposta = await cliente_http.post(f"/api/v1/handoffs/{uuid.uuid4()}/resumo")
    assert resposta.status_code == 403


async def test_handoff_inexistente_e_404(cliente_http) -> None:
    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/resumo", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404


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

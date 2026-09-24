"""O endpoint do painel de funil. TEC-190, RF-17."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app

TOKEN = "token-de-teste-de-metricas"
ROTA = "/api/v1/metricas/funil"
PERIODO = {"de": "2026-08-01", "ate": "2026-08-31"}


@pytest.fixture
async def app_com_token(monkeypatch: Any, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde de `app_com_token` em `test_rota_de_corretores.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app`.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_sem_token_e_403(app_com_token) -> None:
    resposta = await app_com_token.get(ROTA, params=PERIODO)

    assert resposta.status_code == 403


async def test_periodo_sem_lead_devolve_200_com_as_seis_etapas(app_com_token) -> None:
    """Item 5 do Review Focus: vazio e 200, nunca 404."""
    resposta = await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [e["nome"] for e in corpo["etapas"]] == [
        "Novo",
        "Em conversa",
        "Qualificado",
        "Recomendado",
        "Agendado",
        "Handoff aceito",
    ]
    assert corpo["indicadores"]["taxaQualificacao"] is None


async def test_a_etapa_agendado_sai_indisponivel(app_com_token) -> None:
    resposta = await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})

    agendado = next(e for e in resposta.json()["etapas"] if e["nome"] == "Agendado")
    assert agendado["quantidade"] is None
    assert agendado["disponivel"] is False


async def test_os_quatro_indicadores_de_visita_saem_nulos_e_listados(app_com_token) -> None:
    corpo = (await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})).json()

    assert corpo["indisponiveis"] == [
        "agendamentosCriados",
        "agendamentosConfirmados",
        "agendamentosRealizados",
        "taxaNoShow",
    ]
    for chave in corpo["indisponiveis"]:
        assert corpo["indicadores"][chave] is None


async def test_de_depois_de_ate_e_422_nomeando_o_campo(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA,
        params={"de": "2026-08-31", "ate": "2026-08-01"},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 422
    assert "de" in resposta.json()["detail"]


async def test_temperatura_invalida_e_422_e_nao_funil_vazio(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA,
        params={**PERIODO, "temperatura": "MORNA"},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 422
    assert "MORNA" in resposta.json()["detail"]


async def test_data_malformada_e_422(app_com_token) -> None:
    resposta = await app_com_token.get(
        ROTA, params={"de": "ontem", "ate": "2026-08-31"}, headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 422


async def test_periodo_e_obrigatorio(app_com_token) -> None:
    resposta = await app_com_token.get(ROTA, headers={"X-Admin-Token": TOKEN})

    assert resposta.status_code == 422

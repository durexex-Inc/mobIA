"""A aparencia do chat web, lida sem autenticacao. TEC-344, D2 e D3 do desenho.

O loader do site a pede antes de desenhar o botao, pelo servidor do Next. A
rota responde sempre 200, com o slug configurado em `tenant` (ou nulo): quem
compara com o slug do snippet e o Next, porque o Data Cache dele so guarda
resposta 200 (emenda da TEC-344 ao D3).
"""

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from mobia.app.config import get_settings
from mobia.domain.usuarios import tokens

SLUG = "imobiliaria-x"


def _bearer_admin() -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), "ADMIN", mfa=True, corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def com_slug(monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None) -> Iterator[None]:
    monkeypatch.setenv("TENANT_SLUG", SLUG)
    # Vazios, e nao `delenv`: fora de producao o `Settings` le o `.env`.
    monkeypatch.setenv("AVISO_DE_PRIVACIDADE_URL", "")
    monkeypatch.setenv("ENCARREGADO_EMAIL", "")
    get_settings.cache_clear()
    yield


async def test_devolve_a_aparencia_padrao_sem_credencial(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    resposta = await client.get("/widget/aparencia")

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "tenant": SLUG,
        "nomeDoAssistente": None,
        "corPrimaria": "#1D4ED8",
        "posicaoDoBotao": "DIREITA",
        "dominios": [],
        "avisoDePrivacidadeUrl": None,
        "encarregadoEmail": None,
    }


async def test_devolve_o_que_o_admin_configurou(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """Cenario 3 do Gherkin, do lado do backend."""
    await client.patch(
        "/api/v1/configuracao/agente",
        json={
            "nomeDoAssistente": "Lia",
            "corPrimaria": "#0A7F5A",
            "posicaoDoBotao": "ESQUERDA",
            "dominiosDoChat": ["imobiliariasol.com.br"],
        },
        headers=_bearer_admin(),
    )

    resposta = await client.get("/widget/aparencia")

    assert resposta.json() == {
        "tenant": SLUG,
        "nomeDoAssistente": "Lia",
        "corPrimaria": "#0A7F5A",
        "posicaoDoBotao": "ESQUERDA",
        "dominios": ["imobiliariasol.com.br"],
        "avisoDePrivacidadeUrl": None,
        "encarregadoEmail": None,
    }


async def test_devolve_o_aviso_de_privacidade_e_o_encarregado_configurados(
    client: AsyncClient,
    banco_limpo: None,
    com_slug: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TEC-352, D1: a configuracao de implantacao chega a faixa do chat."""
    monkeypatch.setenv("AVISO_DE_PRIVACIDADE_URL", "https://imobiliariasol.com.br/privacidade")
    monkeypatch.setenv("ENCARREGADO_EMAIL", "encarregado@imobiliariasol.com.br")
    get_settings.cache_clear()

    corpo = (await client.get("/widget/aparencia")).json()

    assert corpo["avisoDePrivacidadeUrl"] == "https://imobiliariasol.com.br/privacidade"
    assert corpo["encarregadoEmail"] == "encarregado@imobiliariasol.com.br"


async def test_so_devolve_o_slug_a_aparencia_e_os_dominios(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """D3: tom, pesos, cadencia e orcamento sao do admin e nao saem daqui.
    Os dominios saem desde a TEC-345 (D2), porque o Next precisa deles; o
    aviso de privacidade e o encarregado desde a TEC-352 (D1), porque a faixa
    do chat os mostra a toda visitante."""
    corpo = (await client.get("/widget/aparencia")).json()

    assert set(corpo) == {
        "tenant",
        "nomeDoAssistente",
        "corPrimaria",
        "posicaoDoBotao",
        "dominios",
        "avisoDePrivacidadeUrl",
        "encarregadoEmail",
    }


async def test_sem_slug_configurado_responde_200_com_tenant_nulo(
    client: AsyncClient,
    banco_limpo: None,
    monkeypatch: pytest.MonkeyPatch,
    caches_de_cliente_limpos: None,
) -> None:
    """200 e nao 404: o Data Cache do Next so guarda 200, e um 404 aqui
    chegaria ao FastAPI a cada visita, no balde de rate limit do painel.
    Quem transforma `tenant: null` em 404 para o visitante e o Next.
    """
    # Vazio, e nao `delenv`: fora de producao o `Settings` le o `.env`, e um
    # `TENANT_SLUG` la dentro voltaria pela porta dos fundos. O validador do
    # campo faz do vazio um nulo.
    monkeypatch.setenv("TENANT_SLUG", "")
    get_settings.cache_clear()

    resposta = await client.get("/widget/aparencia")

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["tenant"] is None


async def test_a_rota_antiga_com_slug_no_caminho_nao_existe(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """Um URL por slug seria uma entrada de cache por slug -- e cada slug
    errado, um pedido novo ao FastAPI."""
    assert (await client.get(f"/widget/aparencia/{SLUG}")).status_code == 404

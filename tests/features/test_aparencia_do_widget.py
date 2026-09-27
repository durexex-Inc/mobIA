"""A aparencia do chat web, lida sem autenticacao. TEC-344, D2 e D3 do desenho.

O loader do site a pede antes de desenhar o botao. O slug do snippet tem de
bater com `TENANT_SLUG`; sem ele configurado, nenhum slug bate.
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
    get_settings.cache_clear()
    yield


async def test_devolve_a_aparencia_padrao_sem_credencial(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    resposta = await client.get(f"/widget/aparencia/{SLUG}")

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "nomeDoAssistente": None,
        "corPrimaria": "#1D4ED8",
        "posicaoDoBotao": "DIREITA",
    }


async def test_devolve_o_que_o_admin_configurou(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """Cenario 3 do Gherkin, do lado do backend."""
    await client.patch(
        "/api/v1/configuracao/agente",
        json={"nomeDoAssistente": "Lia", "corPrimaria": "#0A7F5A", "posicaoDoBotao": "ESQUERDA"},
        headers=_bearer_admin(),
    )

    resposta = await client.get(f"/widget/aparencia/{SLUG}")

    assert resposta.json() == {
        "nomeDoAssistente": "Lia",
        "corPrimaria": "#0A7F5A",
        "posicaoDoBotao": "ESQUERDA",
    }


async def test_so_devolve_os_tres_campos_da_aparencia(
    client: AsyncClient, banco_limpo: None, com_slug: None
) -> None:
    """D3: tom, pesos, cadencia e orcamento sao do admin e nao saem daqui."""
    corpo = (await client.get(f"/widget/aparencia/{SLUG}")).json()

    assert set(corpo) == {"nomeDoAssistente", "corPrimaria", "posicaoDoBotao"}


async def test_slug_errado_e_slug_nao_configurado_dao_o_mesmo_404(
    client: AsyncClient,
    banco_limpo: None,
    monkeypatch: pytest.MonkeyPatch,
    caches_de_cliente_limpos: None,
) -> None:
    """D3: responder diferente diria a quem sonda se existe algum tenant."""
    # Vazio, e nao `delenv`: fora de producao o `Settings` le o `.env`, e um
    # `TENANT_SLUG` la dentro voltaria pela porta dos fundos.
    monkeypatch.setenv("TENANT_SLUG", "")
    get_settings.cache_clear()
    sem_slug = await client.get(f"/widget/aparencia/{SLUG}")

    monkeypatch.setenv("TENANT_SLUG", SLUG)
    get_settings.cache_clear()
    errado = await client.get("/widget/aparencia/outra-imobiliaria")

    assert sem_slug.status_code == errado.status_code == 404
    assert sem_slug.json() == errado.json()

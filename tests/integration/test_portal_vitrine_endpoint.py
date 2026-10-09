"""A vitrine paginada do portal, sem credencial nenhuma.

Visual do portal, D7 e D8. Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient

from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.vitrine import IMOVEIS_POR_PAGINA
from mobia.domain.texto import dobrar

_INICIO = datetime(2026, 10, 1, tzinfo=UTC)


async def _semear(session: Any, indice: int, **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    bairro = str(sobrescritas.pop("bairro", "Itacorubi"))
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": f"VT-{indice:03d}",
        "titulo": f"Apartamento {indice}",
        "descricao": "Sala ampla e varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 50_000_000 + indice * 1_000_000,
        "bairro": bairro,
        "bairro_busca": dobrar(bairro),
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 60 + indice,
        "quartos": 2,
        "suites": 1,
        "banheiros": 2,
        "vagas": 1,
        "caracteristicas": [],
        "fotos": [],
        "status": "DISPONIVEL",
        # Um minuto a mais por indice: a ordem "recentes" fica determinada.
        "created_at": _INICIO + timedelta(minutes=indice),
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_pagina_traz_doze_e_o_total_de_todos_os_que_casam(
    client: AsyncClient, session: Any
) -> None:
    for indice in range(IMOVEIS_POR_PAGINA + 2):
        await _semear(session, indice)
    await _semear(session, 99, status="INATIVO")

    primeira = (await client.get("/portal/vitrine", params={"operacao": "VENDA"})).json()
    segunda = (
        await client.get("/portal/vitrine", params={"operacao": "VENDA", "pagina": 2})
    ).json()

    assert primeira["total"] == IMOVEIS_POR_PAGINA + 2
    assert len(primeira["itens"]) == IMOVEIS_POR_PAGINA
    assert primeira["porPagina"] == IMOVEIS_POR_PAGINA
    assert len(segunda["itens"]) == 2
    # Nenhum imovel aparece nas duas paginas, e o inativo em nenhuma.
    codigos = [item["codigo"] for item in primeira["itens"] + segunda["itens"]]
    assert len(set(codigos)) == IMOVEIS_POR_PAGINA + 2
    assert "VT-099" not in codigos


async def test_pagina_alem_da_ultima_vem_vazia_com_o_total(
    client: AsyncClient, session: Any
) -> None:
    await _semear(session, 1)

    corpo = (await client.get("/portal/vitrine", params={"operacao": "VENDA", "pagina": 5})).json()

    assert corpo["itens"] == []
    assert corpo["total"] == 1


async def test_recentes_e_o_padrao_e_menor_preco_inverte(client: AsyncClient, session: Any) -> None:
    for indice in range(3):
        await _semear(session, indice)

    recentes = (await client.get("/portal/vitrine", params={"operacao": "VENDA"})).json()
    baratos = (
        await client.get("/portal/vitrine", params={"operacao": "VENDA", "ordem": "menor_preco"})
    ).json()

    assert [item["codigo"] for item in recentes["itens"]] == ["VT-002", "VT-001", "VT-000"]
    assert [item["codigo"] for item in baratos["itens"]] == ["VT-000", "VT-001", "VT-002"]


async def test_ambos_casa_a_busca_de_aluguel_e_o_preco_e_o_do_aluguel(
    client: AsyncClient, session: Any
) -> None:
    await _semear(session, 1, operacao="AMBOS", preco_aluguel=650_300)
    await _semear(session, 2)

    corpo = (await client.get("/portal/vitrine", params={"operacao": "ALUGUEL"})).json()

    assert [item["codigo"] for item in corpo["itens"]] == ["VT-001"]
    assert corpo["itens"][0]["preco"] == 650_300


async def test_filtro_de_bairro_segue_a_regra_da_busca_do_agente(
    client: AsyncClient, session: Any
) -> None:
    await _semear(session, 1, bairro="Trindade")
    await _semear(session, 2, bairro="Itacorubi")

    corpo = (
        await client.get("/portal/vitrine", params={"operacao": "VENDA", "regioes": "trindade"})
    ).json()

    assert [item["codigo"] for item in corpo["itens"]] == ["VT-001"]
    assert corpo["total"] == 1


async def test_card_traz_foto_publica_tres_caracteristicas_e_coordenada_arredondada(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(
        session,
        1,
        fotos=["/api/v1/imoveis/x/fotos/f-1", "/api/v1/imoveis/x/fotos/f-2"],
        caracteristicas=["varanda", "piscina", "academia", "sauna"],
        latitude=Decimal("-27.583712"),
        longitude=Decimal("-48.505219"),
        condominio=225_900,
    )

    item = (await client.get("/portal/vitrine", params={"operacao": "VENDA"})).json()["itens"][0]

    assert item["foto"] == f"/portal/imoveis/{identificador}/fotos/f-1"
    assert item["caracteristicas"] == ["varanda", "piscina", "academia"]
    assert item["latitude"] == -27.584
    assert item["longitude"] == -48.505
    assert item["condominio"] == 225_900
    assert item["suites"] == 1


async def test_ambos_nao_e_operacao_buscavel(client: AsyncClient) -> None:
    resposta = await client.get("/portal/vitrine", params={"operacao": "AMBOS"})

    assert resposta.status_code == 422

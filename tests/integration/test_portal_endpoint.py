"""A vitrine publica do catalogo, sem credencial nenhuma.

TEC-387. Reaproveita a mesma busca de `test_busca_endpoint.py` -- aqui so a
guarda muda, entao o `_semear` e os numeros de aderencia sao os mesmos.
Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from httpx import AsyncClient

from mobia.domain.catalogo.models import Imovel
from mobia.domain.texto import dobrar


async def _semear(session: Any, **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": "AP-1042",
        "titulo": "Apartamento com vista",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 58000000,
        "bairro": "Vila Mariana",
        "bairro_busca": dobrar("Vila Mariana"),
        "cidade": "Sao Paulo",
        "uf": "SP",
        "zona": "SUL",
        "area_util_m2": 74,
        "quartos": 2,
        "suites": 1,
        "banheiros": 2,
        "vagas": 1,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_ca01_sem_filtro_alem_da_operacao_lista_o_imovel_ativo(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await client.get("/portal/imoveis", params={"operacao": "VENDA"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["totalCandidatos"] == 1
    assert corpo["itens"][0]["id"] == str(identificador)


async def test_ca02_filtro_combinado_so_casa_compativel(client: AsyncClient, session: Any) -> None:
    await _semear(session)

    resposta = await client.get(
        "/portal/imoveis",
        params={
            "operacao": "VENDA",
            "precoMax": 60000000,
            "quartosMin": 3,
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["totalCandidatos"] == 0


async def test_ca03_sem_resultado_devolve_itens_vazio(client: AsyncClient) -> None:
    resposta = await client.get("/portal/imoveis", params={"operacao": "VENDA", "precoMax": 1})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["itens"] == []
    assert corpo["totalCandidatos"] == 0


async def test_ca04_imovel_fora_de_disponivel_nao_aparece(
    client: AsyncClient, session: Any
) -> None:
    await _semear(session, status="VENDIDO")

    resposta = await client.get("/portal/imoveis", params={"operacao": "VENDA"})

    assert resposta.status_code == 200
    assert resposta.json()["totalCandidatos"] == 0


async def test_sem_cabecalho_nenhum_e_200_a_rota_e_publica(
    client: AsyncClient, session: Any
) -> None:
    """A diferenca inteira para `/api/v1/imoveis/busca`: nao ha guarda aqui."""
    await _semear(session)

    resposta = await client.get(
        "/portal/imoveis",
        params={"operacao": "VENDA"},
        headers={"Authorization": "Bearer nao-e-um-token-valido"},
    )

    assert resposta.status_code == 200


async def test_operacao_ausente_e_recusada_com_422(client: AsyncClient) -> None:
    resposta = await client.get("/portal/imoveis")

    assert resposta.status_code == 422


async def test_operacao_ambos_e_recusada_com_422(client: AsyncClient) -> None:
    resposta = await client.get("/portal/imoveis", params={"operacao": "AMBOS"})

    assert resposta.status_code == 422


async def test_relaxamento_funciona_igual_ao_endpoint_interno(
    client: AsyncClient, session: Any
) -> None:
    """RN-09.3 pela borda publica: zero no passe duro relaxa a faixa de preco."""
    identificador = await _semear(session, preco_venda=62000000)

    resposta = await client.get(
        "/portal/imoveis", params={"operacao": "VENDA", "precoMax": 60000000}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["relaxamentoAplicado"] is True
    assert corpo["itens"][0]["id"] == str(identificador)

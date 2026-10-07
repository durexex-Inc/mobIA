"""O pedido de interesse num imovel, pelo portal, sem conversa nenhuma.

TEC-389. Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from mobia.domain.catalogo.models import Imovel
from mobia.domain.texto import dobrar


async def _semear(session: Any, **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": f"AP-{uuid.uuid4().hex[:8]}",
        "titulo": "Apartamento com varanda",
        "descricao": "Sala ampla, dois quartos, varanda com vista para o parque.",
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
        "caracteristicas": [],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_ca01_pedido_valido_registra_e_notifica_corretor(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse",
        json={"telefone": "11988887777", "nome": "Maria", "email": "maria@ex.com"},
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json() == {"recebido": True}

    handoffs = (
        (await session.execute(text("SELECT gatilho, etiqueta, status FROM handoffs")))
        .mappings()
        .all()
    )
    assert len(handoffs) == 1
    assert handoffs[0]["gatilho"] == "INTERESSE_PORTAL"
    assert handoffs[0]["etiqueta"] == "interesse-portal"
    assert handoffs[0]["status"] == "PENDENTE"

    solicitacoes = (
        (
            await session.execute(
                text("SELECT imovel_id, nome, channel FROM solicitacoes_de_interesse")
            )
        )
        .mappings()
        .all()
    )
    assert len(solicitacoes) == 1
    assert str(solicitacoes[0]["imovel_id"]) == str(identificador)
    assert solicitacoes[0]["nome"] == "Maria"
    assert solicitacoes[0]["channel"] == "portal"

    resumo = (await session.execute(text("SELECT resumo FROM handoffs"))).scalar_one()
    assert resumo is not None


async def test_ca02_telefone_ausente_e_422(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session)

    resposta = await client.post(f"/portal/imoveis/{identificador}/interesse", json={})

    assert resposta.status_code == 422


async def test_ca02_telefone_invalido_e_422(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session)

    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse", json={"telefone": "abc"}
    )

    assert resposta.status_code == 422
    assert resposta.json()["detail"] == "telefone invalido"


async def test_ca03_imovel_inexistente_e_404(client: AsyncClient) -> None:
    resposta = await client.post(
        f"/portal/imoveis/{uuid.uuid4()}/interesse", json={"telefone": "11988887777"}
    )

    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "imovel nao disponivel"


async def test_ca03_imovel_indisponivel_e_o_mesmo_404(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session, status="VENDIDO")

    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse", json={"telefone": "11988887777"}
    )

    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "imovel nao disponivel"

    contagem = (
        await session.execute(text("SELECT count(*) FROM solicitacoes_de_interesse"))
    ).scalar_one()
    assert contagem == 0


async def test_ca04_mesmo_telefone_mesmo_imovel_nao_duplica(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)
    corpo = {"telefone": "11988887777", "nome": "Maria"}

    primeira = await client.post(f"/portal/imoveis/{identificador}/interesse", json=corpo)
    segunda = await client.post(f"/portal/imoveis/{identificador}/interesse", json=corpo)

    assert primeira.status_code == 201
    assert segunda.status_code == 201
    assert segunda.json() == {"recebido": True}

    contagem_solicitacoes = (
        await session.execute(text("SELECT count(*) FROM solicitacoes_de_interesse"))
    ).scalar_one()
    assert contagem_solicitacoes == 1

    contagem_handoffs = (await session.execute(text("SELECT count(*) FROM handoffs"))).scalar_one()
    assert contagem_handoffs == 1


async def test_mesmo_telefone_imoveis_diferentes_um_handoff_duas_solicitacoes(
    client: AsyncClient, session: Any
) -> None:
    """D2/D4 do desenho: o handoff e por LEAD, a solicitacao e por IMOVEL."""
    primeiro_imovel = await _semear(session)
    segundo_imovel = await _semear(session)
    telefone = "11988887777"

    await client.post(f"/portal/imoveis/{primeiro_imovel}/interesse", json={"telefone": telefone})
    resposta = await client.post(
        f"/portal/imoveis/{segundo_imovel}/interesse", json={"telefone": telefone}
    )

    assert resposta.status_code == 201

    contagem_handoffs = (await session.execute(text("SELECT count(*) FROM handoffs"))).scalar_one()
    assert contagem_handoffs == 1

    contagem_solicitacoes = (
        await session.execute(text("SELECT count(*) FROM solicitacoes_de_interesse"))
    ).scalar_one()
    assert contagem_solicitacoes == 2


async def test_telefones_diferentes_mesmo_imovel_criam_handoffs_separados(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    await client.post(
        f"/portal/imoveis/{identificador}/interesse", json={"telefone": "11988887777"}
    )
    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse", json={"telefone": "21977776666"}
    )

    assert resposta.status_code == 201

    contagem_handoffs = (await session.execute(text("SELECT count(*) FROM handoffs"))).scalar_one()
    assert contagem_handoffs == 2


async def test_campo_extra_no_corpo_e_422(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session)

    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse",
        json={"telefone": "11988887777", "campo_desconhecido": "x"},
    )

    assert resposta.status_code == 422


async def test_sem_cabecalho_nenhum_e_201_a_rota_e_publica(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await client.post(
        f"/portal/imoveis/{identificador}/interesse",
        json={"telefone": "11988887777"},
        headers={"Authorization": "Bearer nao-e-um-token-valido"},
    )

    assert resposta.status_code == 201

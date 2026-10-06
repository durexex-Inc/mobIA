"""O detalhe e as fotos de um imovel no portal, sem credencial nenhuma.

TEC-388. Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from httpx import AsyncClient

from mobia.domain.catalogo.models import Imovel
from mobia.domain.texto import dobrar
from tests.conftest import cabecalho_de

_JPEG = b"\xff\xd8\xff" + b"\x00" * 64


async def _semear(session: Any, **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": "AP-2042",
        "titulo": "Apartamento com varanda",
        "descricao": "Sala ampla, dois quartos, varanda com vista para o parque.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 58000000,
        "condominio": 65000,
        "iptu_mensal": 12000,
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
        "caracteristicas": ["varanda", "vista para o parque"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_ca01_detalhe_traz_descricao_caracteristicas_e_precos(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await client.get(f"/portal/imoveis/{identificador}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["id"] == str(identificador)
    assert corpo["titulo"] == "Apartamento com varanda"
    assert corpo["descricao"] == "Sala ampla, dois quartos, varanda com vista para o parque."
    assert corpo["tipo"] == "APARTAMENTO"
    assert corpo["operacao"] == "VENDA"
    assert corpo["precoVenda"] == 58000000
    assert corpo["precoAluguel"] is None
    assert corpo["condominio"] == 65000
    assert corpo["iptuMensal"] == 12000
    assert corpo["bairro"] == "Vila Mariana"
    assert corpo["areaUtilM2"] == 74
    assert corpo["quartos"] == 2
    assert corpo["caracteristicas"] == ["varanda", "vista para o parque"]
    assert corpo["fotos"] == []
    # D2: campos administrativos nao vazam.
    assert "codigo" not in corpo
    assert "status" not in corpo
    assert "zona" not in corpo


async def test_ca02_sem_foto_a_lista_vem_vazia(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session, fotos=[])

    resposta = await client.get(f"/portal/imoveis/{identificador}")

    assert resposta.status_code == 200
    assert resposta.json()["fotos"] == []


async def test_ca03_imovel_inexistente_e_404(client: AsyncClient) -> None:
    resposta = await client.get(f"/portal/imoveis/{uuid.uuid4()}")

    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "imovel nao disponivel"


async def test_ca03_status_fora_de_disponivel_e_o_mesmo_404(
    client: AsyncClient, session: Any
) -> None:
    """Nunca 403, e a mesma mensagem de quando o id nao existe (D3)."""
    for status_do_imovel in ("RESERVADO", "VENDIDO", "ALUGADO", "INATIVO"):
        identificador = await _semear(
            session, codigo=f"AP-{status_do_imovel}", status=status_do_imovel
        )

        resposta = await client.get(f"/portal/imoveis/{identificador}")

        assert resposta.status_code == 404
        assert resposta.json()["detail"] == "imovel nao disponivel"


async def test_id_malformado_e_422(client: AsyncClient) -> None:
    resposta = await client.get("/portal/imoveis/nao-e-um-uuid")

    assert resposta.status_code == 422


async def test_sem_cabecalho_nenhum_e_200_a_rota_e_publica(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await client.get(
        f"/portal/imoveis/{identificador}",
        headers={"Authorization": "Bearer nao-e-um-token-valido"},
    )

    assert resposta.status_code == 200


async def test_a_foto_e_servida_e_a_url_do_detalhe_aponta_para_a_rota_publica(
    client: AsyncClient,
) -> None:
    """Ponta a ponta: cadastro + upload (admin) -> detalhe e foto (publico)."""
    criado = await client.post(
        "/api/v1/imoveis",
        json={
            "codigo": "AP-FOTO-388",
            "titulo": "Apartamento com foto",
            "descricao": "Para o teste de ponta a ponta da TEC-388.",
            "tipo": "APARTAMENTO",
            "operacao": "VENDA",
            "status": "DISPONIVEL",
            "precoVenda": 50_000_000,
            "bairro": "Centro",
            "cidade": "Florianopolis",
            "uf": "SC",
            "areaUtilM2": 60,
            "quartos": 2,
            "suites": 1,
            "banheiros": 1,
            "vagas": 1,
            "caracteristicas": [],
            "fotos": [],
        },
        headers=cabecalho_de("ADMIN"),
    )
    assert criado.status_code == 201, criado.text
    imovel_id = criado.json()["id"]

    enviada = await client.post(
        f"/api/v1/imoveis/{imovel_id}/fotos",
        files={"arquivo": ("foto.jpg", _JPEG, "image/jpeg")},
        headers=cabecalho_de("ADMIN"),
    )
    assert enviada.status_code == 201, enviada.text
    (url_administrativa,) = enviada.json()["fotos"]
    foto_id = url_administrativa.rsplit("/", 1)[-1]

    detalhe = await client.get(f"/portal/imoveis/{imovel_id}")
    assert detalhe.status_code == 200
    (url_publica,) = detalhe.json()["fotos"]
    assert url_publica == f"/portal/imoveis/{imovel_id}/fotos/{foto_id}"

    foto = await client.get(url_publica)
    assert foto.status_code == 200
    assert foto.headers["content-type"] == "image/jpeg"
    assert foto.content == _JPEG


async def test_foto_de_imovel_indisponivel_e_404(client: AsyncClient, session: Any) -> None:
    identificador = await _semear(session, status="VENDIDO")

    resposta = await client.get(f"/portal/imoveis/{identificador}/fotos/{uuid.uuid4()}")

    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "imovel nao disponivel"


async def test_foto_inexistente_de_imovel_disponivel_e_404(
    client: AsyncClient, session: Any
) -> None:
    identificador = await _semear(session)

    resposta = await client.get(f"/portal/imoveis/{identificador}/fotos/{uuid.uuid4()}")

    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "foto nao existe"

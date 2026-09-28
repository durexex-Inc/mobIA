"""Criterios de aceite da TEC-335: enviar e reordenar as fotos do imovel.

Os quatro exemplos do Gherkin (JPEG 4MB aceito, WebP 5MB aceito, PNG 6MB
recusado por TAMANHO, GIF 1MB recusado por FORMATO), o teto de 15 fotos (rota
E constraint de banco), a leitura devolvendo o Content-Type certo, a
reordenacao pelo `PATCH` ja existente (D4/D5) e o recorte por papel (D2).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.fotos import FOTO_LIMITE_POR_IMOVEL
from tests.conftest import cabecalho_de

ROTA = "/api/v1/imoveis"

# Assinaturas minimas validas de cada formato, seguidas de recheio para bater
# o tamanho pedido em cada exemplo do Gherkin -- o conteudo depois da
# assinatura e irrelevante para `detectar_formato`.
_JPEG = b"\xff\xd8\xff" + b"\x00" * (4 * 1024 * 1024)
_WEBP = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * (5 * 1024 * 1024 - 12)
_PNG_GRANDE = b"\x89PNG\r\n\x1a\n" + b"\x00" * (6 * 1024 * 1024)
_GIF = b"GIF89a" + b"\x00" * 1024 * 1024


def _corpo(**sobrescritas: object) -> dict[str, object]:
    corpo: dict[str, object] = {
        "codigo": "AP-FOTO-1",
        "titulo": "Apartamento com fotos",
        "descricao": "Para os testes da TEC-335.",
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
    }
    corpo.update(sobrescritas)
    return corpo


async def _criar_imovel(client: AsyncClient, **sobrescritas: object) -> str:
    resposta = await client.post(ROTA, json=_corpo(**sobrescritas), headers=cabecalho_de("ADMIN"))
    assert resposta.status_code == 201, resposta.text
    return str(resposta.json()["id"])


async def _enviar(client: AsyncClient, imovel_id: str, conteudo: bytes, nome: str = "foto.jpg"):
    return await client.post(
        f"{ROTA}/{imovel_id}/fotos",
        files={"arquivo": (nome, conteudo, "image/jpeg")},
        headers=cabecalho_de("ADMIN"),
    )


# --- os quatro exemplos do Gherkin (D3) -----------------------------------------


async def test_jpeg_de_4mb_e_aceito(client: AsyncClient, banco_limpo: None) -> None:
    imovel_id = await _criar_imovel(client)

    resposta = await _enviar(client, imovel_id, _JPEG)

    assert resposta.status_code == 201, resposta.text
    (url,) = resposta.json()["fotos"]
    assert url.startswith(f"{ROTA}/{imovel_id}/fotos/")
    uuid.UUID(url.rsplit("/", 1)[-1])  # o foto_id e um uuid valido


async def test_webp_de_5mb_e_aceito(client: AsyncClient, banco_limpo: None) -> None:
    imovel_id = await _criar_imovel(client)

    resposta = await _enviar(client, imovel_id, _WEBP, nome="foto.webp")

    assert resposta.status_code == 201, resposta.text
    assert len(resposta.json()["fotos"]) == 1


async def test_png_de_6mb_e_recusado_por_tamanho(client: AsyncClient, banco_limpo: None) -> None:
    """Recusado por TAMANHO -- a assinatura de PNG bate, so o teto de 5MB nao."""
    imovel_id = await _criar_imovel(client)

    resposta = await _enviar(client, imovel_id, _PNG_GRANDE, nome="foto.png")

    assert resposta.status_code == 422, resposta.text
    assert "bytes" in resposta.json()["detail"]


async def test_gif_de_1mb_e_recusado_por_formato(client: AsyncClient, banco_limpo: None) -> None:
    """Recusado por FORMATO -- 1MB esta bem abaixo do teto, a assinatura que
    nao bate com JPEG/PNG/WebP."""
    imovel_id = await _criar_imovel(client)

    resposta = await _enviar(client, imovel_id, _GIF, nome="foto.gif")

    assert resposta.status_code == 422, resposta.text
    assert "formato" in resposta.json()["detail"]


async def test_extensao_e_content_type_declarados_nao_importam(
    client: AsyncClient, banco_limpo: None
) -> None:
    """Um GIF renomeado para `.jpg`, com `Content-Type: image/jpeg` declarado
    no upload, continua recusado -- so a assinatura de bytes decide (D3)."""
    imovel_id = await _criar_imovel(client)

    resposta = await client.post(
        f"{ROTA}/{imovel_id}/fotos",
        files={"arquivo": ("disfarcado.jpg", _GIF, "image/jpeg")},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 422, resposta.text


# --- o limite de 15 fotos (rota e CHECK) -----------------------------------------


async def test_decimo_sexto_upload_e_recusado(client: AsyncClient, banco_limpo: None) -> None:
    imovel_id = await _criar_imovel(client)
    for _ in range(FOTO_LIMITE_POR_IMOVEL):
        resposta = await _enviar(client, imovel_id, _JPEG)
        assert resposta.status_code == 201, resposta.text

    resposta = await _enviar(client, imovel_id, _JPEG)

    assert resposta.status_code == 422, resposta.text
    assert "15" in resposta.json()["detail"]


async def test_check_constraint_do_banco_recusa_16_fotos_via_patch(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O `PATCH` generico (TEC-197) tambem escreve `fotos` livremente -- o
    `CHECK` do banco (migration 0069) e o que impede 20 URLs coladas de uma vez."""
    imovel_id = await _criar_imovel(client)
    dezesseis_urls = [f"https://exemplo.com/foto-{i}.jpg" for i in range(16)]

    with pytest.raises(DBAPIError, match="ck_imoveis_fotos_teto"):
        await session.execute(
            text("UPDATE imoveis SET fotos = :fotos WHERE id = :id"),
            {"fotos": dezesseis_urls, "id": uuid.UUID(imovel_id)},
        )
        await session.commit()
    await session.rollback()


# --- a leitura (D2) ---------------------------------------------------------------


async def test_leitura_devolve_os_bytes_e_o_content_type_certo(
    client: AsyncClient, banco_limpo: None
) -> None:
    imovel_id = await _criar_imovel(client)
    enviada = await _enviar(client, imovel_id, _WEBP, nome="foto.webp")
    (url,) = enviada.json()["fotos"]

    resposta = await client.get(url, headers=cabecalho_de("ADMIN"))

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/webp"
    assert resposta.content == _WEBP


async def test_foto_inexistente_e_404(client: AsyncClient, banco_limpo: None) -> None:
    imovel_id = await _criar_imovel(client)

    resposta = await client.get(
        f"{ROTA}/{imovel_id}/fotos/{uuid.uuid4()}", headers=cabecalho_de("ADMIN")
    )

    assert resposta.status_code == 404


# --- reordenacao pelo PATCH ja existente, sem rota nova (D4/D5) -----------------


async def test_reordenar_e_so_o_patch_existente_com_nova_ordem(
    client: AsyncClient, banco_limpo: None
) -> None:
    imovel_id = await _criar_imovel(client)
    primeira = (await _enviar(client, imovel_id, _JPEG)).json()["fotos"][0]
    segunda = (await _enviar(client, imovel_id, _WEBP, nome="b.webp")).json()["fotos"][1]

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}", json={"fotos": [segunda, primeira]}, headers=cabecalho_de("ADMIN")
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["fotos"] == [segunda, primeira]


async def test_remover_e_o_mesmo_patch_com_lista_mais_curta(
    client: AsyncClient, banco_limpo: None
) -> None:
    imovel_id = await _criar_imovel(client)
    primeira = (await _enviar(client, imovel_id, _JPEG)).json()["fotos"][0]
    await _enviar(client, imovel_id, _WEBP, nome="b.webp")

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}", json={"fotos": [primeira]}, headers=cabecalho_de("ADMIN")
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["fotos"] == [primeira]


# --- o recorte por papel (D2) ----------------------------------------------------


@pytest.mark.parametrize("papel", ["GERENTE", "CORRETOR", "LEITURA"])
async def test_so_admin_envia_e_le_fotos(
    client: AsyncClient, banco_limpo: None, papel: str
) -> None:
    imovel_id = await _criar_imovel(client)

    envio = await client.post(
        f"{ROTA}/{imovel_id}/fotos",
        files={"arquivo": ("foto.jpg", _JPEG, "image/jpeg")},
        headers=cabecalho_de(papel),
    )
    leitura = await client.get(
        f"{ROTA}/{imovel_id}/fotos/{uuid.uuid4()}", headers=cabecalho_de(papel)
    )

    assert (envio.status_code, leitura.status_code) == (403, 403)

"""Criterios de aceite da TEC-197 como testes executaveis. RF-19, RN-19.1, RN-08.3.

Os quatro cenarios do Gherkin da card, e o que o desenho acrescentou: a
validacao unica com a importacao (D2), o `PATCH` validado sobre o registro
inteiro, o codigo imutavel, o `reindexa` (D3), a paginacao (D5) e o recorte
por papel.

**Os dois primeiros cenarios rodam a varredura de verdade**, com o embedador
falso de `conftest.py`. Nao ha codigo de reindexacao nesta card (D2 da
TEC-157: a pendencia e derivada do estado), entao o que se prova e que a
escrita pela tela deixa o estado que a varredura sabe ler -- e a unica forma
de afirmar "nenhum embedding novo" e contar as chamadas ao provedor.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from conftest import EmbedadorFake
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agente.models import Recomendacao
from mobia.domain.catalogo.enums import OrigemImportacao
from mobia.domain.catalogo.importacao import executar, registrar
from mobia.domain.catalogo.models import Imovel
from mobia.domain.usuarios import tokens
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo

ROTA = "/api/v1/imoveis"


def _bearer(papel: str = "ADMIN") -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


def _corpo(**sobrescritas: object) -> dict[str, object]:
    corpo: dict[str, object] = {
        "codigo": "AP-620",
        "titulo": "Apartamento no Campeche",
        "descricao": "Dois quartos, perto da praia.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "status": "DISPONIVEL",
        "precoVenda": 62_000_000,
        "bairro": "Campeche",
        "cidade": "Florianopolis",
        "uf": "SC",
        "areaUtilM2": 70,
        "quartos": 2,
        "suites": 1,
        "banheiros": 2,
        "vagas": 1,
        "caracteristicas": ["varanda"],
        "fotos": [],
    }
    corpo.update(sobrescritas)
    return corpo


async def _criar(client: AsyncClient, **sobrescritas: object) -> str:
    resposta = await client.post(ROTA, json=_corpo(**sobrescritas), headers=_bearer())
    assert resposta.status_code == 201, resposta.text
    return str(resposta.json()["id"])


async def _na_busca(client: AsyncClient, preco_max: int) -> dict[str, int]:
    """Codigo -> preco de venda, como a busca do agente os devolve."""
    resposta = await client.post(
        f"{ROTA}/busca",
        json={"filtros": {"operacao": "VENDA", "precoMax": preco_max}, "limite": 10},
        headers=_bearer(),
    )
    assert resposta.status_code == 200, resposta.text
    return {item["codigo"]: item["preco"] for item in resposta.json()["itens"]}


def _ctx(embedador: EmbedadorFake) -> dict[str, Any]:
    return {"session_factory": get_sessionmaker(), "embedador": embedador}


# --- os quatro cenarios do Gherkin ---------------------------------------------


async def test_corrigir_preco_vale_na_busca_e_nao_gera_embedding(
    client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1, com os numeros da card: de R$ 620.000 para R$ 590.000."""
    imovel_id = await _criar(client)
    await indexar_catalogo(_ctx(EmbedadorFake()))
    assert (await _na_busca(client, 60_000_000))["AP-620"] == 62_000_000

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}", json={"precoVenda": 59_000_000}, headers=_bearer()
    )
    depois = EmbedadorFake()
    await indexar_catalogo(_ctx(depois))

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["reindexa"] is False
    # O preco que a busca devolve, e nao "aparece abaixo do teto": a busca tem
    # folga de preco, e os dois valores da card caem dentro dela.
    assert (await _na_busca(client, 60_000_000))["AP-620"] == 59_000_000
    assert depois.chamadas == []


async def test_alterar_descricao_regera_o_indice(client: AsyncClient, banco_limpo: None) -> None:
    """Cenario 2. A varredura chama o provedor com o documento novo."""
    imovel_id = await _criar(client)
    await indexar_catalogo(_ctx(EmbedadorFake()))

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}",
        json={"descricao": "Tres quartos, vista para o mar."},
        headers=_bearer(),
    )
    depois = EmbedadorFake()
    await indexar_catalogo(_ctx(depois))

    assert resposta.json()["reindexa"] is True
    ((documento,),) = depois.chamadas
    assert "vista para o mar" in documento


async def test_exclusao_e_logica(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 3: sai da busca, fica no banco, e a recomendacao antiga
    continua apontando para ele."""
    imovel_id = await _criar(client)
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5548990000021",
            imovel_id=uuid.UUID(imovel_id),
            score_match=Decimal("0.900"),
            motivo_match="bate",
            apresentado_em=datetime.now(UTC),
        )
    )
    await session.commit()

    resposta = await client.delete(f"{ROTA}/{imovel_id}", headers=_bearer())

    assert resposta.status_code == 204
    assert "AP-620" not in await _na_busca(client, 90_000_000)
    imovel = (
        await session.execute(
            select(Imovel)
            .where(Imovel.id == uuid.UUID(imovel_id))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert imovel.status == "INATIVO"
    (recomendacao,) = (await session.execute(select(Recomendacao))).scalars().all()
    assert recomendacao.imovel_id == imovel.id


async def test_upload_em_lote_mostra_as_linhas_rejeitadas(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 4: 3 linhas invalidas, e a tela le a ultima importacao."""
    cabecalho = (
        "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
        "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
        "suites,banheiros,vagas,caracteristicas,fotos,status"
    )
    boa = (
        "AP-1,Apartamento,Vista,APARTAMENTO,VENDA,580000.00,,,,Centro,Florianopolis,SC,"
        ",,,74,2,1,2,1,,,DISPONIVEL"
    )
    sem_titulo = boa.replace("AP-1,Apartamento", "AP-2,")
    tipo_ruim = boa.replace("AP-1", "AP-3").replace("APARTAMENTO", "CASTELO")
    sem_preco = boa.replace("AP-1", "AP-4").replace("580000.00", "")
    conteudo = "\n".join([cabecalho, boa, sem_titulo, tipo_ruim, sem_preco]) + "\n"
    importacao_id = await registrar(
        session, origem=OrigemImportacao.HTTP, nome_arquivo="lote.csv", conteudo=conteudo.encode()
    )
    await session.commit()
    await executar(get_sessionmaker(), importacao_id=importacao_id)

    resposta = await client.get(f"{ROTA}/importacoes", headers=_bearer())

    (ultima,) = resposta.json()["itens"]
    assert ultima["importacaoId"] == str(importacao_id)
    assert ultima["rejeitados"] == 3
    motivos = " | ".join(e["motivo"] for e in ultima["erros"])
    assert "titulo ausente" in motivos
    assert "tipo invalido" in motivos
    assert "preco_venda" in motivos


# --- a validacao e a da importacao (D2) ----------------------------------------


async def test_a_recusa_da_tela_e_a_mesma_do_arquivo(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.post(ROTA, json=_corpo(tipo="CASTELO", titulo=None), headers=_bearer())

    assert resposta.status_code == 422
    detalhe = resposta.json()["detail"]
    assert "titulo ausente" in detalhe
    assert "tipo invalido: 'CASTELO'" in detalhe


async def test_patch_valida_o_registro_inteiro(client: AsyncClient, banco_limpo: None) -> None:
    """Limpar o unico preco: `null` e um valor valido sozinho, e o registro
    resultante fere a regra de "ao menos um preco" da importacao."""
    imovel_id = await _criar(client)

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}", json={"precoVenda": None}, headers=_bearer()
    )

    assert resposta.status_code == 422, resposta.text


async def test_codigo_duplicado_e_409(client: AsyncClient, banco_limpo: None) -> None:
    await _criar(client)

    resposta = await client.post(ROTA, json=_corpo(), headers=_bearer())

    assert resposta.status_code == 409


async def test_codigo_nao_se_edita(client: AsyncClient, banco_limpo: None) -> None:
    imovel_id = await _criar(client)

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}", json={"codigo": "AP-999"}, headers=_bearer()
    )

    assert resposta.status_code == 422


async def test_status_nao_reindexa(client: AsyncClient, banco_limpo: None) -> None:
    imovel_id = await _criar(client)

    resposta = await client.patch(
        f"{ROTA}/{imovel_id}", json={"status": "RESERVADO"}, headers=_bearer()
    )

    assert (resposta.status_code, resposta.json()["reindexa"]) == (200, False)


async def test_caracteristica_com_separador_e_recusada(
    client: AsyncClient, banco_limpo: None
) -> None:
    """O `|` e o separador do arquivo; na tela ele viraria duas caracteristicas."""
    resposta = await client.post(
        ROTA, json=_corpo(caracteristicas=["piscina|churrasqueira"]), headers=_bearer()
    )

    assert resposta.status_code == 422


async def test_imovel_inexistente_e_404(client: AsyncClient, banco_limpo: None) -> None:
    alvo = f"{ROTA}/{uuid.uuid4()}"
    assert (await client.get(alvo, headers=_bearer())).status_code == 404
    assert (await client.patch(alvo, json={"quartos": 3}, headers=_bearer())).status_code == 404
    assert (await client.delete(alvo, headers=_bearer())).status_code == 404


# --- a listagem (D5) -----------------------------------------------------------


async def test_listagem_pagina_sem_repetir_nem_perder(
    client: AsyncClient, banco_limpo: None
) -> None:
    for numero in range(7):
        await _criar(client, codigo=f"AP-{numero:03d}")

    vistos: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limite": 3}
        if cursor:
            params["cursor"] = cursor
        corpo = (await client.get(ROTA, params=params, headers=_bearer())).json()
        vistos.extend(item["codigo"] for item in corpo["itens"])
        cursor = corpo["proximoCursor"]
        if cursor is None:
            break

    assert vistos == [f"AP-{numero:03d}" for numero in range(7)]


async def test_listagem_filtra_por_bairro_sem_acento(
    client: AsyncClient, banco_limpo: None
) -> None:
    await _criar(client, codigo="AP-1", bairro="João Paulo")
    await _criar(client, codigo="AP-2", bairro="Centro")

    corpo = (await client.get(ROTA, params={"bairro": "joao"}, headers=_bearer())).json()

    assert [item["codigo"] for item in corpo["itens"]] == ["AP-1"]


# --- o recorte (D1) ------------------------------------------------------------


@pytest.mark.parametrize("papel", ["GERENTE", "CORRETOR", "LEITURA"])
async def test_so_admin_gerencia_imoveis(
    client: AsyncClient, banco_limpo: None, papel: str
) -> None:
    respostas = [
        await client.get(ROTA, headers=_bearer(papel)),
        await client.post(ROTA, json=_corpo(), headers=_bearer(papel)),
        await client.get(f"{ROTA}/importacoes", headers=_bearer(papel)),
    ]

    assert [r.status_code for r in respostas] == [403, 403, 403]

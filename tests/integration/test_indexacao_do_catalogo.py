"""A varredura da indexacao vetorial.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from conftest import EmbedadorFake
from sqlalchemy import select, text

from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo


async def _imovel(session: Any, codigo: str = "AP-001", **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


def _ctx(embedador: EmbedadorFake) -> dict[str, Any]:
    return {"session_factory": get_sessionmaker(), "embedador": embedador}


async def test_imovel_novo_e_indexado(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()

    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 1
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None
    assert imovel.documento_hash is not None
    assert imovel.embedding_atualizado_em is not None


async def test_a_segunda_passagem_nao_reindexa_nada(session: Any) -> None:
    await _imovel(session)
    embedador = EmbedadorFake()

    await indexar_catalogo(_ctx(embedador))
    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 0
    # Uma chamada na primeira passagem, nenhuma na segunda.
    assert len(embedador.chamadas) == 1


async def test_o_teto_por_passagem_limita(session: Any) -> None:
    for numero in range(5):
        await _imovel(session, codigo=f"AP-{numero:03d}")
    embedador = EmbedadorFake()

    indexados = await indexar_catalogo(_ctx(embedador), limite=3)

    assert indexados == 3


async def test_mudanca_de_preco_nao_faz_chamada_nenhuma(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    await indexar_catalogo(_ctx(embedador))
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text(
                "UPDATE imoveis SET preco_venda = 69900000, updated_at = clock_timestamp() "
                " WHERE id = :id"
            ),
            {"id": identificador},
        )
        await escrita.commit()

    indexados = await indexar_catalogo(_ctx(embedador))

    # A assercao e sobre CHAMADAS, e nao sobre o vetor: um vetor igual nao
    # provaria nada, porque uma implementacao errada tambem o devolveria.
    assert indexados == 0
    assert len(embedador.chamadas) == 1


async def test_mudanca_de_descricao_gera_vetor_e_hash_novos(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    await indexar_catalogo(_ctx(embedador))

    async with get_sessionmaker()() as leitura:
        antes = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert antes is not None
    hash_antigo = antes.documento_hash

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text(
                "UPDATE imoveis SET descricao = 'Reformado em 2026.', "
                "       updated_at = clock_timestamp() "
                " WHERE id = :id"
            ),
            {"id": identificador},
        )
        await escrita.commit()

    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 1
    assert len(embedador.chamadas) == 2

    async with get_sessionmaker()() as leitura:
        depois = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert depois is not None
    assert depois.documento_hash != hash_antigo

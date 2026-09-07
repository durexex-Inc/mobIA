"""A varredura da indexacao vetorial.

Basename distinto de tudo em `tests/unit/`.
"""

import asyncio
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


async def test_imovel_vendido_tambem_e_indexado(session: Any) -> None:
    # D9: a RN-08.4 tira o nao disponivel dos RESULTADOS da busca, mas o
    # corte por status e da busca, nao da indexacao. Filtrar aqui criaria o
    # caso em que reativar um imovel o deixa sem vetor.
    identificador = await _imovel(session, status="VENDIDO")
    embedador = EmbedadorFake()

    assert await indexar_catalogo(_ctx(embedador)) == 1

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None


async def test_falha_do_provedor_deixa_a_linha_pendente(session: Any) -> None:
    identificador = await _imovel(session)

    # NAO levanta, e isso e deliberado. Relevantar faria um documento que o
    # provedor rejeita de forma permanente abortar a passagem inteira -- e com
    # `ORDER BY updated_at` ele cai no lote 1 de TODA passagem, entao nada mais
    # no catalogo seria indexado nunca, com um warning por tick como unico
    # sintoma. O job loga e segue, no molde do `sweep_stalled`.
    assert await indexar_catalogo(_ctx(EmbedadorFake(falhar=True))) == 0

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    # A linha so e gravada em caso de sucesso: falha deixa o candidato como
    # estava, e a retomada nao depende do retry do ARQ -- o cron roda de novo.
    assert imovel.embedding is None
    assert imovel.documento_hash is None

    embedador = EmbedadorFake()
    assert await indexar_catalogo(_ctx(embedador)) == 1


async def test_varreduras_concorrentes_deixam_a_linha_indexada_uma_vez(
    session: Any,
) -> None:
    identificador = await _imovel(session)
    primeiro = EmbedadorFake()
    segundo = EmbedadorFake()

    await asyncio.gather(
        indexar_catalogo(_ctx(primeiro)),
        indexar_catalogo(_ctx(segundo)),
    )

    # A assercao e sobre o DESFECHO, e nao sobre o numero de chamadas.
    #
    # `FOR UPDATE SKIP LOCKED` impede duas varreduras de selecionar a mesma
    # linha no mesmo instante, mas o lock e solto antes do I/O de rede -- de
    # proposito, herdado da `sweep_stalled`: segurar lock de linha atravessando
    # chamada a provedor externo e pior. Entao uma varredura que comece depois
    # do rollback da outra pode gastar uma chamada em duplicidade. Isso e
    # desperdicio idempotente, nao incorrecao: mesmo texto gera mesmo vetor, e
    # a ultima escrita tem o mesmo conteudo da primeira.
    #
    # Afirmar `len(chamadas) == 1` aqui seria afirmar mais do que o desenho
    # garante, e o teste flakearia sob carga por um motivo que nao e defeito.
    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None
    assert imovel.documento_hash is not None
    assert imovel.embedding_atualizado_em is not None

    # E a linha nao fica candidata depois: a proxima passagem nao chama nada.
    terceiro = EmbedadorFake()
    assert await indexar_catalogo(_ctx(terceiro)) == 0
    assert terceiro.chamadas == []

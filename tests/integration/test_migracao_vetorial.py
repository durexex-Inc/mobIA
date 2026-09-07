"""A `0017` criou a extensao, as tres colunas e o indice.

Basename distinto de qualquer arquivo em `tests/unit/`: basename repetido
entre unit e integration aborta a coleta da suite inteira.
"""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker


async def test_a_extensao_vector_existe() -> None:
    async with get_sessionmaker()() as session:
        presente = await session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    assert presente == 1


async def test_as_tres_colunas_existem_e_sao_nulaveis() -> None:
    esperadas = {
        "embedding": "USER-DEFINED",
        "embedding_atualizado_em": "timestamp with time zone",
        "documento_hash": "text",
    }
    async with get_sessionmaker()() as session:
        resultado = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "  FROM information_schema.columns "
                " WHERE table_name = 'imoveis' "
                "   AND column_name = ANY(:nomes)"
            ),
            {"nomes": list(esperadas)},
        )
        colunas = {linha.column_name: linha for linha in resultado}

    assert set(colunas) == set(esperadas)
    for nome, tipo in esperadas.items():
        assert colunas[nome].data_type == tipo
        # Nulaveis e o que faz os 520 imoveis ja importados entrarem como
        # pendentes sem backfill nenhum.
        assert colunas[nome].is_nullable == "YES"


async def test_o_indice_ivfflat_existe_com_cosseno() -> None:
    async with get_sessionmaker()() as session:
        definicao = await session.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_imoveis_embedding'")
        )
    assert definicao is not None
    assert "ivfflat" in definicao
    assert "vector_cosine_ops" in definicao

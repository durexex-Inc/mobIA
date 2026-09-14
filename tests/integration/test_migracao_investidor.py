"""A `0033` acrescenta os campos da RN-05.2 e da RN-07.2. TEC-153."""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker

ESPERADAS = {
    "ticket_investimento_centavos": "bigint",
    "retorno_esperado_pct": "numeric",
    # `String(16)` do SQLAlchemy vira `character varying` no Postgres, nao
    # `text`: o limite de 16 caracteres e o que restringe a grafia do enum.
    "retorno_esperado_tipo": "character varying",
    "horizonte": "character varying",
    "tolerancia_reforma": "character varying",
    "ja_investe_em_imoveis": "boolean",
    "perfil_investidor": "character varying",
}


async def test_as_colunas_do_investidor_existem_e_sao_nulaveis() -> None:
    """Nulaveis pela mesma razao das vizinhas: qualificacao e progressiva, e
    campo ausente e o estado normal, nao um defeito."""
    async with get_sessionmaker()() as session:
        resultado = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "  FROM information_schema.columns "
                " WHERE table_name = 'lead_qualification' "
                "   AND column_name = ANY(:nomes)"
            ),
            {"nomes": list(ESPERADAS)},
        )
        colunas = {linha.column_name: linha for linha in resultado}

    assert set(colunas) == set(ESPERADAS)
    for nome, tipo in ESPERADAS.items():
        assert colunas[nome].data_type.startswith(tipo), f"{nome}: {colunas[nome].data_type}"
        assert colunas[nome].is_nullable == "YES"

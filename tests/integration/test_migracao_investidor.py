"""A `0033` acrescenta os campos da RN-05.2 e da RN-07.2. TEC-153."""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker

# Tipo e, quando ha, o limite de caracteres. `String(16)` do SQLAlchemy vira
# `character varying(16)` no Postgres, nao `text`: o limite de 16 e o que
# restringe a grafia do enum, e sem asseri-lo este teste passaria igual sobre
# um `varchar(255)` ou um `text` -- o comentario dizia que o limite era o
# ponto e so o tipo era conferido.
ESPERADAS = {
    "ticket_investimento_centavos": ("bigint", None),
    "retorno_esperado_pct": ("numeric", None),
    "retorno_esperado_tipo": ("character varying", 16),
    "horizonte": ("character varying", 16),
    "tolerancia_reforma": ("character varying", 16),
    "ja_investe_em_imoveis": ("boolean", None),
    "perfil_investidor": ("character varying", 16),
}


async def test_as_colunas_do_investidor_existem_e_sao_nulaveis() -> None:
    """Nulaveis pela mesma razao das vizinhas: qualificacao e progressiva, e
    campo ausente e o estado normal, nao um defeito."""
    async with get_sessionmaker()() as session:
        resultado = await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable, character_maximum_length "
                "  FROM information_schema.columns "
                " WHERE table_name = 'lead_qualification' "
                "   AND column_name = ANY(:nomes)"
            ),
            {"nomes": list(ESPERADAS)},
        )
        colunas = {linha.column_name: linha for linha in resultado}

    assert set(colunas) == set(ESPERADAS)
    for nome, (tipo, tamanho) in ESPERADAS.items():
        assert colunas[nome].data_type.startswith(tipo), f"{nome}: {colunas[nome].data_type}"
        assert colunas[nome].is_nullable == "YES"
        assert colunas[nome].character_maximum_length == tamanho, (
            f"{nome}: {colunas[nome].character_maximum_length}"
        )

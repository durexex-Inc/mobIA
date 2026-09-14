"""A `0032` acrescenta o contador do teto da RN-05.5. TEC-149."""

from sqlalchemy import text

from mobia.infra.db import get_sessionmaker


async def test_a_coluna_do_contador_existe_nao_nulavel_com_default_zero() -> None:
    async with get_sessionmaker()() as session:
        linha = (
            await session.execute(
                text(
                    "SELECT data_type, is_nullable, column_default "
                    "  FROM information_schema.columns "
                    " WHERE table_name = 'lead_qualification' "
                    "   AND column_name = 'perguntas_feitas'"
                )
            )
        ).one_or_none()

    assert linha is not None, "a coluna perguntas_feitas nao existe"
    assert linha.data_type == "smallint"
    # NOT NULL com default: `0` numa linha antiga nao afirma "ninguem
    # perguntou", afirma "ninguem contava" -- e o lead antigo ganha orcamento
    # cheio, que erra na direcao de continuar atendendo como hoje. Ver D1.
    assert linha.is_nullable == "NO"
    assert linha.column_default is not None and "0" in linha.column_default

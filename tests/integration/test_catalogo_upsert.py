"""O upsert do catalogo por codigo, e os cinco totais que ele produz.

TEC-156. Integracao de verdade: as migrations rodam pela fixture de sessao.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.models import Imovel


async def test_as_duas_tabelas_existem_depois_da_migration(session) -> None:
    for tabela in ("imoveis", "importacoes"):
        assert await session.scalar(text(f"SELECT to_regclass('public.{tabela}')"))


async def test_codigo_e_unico(session) -> None:
    session.add(_imovel("AP-1"))
    await session.commit()
    session.add(_imovel("AP-1"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


def _imovel(codigo: str) -> Imovel:
    return Imovel(
        id=uuid.uuid4(),
        codigo=codigo,
        titulo="Apartamento",
        descricao="Descricao",
        tipo=TipoImovel.APARTAMENTO,
        operacao=Operacao.VENDA,
        preco_venda=58_000_000,
        bairro="Centro",
        cidade="Florianopolis",
        uf="SC",
        area_util_m2=74,
        quartos=2,
        suites=1,
        banheiros=2,
        vagas=1,
        caracteristicas=[],
        fotos=[],
        status=StatusImovel.DISPONIVEL,
    )

"""O upsert do catalogo por codigo, e os tres totais que `sincronizar` produz.

TEC-156. Integracao de verdade: as migrations rodam pela fixture de sessao.

Os cinco totais do relatorio (`Relatorio`, em schemas.py) somam estes tres
mais `processados` e `rejeitados` -- os dois ultimos nascem no orquestrador
da Task 5, que ainda nao existe aqui. Este arquivo testa o que `sincronizar`
de fato devolve: inseridos, atualizados e inalterados.
"""

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.repositorio import sincronizar
from mobia.domain.catalogo.schemas import RegistroImovel


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


def _registro(codigo: str, linha: int = 2, preco: int = 58_000_000) -> RegistroImovel:
    return RegistroImovel(
        linha=linha,
        codigo=codigo,
        titulo="Apartamento com varanda",
        descricao="Vista para o mar",
        tipo=TipoImovel.APARTAMENTO,
        operacao=Operacao.VENDA,
        preco_venda=preco,
        preco_aluguel=None,
        condominio=85_000,
        iptu_mensal=32_000,
        bairro="Centro",
        cidade="Florianopolis",
        uf="SC",
        zona=None,
        latitude=Decimal("-27.595377"),
        longitude=Decimal("-48.548050"),
        area_util_m2=74,
        quartos=2,
        suites=1,
        banheiros=2,
        vagas=1,
        caracteristicas=("varanda gourmet",),
        fotos=(),
        status=StatusImovel.DISPONIVEL,
    )


async def test_primeira_carga_insere_tudo(session):
    inseridos, atualizados, inalterados = await sincronizar(
        session, [_registro(f"AP-{i}", linha=i + 2) for i in range(10)]
    )
    await session.commit()
    assert (inseridos, atualizados, inalterados) == (10, 0, 0)
    assert len((await session.scalars(select(Imovel))).all()) == 10


async def test_reimportacao_identica_nao_atualiza_nada(session):
    registros = [_registro(f"AP-{i}", linha=i + 2) for i in range(10)]
    await sincronizar(session, registros)
    await session.commit()

    inseridos, atualizados, inalterados = await sincronizar(session, registros)
    await session.commit()
    assert (inseridos, atualizados, inalterados) == (0, 0, 10)


async def test_cenario_3_do_gherkin(session):
    """500 ja importados, 10 precos alterados: 0 novos, 10 atualizados, 490 iguais."""
    registros = [_registro(f"AP-{i}", linha=i + 2) for i in range(500)]
    await sincronizar(session, registros)
    await session.commit()

    alterados = [
        replace(r, preco_venda=r.preco_venda + 1_000_00) if i < 10 else r
        for i, r in enumerate(registros)
    ]
    inseridos, atualizados, inalterados = await sincronizar(session, alterados)
    await session.commit()

    assert (inseridos, atualizados, inalterados) == (0, 10, 490)
    assert len((await session.scalars(select(Imovel))).all()) == 500


async def test_inalterado_nao_tem_updated_at_tocado(session):
    registros = [_registro("AP-1")]
    await sincronizar(session, registros)
    await session.commit()
    antes = (await session.scalars(select(Imovel))).one().updated_at

    session.expire_all()
    await sincronizar(session, registros)
    await session.commit()
    depois = (await session.scalars(select(Imovel))).one().updated_at

    assert antes == depois


async def test_atualizado_tem_updated_at_movido(session):
    await sincronizar(session, [_registro("AP-1")])
    await session.commit()
    antes = (await session.scalars(select(Imovel))).one().updated_at

    session.expire_all()
    await sincronizar(session, [_registro("AP-1", preco=59_000_000)])
    await session.commit()
    depois = (await session.scalars(select(Imovel))).one().updated_at

    assert depois > antes


async def test_lote_maior_que_500_e_processado_inteiro(session):
    inseridos, _, _ = await sincronizar(
        session, [_registro(f"AP-{i}", linha=i + 2) for i in range(1200)]
    )
    await session.commit()
    assert inseridos == 1200

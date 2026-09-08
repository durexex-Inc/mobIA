"""O upsert do catalogo por codigo, e os cinco totais que fecham o relatorio.

TEC-156. Integracao de verdade: as migrations rodam pela fixture de sessao.

Os cinco totais do relatorio (`Relatorio`, em schemas.py) somam tres que
`sincronizar` devolve -- inseridos, atualizados, inalterados -- mais
`processados` e `rejeitados`, que nascem no orquestrador (`importacao.py`,
Task 5). Os testes daqui embaixo cobrem so os tres primeiros, direto contra
`sincronizar`; os cenarios que exercitam os cinco juntos, com o relatorio
gravado na tabela `importacoes`, vem depois, contra `registrar`/`executar`.
"""

import asyncio
import uuid
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from mobia.domain.catalogo.enums import (
    Operacao,
    OrigemImportacao,
    StatusImovel,
    StatusImportacao,
    TipoImovel,
)
from mobia.domain.catalogo.importacao import executar, registrar
from mobia.domain.catalogo.models import Imovel, Importacao
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
        # Este helper constroi o ORM direto, sem passar por `sincronizar` --
        # entao ninguem deriva a coluna para ele. NOT NULL desde a `0019`.
        bairro_busca="centro",
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


_CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)


def _linha(codigo: str, preco: str = "580000.00") -> str:
    return (
        f"{codigo},Apartamento,Vista para o mar,APARTAMENTO,VENDA,{preco},,850.00,"
        "320.00,Centro,Florianopolis,SC,CENTRO,-27.595377,-48.548050,74,2,1,2,1,"
        "varanda,,DISPONIVEL"
    )


def _arquivo(linhas: list[str]) -> bytes:
    return ("\n".join([_CABECALHO, *linhas]) + "\n").encode("utf-8")


async def test_cenario_1_do_gherkin(session, session_factory):
    """500 linhas, 3 invalidas: 497 gravados, 3 rejeicoes com linha e motivo."""
    linhas = [_linha(f"AP-{i}") for i in range(497)]
    linhas.insert(10, _linha("AP-X", preco=""))
    linhas.insert(200, _linha("AP-Y").replace("APARTAMENTO", "apto"))
    linhas.insert(400, _linha("AP-Z").replace(",74,", ",setenta,"))

    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=_arquivo(linhas),
    )
    await session.commit()

    relatorio = await executar(session_factory, importacao_id=importacao_id)

    assert relatorio.processados == 500
    assert relatorio.inseridos == 497
    assert relatorio.rejeitados == 3
    assert relatorio.fecha()
    assert {e.linha for e in relatorio.erros} == {12, 202, 402}
    assert all(e.motivo for e in relatorio.erros)


async def test_o_relatorio_fica_gravado_e_consultavel(session, session_factory):
    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.HTTP,
        nome_arquivo="base.csv",
        conteudo=_arquivo([_linha("AP-1")]),
    )
    await session.commit()
    await executar(session_factory, importacao_id=importacao_id)

    session.expire_all()
    gravada = await session.get(Importacao, importacao_id)
    assert gravada is not None
    assert gravada.status == StatusImportacao.CONCLUIDO
    assert gravada.inseridos == 1
    assert gravada.concluida_em is not None


async def test_arquivo_sem_cabecalho_valido_e_falhou_e_nao_rejeicao(session, session_factory):
    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=b"nada,disso,serve\n1,2,3\n",
    )
    await session.commit()
    await executar(session_factory, importacao_id=importacao_id)

    session.expire_all()
    gravada = await session.get(Importacao, importacao_id)
    assert gravada is not None
    assert gravada.status == StatusImportacao.FALHOU
    assert gravada.processados == 0
    # A falha do arquivo inteiro vai para `erros` com linha 0: nao e "uma
    # linha", mas quem le o relatorio precisa do motivo em algum lugar.
    assert gravada.erros and gravada.erros[0]["linha"] == 0


async def test_uf_longa_rejeita_a_linha_e_nao_derruba_o_lote(session, session_factory):
    """Celula que a coluna nao aceita custa uma linha, nunca o arquivo.

    Antes da checagem de tamanho no parser esta linha atravessava, o INSERT do
    lote levantava StringDataRightTruncation, e o relatorio saia FALHOU com
    zero gravados e um motivo sem linha e sem nome de campo -- as tres linhas
    (ou as 520 de uma base real) perdidas por um typo numa celula. A RN-08.5
    diz o oposto: linha ruim nunca leva a FALHOU.
    """
    linhas = [
        _linha("AP-1"),
        _linha("AP-2").replace(",SC,CENTRO,", ",Sao Paulo,CENTRO,"),
        _linha("AP-3"),
    ]
    importacao_id = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=_arquivo(linhas),
    )
    await session.commit()

    relatorio = await executar(session_factory, importacao_id=importacao_id)

    assert relatorio.status is StatusImportacao.CONCLUIDO
    assert (relatorio.processados, relatorio.inseridos, relatorio.rejeitados) == (3, 2, 1)
    assert relatorio.fecha()
    assert [e.linha for e in relatorio.erros] == [3]
    assert "uf" in relatorio.erros[0].motivo

    session.expire_all()
    gravada = await session.get(Importacao, importacao_id)
    assert gravada is not None
    assert gravada.status == StatusImportacao.CONCLUIDO
    assert gravada.inseridos == 2
    assert len((await session.scalars(select(Imovel))).all()) == 2


async def test_reimportacao_grava_atualizados_e_inalterados_na_linha(session, session_factory):
    """O cenario 3 pela superficie do produto, e nao contra `sincronizar`.

    O outro teste do cenario 3 chama `sincronizar` direto e le a tupla de
    retorno. Nada afirmava que `atualizados` e `inalterados` atravessam
    `executar` e chegam a linha `importacoes` -- que e o que o GET do relatorio
    devolve, e o unico lugar onde o admin le esses dois numeros. Se `executar`
    parasse de acumular os dois, a suite inteira continuaria verde.
    """
    linhas = [_linha(f"AP-{i}") for i in range(10)]
    primeira = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=_arquivo(linhas),
    )
    await session.commit()
    await executar(session_factory, importacao_id=primeira)

    alteradas = [
        _linha(f"AP-{i}", preco="590000.00") if i < 3 else _linha(f"AP-{i}") for i in range(10)
    ]
    segunda = await registrar(
        session,
        origem=OrigemImportacao.CLI,
        nome_arquivo="base.csv",
        conteudo=_arquivo(alteradas),
    )
    await session.commit()
    relatorio = await executar(session_factory, importacao_id=segunda)

    assert (relatorio.inseridos, relatorio.atualizados, relatorio.inalterados) == (0, 3, 7)

    session.expire_all()
    gravada = await session.get(Importacao, segunda)
    assert gravada is not None
    assert gravada.status == StatusImportacao.CONCLUIDO
    assert (gravada.inseridos, gravada.atualizados, gravada.inalterados) == (0, 3, 7)
    assert gravada.processados == 10
    assert gravada.rejeitados == 0


async def test_corrida_de_lotes_nao_deixa_updated_at_para_tras(session_factory):
    """A linha perdedora da corrida ganha conteudo E carimbo novos.

    Reproduz a corrida que a docstring de `repositorio` descreve: dois lotes
    com o mesmo codigo, o segundo fazendo seu SELECT antes de o primeiro
    comitar. O INSERT do segundo cai no ON CONFLICT DO UPDATE.

    Sem `updated_at` no SET, a linha ficava com o conteudo do segundo lote e o
    carimbo do primeiro -- dados que mudaram e um `updated_at` jurando que
    nao. A rotulagem imprecisa (contada como inserida) e custo aceito de D4;
    o carimbo mentindo para menos nao era.
    """
    primeira = session_factory()
    segunda = session_factory()
    try:
        await sincronizar(primeira, [_registro("AP-1")])
        # Sem commit de proposito: e esta janela, em que a linha existe no
        # indice mas nao para quem le, que abre a corrida.

        async def segundo_lote() -> None:
            await sincronizar(segunda, [_registro("AP-1", preco=59_000_000)])
            await segunda.commit()

        tarefa = asyncio.create_task(segundo_lote())
        # O INSERT do segundo lote trava no UNIQUE ate o commit do primeiro. A
        # espera garante os dois lados da corrida e, junto, uma distancia
        # mensuravel entre os dois carimbos.
        await asyncio.sleep(0.3)
        await primeira.commit()
        await tarefa
    finally:
        await primeira.close()
        await segunda.close()

    async with session_factory() as leitura:
        imovel = (await leitura.scalars(select(Imovel))).one()
        assert imovel.preco_venda == 59_000_000
        # Diferenca > 0.1s, e nao `!=`: os dois server_default sao
        # clock_timestamp() e nascem microssegundos separados no mesmo INSERT.
        # Os 0.3s de espera acima so aparecem aqui se o SET do conflito tiver
        # mexido no carimbo.
        assert (imovel.updated_at - imovel.created_at).total_seconds() > 0.1


async def test_o_upsert_mantem_a_dobra_do_bairro(session: Any) -> None:
    """A guarda escrita da D5: `bairro_busca` acompanha `bairro`, sempre.

    Esta coluna e derivada e escrita a mao porque o Postgres nao permite
    coluna gerada com `unaccent` (STABLE, nao IMMUTABLE). O preco disso e que
    um escritor novo pode esquece-la; este teste e o que pega o esquecimento.

    Duas metades, porque sao dois caminhos de escrita diferentes: o INSERT e o
    UPDATE de linha existente.
    """
    # `_registro` (linha 72 deste arquivo) nao expoe `bairro` -- ele fixa
    # "Centro". `replace` do dataclasses ja esta importado aqui, e sobrescreve
    # sem mexer no helper que outros doze testes usam.
    await sincronizar(session, [replace(_registro("AP-7001"), bairro="Aclimação")])
    await session.commit()

    imovel = await session.scalar(select(Imovel).where(Imovel.codigo == "AP-7001"))
    assert imovel is not None
    assert imovel.bairro == "Aclimação"
    assert imovel.bairro_busca == "aclimacao"

    # Segunda metade: a linha existe, e o bairro muda. Este e o caminho do
    # `setattr`, e nao o do INSERT -- sao dois lugares diferentes no
    # repositorio, e um pode ter a dobra sem o outro.
    await sincronizar(session, [replace(_registro("AP-7001"), bairro="Vila Madalena")])
    await session.commit()

    await session.refresh(imovel)
    assert imovel.bairro == "Vila Madalena"
    assert imovel.bairro_busca == "vila madalena"

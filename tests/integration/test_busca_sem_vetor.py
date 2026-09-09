"""A busca degrada para filtro SQL quando nao ha vetor. TEC-159, RNF-32.

O comportamento e da TEC-158; esta card so o fixa em teste, porque e um dos
tres cenarios do Gherkin da TEC-159. Basename distinto de tudo em
`tests/unit/` e `tests/perf/`.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import Operacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 50000000,
        "bairro": "Vila Mariana",
        "bairro_busca": "vila mariana",
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


async def test_sem_embedador_a_busca_devolve_por_filtro_sql(session: Any) -> None:
    """RNF-32: o atendimento continua funcionando sem indice vetorial.

    `embedador=None` e o caminho que a TEC-158 declarou nao ser erro. O que
    esta assercao protege e o desfecho: resultado devolvido, nao excecao.
    """
    identificador = await _imovel(session, "AP-001")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=None,
    )

    assert resultado.consulta_vetorizada is False
    assert [c.imovel_id for c in resultado.candidatos] == [identificador]


async def test_imovel_sem_embedding_ainda_e_candidato(session: Any) -> None:
    """Imovel indexado e imovel nao indexado convivem no mesmo resultado.

    A degradacao da RNF-32 nao e so "a consulta sem vetor funciona" -- e
    tambem "a linha sem vetor nao some da busca". A consulta de hoje e um
    SELECT de tabela unica, sem join nenhum -- mas a `0017` ja nomeia o
    mecanismo concreto que quebraria isto: uma consulta em dois estagios, que
    pre-filtra por ANN antes de reordenar os sobreviventes pelo score
    computado. Um pre-filtro ANN so acha linha que TEM `embedding` -- e
    dropa toda linha com `embedding IS NULL`, exatamente o candidato que esta
    assercao garante que nao suma. Sem esta assercao, o dia em que alguem
    fizer essa migracao (ver a nota da `0017` sobre o indice ser custo de
    escrita sem retorno de leitura hoje) passaria despercebido ate um imovel
    sem embedding sumir da busca em producao.
    """
    sem_vetor = await _imovel(session, "AP-001")
    com_vetor = await _imovel(session, "AP-002", embedding=[0.1] * 1536)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    encontrados = {c.imovel_id for c in resultado.candidatos}
    assert encontrados == {sem_vetor, com_vetor}


async def test_a_busca_sem_texto_nem_vetor_ainda_filtra(session: Any) -> None:
    """Sem `consulta_texto` nao ha o que vetorizar, e o filtro duro vale."""
    barato = await _imovel(session, "AP-001", preco_venda=30000000)
    await _imovel(session, "AP-002", preco_venda=90000000)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=50000000),
    )

    assert [c.imovel_id for c in resultado.candidatos] == [barato]

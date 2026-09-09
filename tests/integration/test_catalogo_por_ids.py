"""Leitura do catalogo por id, na ordem pedida. TEC-162.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.repositorio import imoveis_por_ids


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": f"Imovel {codigo}",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
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


async def test_devolve_na_ordem_pedida_e_nao_na_do_banco(session: Any) -> None:
    """A ordem pedida e a ordem de SCORE da busca.

    Sem esta garantia a ficha_1 poderia ser o terceiro melhor candidato, e o
    lead leria a pior opcao primeiro sem que nada falhasse.
    """
    primeiro = await _imovel(session, "AP-001")
    segundo = await _imovel(session, "AP-002")
    terceiro = await _imovel(session, "AP-003")

    encontrados = await imoveis_por_ids(session, [terceiro, primeiro, segundo])

    assert [i.id for i in encontrados] == [terceiro, primeiro, segundo]


async def test_id_ausente_sai_da_lista_em_vez_de_virar_none(session: Any) -> None:
    """D6: imovel inativado entre a busca e a apresentacao devolve a menos, e
    isso nao e erro -- o turno apresenta o que voltou."""
    existente = await _imovel(session, "AP-001")

    encontrados = await imoveis_por_ids(session, [existente, uuid.uuid4()])

    assert [i.id for i in encontrados] == [existente]


async def test_lista_vazia_devolve_tupla_vazia(session: Any) -> None:
    """`IN ()` e SQL invalido em alguns dialetos; o chamador nao deve precisar
    saber disso."""
    assert await imoveis_por_ids(session, []) == ()

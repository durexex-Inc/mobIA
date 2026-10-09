"""A vitrine paginada do portal publico (visual do portal, D7 e D8).

A busca do agente (`busca.py::buscar`) devolve no maximo `MAX_CANDIDATOS`
imoveis, ordenados pela relevancia da RN-09.6 e com o relaxamento da RN-09.3
-- e o que um corretor manda numa conversa. A vitrine e outra coisa: quem
navega quer ver TODOS os imoveis que casam com os filtros, paginados, na
ordem que escolher. Por isso esta consulta e propria, sem score e sem
relaxamento.

O que ela NAO tem de proprio e a regra de quem casa: o `WHERE` vem de
`busca.py::condicoes_do_filtro`, o mesmo da busca do agente.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from mobia.domain.catalogo.busca import condicoes_do_filtro
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca

# Doze por pagina: divide em uma, duas e tres colunas sem sobrar ladrilho, e
# e o bastante para o mapa ao lado ter pinos sem virar um borrao.
IMOVEIS_POR_PAGINA = 12


class OrdemDaVitrine(StrEnum):
    """As ordens que o portal oferece.

    Sem "mais relevantes": relevancia, aqui, seria o score da RN-09.6, e ele
    so discrimina com texto de consulta (similaridade) ou com teto de preco
    (aderencia) -- sem os dois, todo imovel empataria em 1,0 e a ordem seria
    a do desempate, com um nome que promete outra coisa.
    """

    RECENTES = "recentes"
    MENOR_PRECO = "menor_preco"
    MAIOR_PRECO = "maior_preco"
    MAIOR_AREA = "maior_area"


@dataclass(frozen=True)
class PaginaDaVitrine:
    imoveis: tuple[Imovel, ...]
    total: int


async def listar_vitrine(
    session: AsyncSession,
    filtro: FiltroDeBusca,
    ordem: OrdemDaVitrine,
    pagina: int,
) -> PaginaDaVitrine:
    """Uma pagina dos imoveis que casam com `filtro`, mais o total.

    `pagina` comeca em 1. Uma pagina alem da ultima devolve tupla vazia com
    o total certo -- quem chama decide o que mostrar, e o total e o que
    permite mostrar "volte para a primeira".
    """
    preco, condicoes = condicoes_do_filtro(filtro)
    criterio: ColumnElement[Any] = {
        OrdemDaVitrine.RECENTES: Imovel.created_at.desc(),
        OrdemDaVitrine.MENOR_PRECO: preco.asc(),
        OrdemDaVitrine.MAIOR_PRECO: preco.desc(),
        OrdemDaVitrine.MAIOR_AREA: Imovel.area_util_m2.desc(),
    }[ordem]

    consulta = (
        # A contagem na mesma passagem, como em `buscar`: a funcao de janela e
        # avaliada depois do WHERE e antes do LIMIT/OFFSET.
        select(Imovel, func.count().over().label("total"))
        .where(*condicoes)
        # Desempate por `id`, senao a mesma pagina muda entre duas visitas e um
        # imovel some entre a pagina 1 e a 2.
        .order_by(criterio, Imovel.id)
        .offset((max(pagina, 1) - 1) * IMOVEIS_POR_PAGINA)
        .limit(IMOVEIS_POR_PAGINA)
    )
    linhas = list(await session.execute(consulta))
    if linhas:
        return PaginaDaVitrine(imoveis=tuple(linha[0] for linha in linhas), total=linhas[0].total)

    # Pagina vazia nao diz o total pela janela -- ela nao teve linha nenhuma.
    # So aqui se paga um COUNT separado, e so quando ha algo a contar.
    if pagina <= 1:
        return PaginaDaVitrine(imoveis=(), total=0)
    total = await session.scalar(select(func.count()).select_from(Imovel).where(*condicoes))
    return PaginaDaVitrine(imoveis=(), total=total or 0)

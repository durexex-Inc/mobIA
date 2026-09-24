"""A aritmetica do funil. TEC-190, RN-17.2. Sem I/O."""

from collections.abc import Mapping
from dataclasses import dataclass

from mobia.domain.metricas.vocabulario import ETAPAS, SEM_FONTE, Etapa


@dataclass(frozen=True)
class EtapaDoFunil:
    """Uma etapa pronta para a resposta HTTP."""

    nome: str
    quantidade: int | None
    disponivel: bool
    conversao_da_anterior: float | None


def _conversao(anterior: int | None, atual: int | None) -> float | None:
    """A fracao da etapa anterior que chegou nesta, ou `None`.

    **Sao TRES as origens de `None`, e nenhuma delas e zero por cento:**

    1. nao ha etapa anterior (a primeira do funil);
    2. a anterior nao tem numero (`SEM_FONTE`) -- pular a etapa cega e
       dividir pela penultima daria um numero plausivel e errado;
    3. a anterior e zero -- 0 lead nao converteu em nada e tambem nao deixou
       de converter; a fracao nao existe. Devolver 0.0 aqui diria "ninguem
       passou", que e afirmacao diferente de "nao ha o que medir".
    """
    if anterior is None or atual is None or anterior == 0:
        return None
    return atual / anterior


def montar_funil(quantidades: Mapping[Etapa, int]) -> list[EtapaDoFunil]:
    """As seis etapas, sempre as seis, com a conversao entre consecutivas.

    Uma etapa em `SEM_FONTE` sai com `quantidade` nula ainda que
    `quantidades` traga numero para ela -- a ausencia de fonte e propriedade
    do vocabulario, e nao de quem consultou o banco.
    """
    valores: list[int | None] = [
        None if etapa in SEM_FONTE else quantidades.get(etapa, 0) for etapa in ETAPAS
    ]

    return [
        EtapaDoFunil(
            nome=etapa.value,
            quantidade=valores[indice],
            disponivel=etapa not in SEM_FONTE,
            conversao_da_anterior=(
                None if indice == 0 else _conversao(valores[indice - 1], valores[indice])
            ),
        )
        for indice, etapa in enumerate(ETAPAS)
    ]

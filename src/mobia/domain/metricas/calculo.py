"""A aritmetica do funil. TEC-190, RN-17.2. Sem I/O."""

from collections.abc import Mapping
from dataclasses import dataclass

from mobia.domain.metricas.vocabulario import ETAPAS, Etapa


@dataclass(frozen=True)
class EtapaDoFunil:
    """Uma etapa pronta para a resposta HTTP."""

    nome: str
    quantidade: int | None
    disponivel: bool
    conversao_da_anterior: float | None


def _conversao(anterior: int | None, atual: int | None) -> float | None:
    """A fracao da etapa anterior que chegou nesta, ou `None`.

    **Sao DUAS as origens de `None`, e nenhuma delas e zero por cento:**

    1. nao ha etapa anterior (a primeira do funil);
    2. a anterior e zero -- 0 lead nao converteu em nada e tambem nao deixou
       de converter; a fracao nao existe. Devolver 0.0 aqui diria "ninguem
       passou", que e afirmacao diferente de "nao ha o que medir".

    **Eram TRES ate a TEC-376**, e a que saiu era "a anterior nao tem numero":
    `AGENDADO` ficava sem fonte e pular a etapa cega para dividir `Handoff
    aceito` por `Recomendado` daria um numero plausivel e errado. Agora as
    seis etapas tem consulta, e nenhuma vem nula do repositorio -- a guarda
    de `None` nos parametros fica por contrato de tipo, e nao por caso
    alcancavel.
    """
    if anterior is None or atual is None or anterior == 0:
        return None
    return atual / anterior


def montar_funil(quantidades: Mapping[Etapa, int]) -> list[EtapaDoFunil]:
    """As seis etapas, sempre as seis, com a conversao entre consecutivas."""
    valores: list[int | None] = [quantidades.get(etapa, 0) for etapa in ETAPAS]

    return [
        EtapaDoFunil(
            nome=etapa.value,
            quantidade=valores[indice],
            # Constante desde a TEC-376, e o campo FICA (D8): tira-lo e
            # mudanca de contrato de verdade, e ele volta a valer no dia em
            # que uma etapa nova nascer sem fonte. Remover agora e recriar
            # depois troca uma constante por duas migracoes de contrato.
            disponivel=True,
            conversao_da_anterior=(
                None if indice == 0 else _conversao(valores[indice - 1], valores[indice])
            ),
        )
        for indice, etapa in enumerate(ETAPAS)
    ]

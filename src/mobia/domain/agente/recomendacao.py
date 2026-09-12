"""As regras puras da recomendacao e da reacao do lead.

TEC-163. Sem I/O e sem banco: o que precisa de sessao mora em
`repositorio.py`, e o que precisa do modelo mora em `classificador.py`. Aqui
ficam as decisoes que se testam sem nada de pe.
"""

import uuid
from collections.abc import Sequence

from mobia.domain.agente.schemas import ReacaoDoImovel

_SEM_CRITERIO = "sem filtro: o lead nao restringiu a busca"


def motivo_do_match(criterios: Sequence[str]) -> str:
    """A frase de explicabilidade da RN-10.3, montada dos criterios da busca.

    **Derivada, nunca escrita pelo modelo (D5).** Um motivo inventado ficaria
    gravado no banco como se fosse fato, e explicabilidade falsa e pior que
    explicabilidade pobre: a pobre se reconhece, a falsa nao.

    **E por BUSCA e nao por imovel (D4).** Todos os candidatos de uma busca
    casaram o mesmo filtro; o que os distingue e o `score_match`, que tem
    coluna propria. Um motivo por candidato seria a mesma frase repetida tres
    vezes, paga em tokens no `tool_result` de todo turno que busca.

    Lista vazia devolve uma frase e nao string vazia: a coluna e NOT NULL, e
    um campo de explicabilidade em branco deixa quem le a linha meses depois
    sem saber se nao houve filtro ou se alguem esqueceu de gravar.
    """
    return ", ".join(criterios) if criterios else _SEM_CRITERIO


def resolver_ordinais(
    reacoes: Sequence[ReacaoDoImovel], apresentados: Sequence[uuid.UUID]
) -> tuple[tuple[uuid.UUID, ReacaoDoImovel], ...]:
    """Casa cada reacao com o imovel daquela posicao. D7.

    **Ordinal fora de 1..N sai, e os outros ficam.** Um ordinal inventado nao
    pode invalidar as reacoes que o modelo acertou: o lead perderia a opiniao
    correta junto com a errada, e o turno nao tem como perguntar de novo.

    A guarda e `1 <= ordinal <= len(apresentados)` e nao um `try/except
    IndexError`, porque `apresentados[-1]` em Python devolve o ULTIMO item em
    vez de levantar -- um ordinal negativo marcaria o imovel errado, em
    silencio, e o lead veria a reacao dele aplicada a outro imovel.
    """
    return tuple(
        (apresentados[reacao.ordinal - 1], reacao)
        for reacao in reacoes
        if 1 <= reacao.ordinal <= len(apresentados)
    )

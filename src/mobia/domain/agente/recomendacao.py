"""As regras puras da recomendacao e da reacao do lead.

TEC-163. Sem I/O e sem banco: o que precisa de sessao mora em
`repositorio.py`, e o que precisa do modelo mora em `classificador.py`. Aqui
ficam as decisoes que se testam sem nada de pe.
"""

from collections.abc import Sequence

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

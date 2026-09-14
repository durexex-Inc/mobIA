"""A informacao nova que o follow-up entrega, montada sem tocar banco.

TEC-184. Modulo sem I/O de proposito -- mesmo molde de `handoff/vocabulario.py`
e `corretores/vocabulario.py`: e o que permite testar a regra em `tests/unit/`,
sem Postgres de pe. `repositorio.py` (com I/O) importa daqui, nunca o
contrario.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuedaDePreco:
    """Um imovel que o lead VIU e que hoje custa menos. TEC-184, D2.

    `preco_antes_centavos` sai de `recomendacoes.preco_centavos`, que e o
    numero que saiu na ficha -- fato historico, nao copia do preco do imovel
    (ver o comentario daquela coluna, TEC-275 D3). E e por isso que esta card
    nao precisa de tabela de historico de preco.
    """

    imovel_id: uuid.UUID
    preco_antes_centavos: int
    preco_agora_centavos: int

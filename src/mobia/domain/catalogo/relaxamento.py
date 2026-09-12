"""A politica de zero-resultado da RN-09.3: relaxar uma vez, e so uma.

TEC-160. **Modulo proprio, e nao dentro de `busca.py`**, por duas razoes (D1).
A docstring de `busca.py` afirma que "nao precisa de CTE nem de duas viagens ao
banco" e deriva dali a garantia de latencia; uma funcao que faz duas viagens
sob esse texto o torna falso, e este repo trata comentario desatualizado como
defeito. E montar a consulta e decidir a politica de zero-resultado sao
responsabilidades diferentes -- separa-las da a RN-09.3 um nome proprio nos
testes.

A seta aponta num sentido so: este modulo importa `busca`, nunca o contrario.
"""

from collections.abc import Sequence
from dataclasses import replace

from mobia.domain.catalogo.schemas import FiltroDeBusca


def e_relaxavel(filtro: FiltroDeBusca) -> bool:
    """Se ha alguma dimensao que a RN-09.3 saiba relaxar. D5.

    Sem teto, sem piso e sem regiao, o zero veio de tipo, quartos ou vagas --
    e a regra nao relaxa nenhum dos tres. A segunda consulta seria byte a byte
    igual a primeira: paga-se latencia contra o p95 de 400 ms da TEC-159 para
    receber o mesmo zero.

    E tambem a lacuna que o desenho da TEC-262 nomeou -- "relaxaria preco e
    bairro de uma busca que nunca teve chance". Ela fechou o caso do tipo;
    quartos e vagas seguem abertos (L3).
    """
    return (
        filtro.preco_max_centavos is not None
        or filtro.preco_min_centavos is not None
        or bool(filtro.regioes)
    )


def alargar(filtro: FiltroDeBusca, adjacentes: Sequence[str]) -> FiltroDeBusca:
    """O filtro do segundo passe: regioes UNIAO adjacentes, e `relaxado=True`.

    **O teto e o piso NAO se mexem aqui, de proposito.** A folga de preco e do
    `WHERE`, e mora dentro de `buscar` (D2 e D3). Escrever
    `preco_max_centavos = teto * 1,10` neste ponto faria a ancora de
    `_aderencia` viajar junto, e a promessa da emenda E-01 da RN-09.6 -- "10%
    acima do teto sai com 0,9" -- viraria falsa em silencio, com a ordenacao
    passando a favorecer o mais caro do conjunto AMPLIADO.

    **Uniao, e nao substituicao.** O cenario 4 do Gherkin diz "apenas bairros
    marcados como adjacentes a Trindade entram na busca"; ao pe da letra isso
    excluiria a propria Trindade, e esconderia o imovel que o preco relaxado
    acabou de tornar elegivel nela. "Apenas" limita de onde vem os novos, nao
    quem sai -- e o cenario 1 confirma ao dizer "preco ate R$ 440.000 E
    bairros adjacentes", nao "em vez de".

    Ordenado para que o `IN` gerado seja estavel entre execucoes: `set` nao tem
    ordem, e um IN que muda de ordem muda o SQL e invalida plano em cache sem
    motivo. E o mesmo argumento de `zonas_de`, em `busca.py`.
    """
    return replace(
        filtro,
        relaxado=True,
        regioes=tuple(sorted(set(filtro.regioes) | set(adjacentes))),
    )

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Intencao(StrEnum):
    """As sete intencoes da RN-03.1.

    O schema estrito da chamada ao modelo e derivado deste enum: acrescentar um
    membro aqui muda o conjunto de valores que o modelo pode devolver.
    """

    COMPRA = "COMPRA"
    ALUGUEL = "ALUGUEL"
    INVESTIMENTO = "INVESTIMENTO"
    VENDER_IMOVEL = "VENDER_IMOVEL"
    SUPORTE_CONTRATO = "SUPORTE_CONTRATO"
    INDEFINIDA = "INDEFINIDA"
    FORA_DE_ESCOPO = "FORA_DE_ESCOPO"


# Limiar da RN-03.2. `Decimal` e nao `float` porque a coluna e `numeric(3,2)` e
# a comparacao e de igualdade na borda: `0.6` em binario nao e 0,6, e "confianca
# exatamente 0,6 nao desambigua" e criterio de aceite.
#
# Fechado por cima: `< LIMIAR` desambigua, `>= LIMIAR` nao. O numero vem do SRS
# e nao esta calibrado -- confianca e autoavaliacao do modelo, nao
# probabilidade. Quem vai medi-lo contra as 50 conversas anotadas e a TEC-210, e
# este e o unico lugar que ela precisa mexer.
LIMIAR_DE_DESAMBIGUACAO = Decimal("0.6")


@dataclass(frozen=True)
class RespostaDoAgente:
    """O que uma chamada ao modelo devolve num turno.

    Intencao, confianca e resposta vem juntas porque vem da mesma chamada: o
    modelo enxerga a conversa inteira ao decidir as tres, entao a resposta ja
    sai coerente com a intencao que ele mesmo atribuiu.
    """

    intencao: Intencao
    confianca: Decimal
    resposta: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int

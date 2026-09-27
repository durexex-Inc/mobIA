"""A temperatura do lead: derivada do score, e forcavel por gatilho.

TEC-151, RN-06.2 e RN-06.3. Pura de proposito: sem I/O, sem banco, sem
chamada ao modelo -- mesma forma de `score.py`, `auditoria.py` e
`qualificacao.py`. Quem le a coluna e quem grava e o repositorio; aqui so se
decide qual e a temperatura.

**Os cortes sao os do SRS, e nao os do teto real do score.** O score topa em
95 com catalogo e 75 sem ele (a aderencia vale 20 e contribui zero ate a
TEC-158), e a RN-06.2 corta QUENTE em 70 -- um limiar desenhado para uma
escala que ia a 100. Perguntou-se em 02/09/2026 se esta card deveria
recalibrar, e a decisao foi aceitar: so tres totais alcancam 70 hoje,
{70, 72, 75}, cada um exigindo simultaneamente os quatro obrigatorios,
`urgencia == IMEDIATA`, forma de pagamento declarada e engajamento. **QUENTE
por faixa nao e uma faixa; e uma conjuncao de quase-maximos**, e por isso os
gatilhos da RN-06.3 sao o caminho principal, e nao a excecao.
"""

from dataclasses import replace
from enum import StrEnum

from mobia.domain.context.score import Score

CORTE_QUENTE = 70
CORTE_MORNO = 40


class Temperatura(StrEnum):
    QUENTE = "QUENTE"
    MORNO = "MORNO"
    FRIO = "FRIO"


def temperatura_de(score: Score, *, qualificado: bool, forcada: bool) -> Temperatura:
    """A temperatura da RN-06.2, com o teto da emenda e o forcamento da RN-06.3.

    **`forcada` curto-circuita antes de olhar o score**, e e o cenario 2 da
    card: "score 35 e temperatura FRIO... a temperatura passa a QUENTE... e o
    score permanece 35". Nada nesta card toca o score.

    **`qualificado` e teto, nao piso: ele so morde em QUENTE.** Um lead nao
    qualificado com total 45 ja era MORNO, e continua. O que o teto impede e
    a passagem para QUENTE, e a razao e a RN-06.5: QUENTE faz o telefone do
    corretor tocar. A TEC-150 declarou que dois estados alcancaveis somam 70
    com `esta_qualificado` False -- um deles com `intencao = None`, cuja
    intencao o sistema nunca determinou --, e enquanto nada consumia o numero
    declarar bastava. E **emenda E-01 a RN-06.2**, nao leitura dela.

    **`Score` e nao `int`.** A funcao usa so `.total`, e receber o total seria
    mais simples -- e abriria a porta para alguem passar `total_anterior` da
    trilha ou um numero montado a mao. O tipo e a unica coisa que impede a
    temperatura de ser derivada de um total cuja procedencia ninguem garante.

    **Os dois flags sao keyword-only**, pela razao que a TEC-150 aplicou as
    duas contagens de `calcular_score`: sao dois `bool` adjacentes, e inverter
    a ordem num chamador nao levanta, nao e erro de tipo, nao e visivel ao
    mypy, e devolve temperatura errada em silencio.

    **`score is None` nao e caso.** Quem chama ja sabe que ha linha -- sem
    linha nao ha sujeito, e `registrar_recalculo` devolve antes. Aceitar
    `None` aqui exigiria escolher entre FRIO e "sem temperatura" para um lead
    que nao existe, e as duas respostas seriam invencao.
    """
    if forcada:
        return Temperatura.QUENTE
    if score.total >= CORTE_QUENTE:
        return Temperatura.QUENTE if qualificado else Temperatura.MORNO
    if score.total >= CORTE_MORNO:
        return Temperatura.MORNO
    return Temperatura.FRIO


def temperatura_da_cadencia_de(score: Score, *, qualificado: bool, forcada: bool) -> Temperatura:
    """A temperatura que escolhe a regua de reengajamento: a de `temperatura_de`
    sem a penalidade de nao comparecimento. TEC-385, Emenda E-02 a RN-13.1.

    **So a penalidade sai, e nada mais muda.** O teto de `qualificado` e o
    forcamento valem igual: os dois dizem o que o LEAD sinalizou -- os
    obrigatorios que ele respondeu, o pedido de visita que ele fez --, e
    faltar a uma visita nao desfaz nenhum dos dois. O que a Emenda E-02 a RN-12.4
    tira da cadencia e so o desconto, que e o juizo sobre a falta.

    Por construcao, sem penalidade as duas funcoes devolvem o mesmo: e o
    terceiro cenario da card ("lead sem nao comparecimento nao muda nada").
    """
    return temperatura_de(replace(score, penalidade=0), qualificado=qualificado, forcada=forcada)

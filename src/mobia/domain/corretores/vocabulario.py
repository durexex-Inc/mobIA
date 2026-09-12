"""Especialidade, jornada e capacidade do corretor.

TEC-196. Modulo sem I/O de proposito, no molde de `handoff/vocabulario.py` e
de `context/auditoria.py`: e o que deixa a regra ser testada em `tests/unit/`,
sem Postgres de pe.
"""

from enum import StrEnum

# A jornada e em horas inteiras, e nao em `jsonb` por dia da semana como o
# modelo da secao 5 do SRS pede -- ver a emenda E-02 daquele modelo e a D2 do
# desenho. E a forma que o repo ja usa: `followup_horario_inicio` e
# `followup_horario_fim` em `app/config.py` representam janela assim, e
# `outbound/horario.py` consome nesse formato.
HORA_MINIMA = 0
HORA_MAXIMA = 23

# Zero nao e "desativado" -- para isso existe a coluna `ativo`. Capacidade
# zero seria uma linha que nunca recebe alocacao e que ninguem consegue
# explicar seis meses depois.
CAPACIDADE_MINIMA = 1


class Especialidade(StrEnum):
    """As quatro especialidades da card.

    **As tres primeiras sao grafadas identicas aos membros de `Intencao`**
    (`domain/agente/schemas.py`), e isso e deliberado: e por igualdade de
    string que a TEC-166 vai mapear intencao do lead para especialidade do
    corretor, sem tabela de traducao. Tabela de traducao seria um segundo
    lugar para a mesma verdade divergir.

    **Nao reusa o enum `Intencao`** porque os conjuntos nao coincidem:
    `Intencao` tem VENDER_IMOVEL, SUPORTE_CONTRATO, INDEFINIDA e
    FORA_DE_ESCOPO, que nao sao especialidade de ninguem. E acrescentar
    INVESTIMENTO_ALTO_TICKET la
    mudaria o schema estrito da chamada ao modelo -- a docstring de `Intencao`
    avisa que acrescentar um membro muda o conjunto que o modelo pode
    devolver.
    """

    COMPRA = "COMPRA"
    ALUGUEL = "ALUGUEL"
    INVESTIMENTO = "INVESTIMENTO"
    # Segmentacao de ticket, nao intencao de conversa. Por isso nao tem
    # correspondente em `Intencao`.
    INVESTIMENTO_ALTO_TICKET = "INVESTIMENTO_ALTO_TICKET"


def jornada_valida(inicio: int, fim: int) -> bool:
    """A jornada cabe no relogio e comeca antes de terminar.

    Fim igual ao inicio e recusado junto com fim antes do inicio: uma janela
    de duracao zero nao e jornada, e aceita-la poria no banco um corretor a
    quem a TEC-170 nunca conseguiria propor horario nenhum.
    """
    return HORA_MINIMA <= inicio < fim <= HORA_MAXIMA

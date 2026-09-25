"""Por que aquele corretor foi alocado. TEC-166, D4 do desenho.

Modulo sem I/O, no molde de `handoff/vocabulario.py`. Categoria e nao texto
livre: o que a gerente le e o motivo junto do corretor e do lead, montado
pela tela que existir -- texto gravado envelhece quando a regra muda.
"""

from enum import StrEnum


class MotivoDaAlocacao(StrEnum):
    # Especialidade e regiao casaram.
    MATCH_EXATO = "MATCH_EXATO"
    # Nenhum corretor ativo tinha especialidade e regiao; foi o plantao.
    SEM_MATCH = "SEM_MATCH"
    # Havia match exato, mas nenhum pode naquele dia -- sem capacidade ou
    # sem horario livre; foi o plantao.
    MATCH_SEM_CAPACIDADE = "MATCH_SEM_CAPACIDADE"

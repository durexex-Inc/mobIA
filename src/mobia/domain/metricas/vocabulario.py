"""As seis etapas do funil e o que ainda nao tem fonte. TEC-190, RN-17.2.

Modulo sem I/O, no molde de `conversa/vocabulario.py` e
`handoff/vocabulario.py`: e o que deixa a regra ser testada em `tests/unit/`
sem Postgres de pe.
"""

from enum import StrEnum


class Etapa(StrEnum):
    """Os seis estagios da RN-17.2, na ordem do funil.

    O VALOR e o rotulo que sai na resposta HTTP, e nao um codigo interno: o
    contrato do SRS (secao 6.6) lista `{"nome": "Novo", ...}`, e manter o
    rotulo aqui evita um segundo mapa de traducao que poderia divergir.
    """

    NOVO = "Novo"
    EM_CONVERSA = "Em conversa"
    QUALIFICADO = "Qualificado"
    RECOMENDADO = "Recomendado"
    AGENDADO = "Agendado"
    HANDOFF_ACEITO = "Handoff aceito"


# A ordem importa: a conversao de cada etapa e sobre a IMEDIATAMENTE anterior
# nesta tupla.
ETAPAS: tuple[Etapa, ...] = tuple(Etapa)

# Nao existe tabela de agendamento neste repo -- marcar visita e RF-11 e
# RF-12, epicos nao construidos. Enquanto for assim, a etapa sai com
# `quantidade: null` e `disponivel: false`, e NUNCA com zero: zero afirmaria
# que nenhuma visita foi marcada no periodo, quando a verdade e que nenhuma e
# registrada em lugar nenhum. Ver a D1 do desenho.
#
# Quando a RF-12 existir, tire `AGENDADO` daqui e escreva a consulta. Nem o
# contrato nem o frontend mudam.
SEM_FONTE: frozenset[Etapa] = frozenset({Etapa.AGENDADO})

# Os indicadores da RN-17.1 que dependem da mesma tabela ausente.
INDICADORES_SEM_FONTE: tuple[str, ...] = (
    "agendamentosCriados",
    "agendamentosConfirmados",
    "agendamentosRealizados",
    "taxaNoShow",
)

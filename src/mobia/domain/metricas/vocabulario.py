"""As seis etapas do funil e os indicadores de agendamento. TEC-190, RN-17.2.

Modulo sem I/O, no molde de `conversa/vocabulario.py` e
`handoff/vocabulario.py`: e o que deixa a regra ser testada em `tests/unit/`
sem Postgres de pe.

**Duas unidades de contagem convivem na mesma resposta** (TEC-376, D3), e
confundi-las faz uma das duas consultas parecer errada:

- as seis ETAPAS contam LEADS -- pares `(channel, conversation_key)`
  distintos --, porque conversao entre etapas so e fracao se as duas contarem
  a mesma coisa;
- os quatro INDICADORES de agendamento contam COMPROMISSOS. A gerente
  pergunta quantas visitas foram marcadas, nao quantas pessoas marcaram
  alguma.

Um lead com duas visitas soma 2 em `agendamentosCriados` e 1 na etapa
`Agendado`.
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

# As quatro chaves de agendamento da RN-17.1, na ordem em que o contrato do
# SRS (secao 6.6) as lista.
#
# **Ate a TEC-376 isto se chamava `INDICADORES_SEM_FONTE`** e nomeava o que
# FALTAVA: a tabela de agendamento existia desde a TEC-168, mas nenhum
# caminho de producao criava linha, entao conta-los sairia zero e zero diria
# "nenhuma visita foi marcada" quando o fato era "nenhuma e registrada". A
# TEC-371 acabou com isso -- `agendamento/conversa.py` cria agendamento a
# partir da fala do lead --, e a mesma lista passou a nomear o que a rota
# PUBLICA. Ver as Emendas E-01 a E-05 da RN-17.1.
INDICADORES_DE_AGENDAMENTO: tuple[str, ...] = (
    "agendamentosCriados",
    "agendamentosConfirmados",
    "agendamentosRealizados",
    "taxaNoShow",
)

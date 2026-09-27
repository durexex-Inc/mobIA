"""O vocabulario fechado dos direitos do titular. TEC-207, D2 do desenho.

Modulo sem I/O, no molde de `auditoria/vocabulario.py`: os tres enums tem copia
literal no CHECK de uma migration (`alembic/versions/0063_solicitacoes_de_titular.py`),
porque migration aplicada nao muda quando o codigo muda.
"""

from datetime import timedelta
from enum import StrEnum


class TipoDeSolicitacao(StrEnum):
    ELIMINACAO = "ELIMINACAO"
    ACESSO = "ACESSO"


class OrigemDaSolicitacao(StrEnum):
    WHATSAPP = "WHATSAPP"
    ADMIN = "ADMIN"
    # A retencao tambem registra uma solicitacao, ja atendida, para que toda
    # anonimizacao tenha registro e entidade na trilha (D2 e D5 do desenho).
    RETENCAO = "RETENCAO"


class StatusDaSolicitacao(StrEnum):
    ABERTA = "ABERTA"
    ATENDIDA = "ATENDIDA"
    RECUSADA = "RECUSADA"


# RNF-21 / D2 do desenho. Prazo legal para atender um pedido do titular.
PRAZO_DO_TITULAR = timedelta(days=15)

# D5 do desenho. O sweep de retencao cumpre a ELIMINACAO aberta que vence ate
# um dia a frente, e nao so a que ja venceu: ele passa uma vez por dia, e com
# esta antecedencia a passagem diaria sempre cai dentro do prazo. Ver
# `repositorio.py::vencendo`.
ANTECEDENCIA_DO_CUMPRIMENTO = timedelta(days=1)

# D5 do desenho. Lead sem conversao (nenhum handoff ACEITO ou CONCLUIDO) com
# mais de 24 meses desde a ultima interacao (max(messages.created_at)) e
# anonimizado. Conteudo de mensagem com mais de 12 meses, de qualquer lead,
# e esvaziado.
RETENCAO_DO_LEAD_MESES = 24
RETENCAO_DA_TRANSCRICAO_MESES = 12

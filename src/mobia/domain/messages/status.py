from enum import StrEnum


class MessageStatus(StrEnum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    # TEC-209, D5. A dead-letter queue: as tentativas esgotaram, e o handoff
    # por erro ja nasceu. Terminal -- fora de `CLAIMABLE_STATUSES`, entao nem o
    # sweeper nem o claim a pegam. So o reprocessamento manual
    # (`POST /api/v1/mensagens/{id}/reprocessar`) a devolve ao pipeline.
    #
    # E status, e nao marca paralela como `bloqueada_em`, porque a pergunta
    # aqui E a de `CLAIMABLE_STATUSES` -- "ainda vale retentar?". Antes dela,
    # FAILED com `attempts >= sweep_max_attempts` era terminal de fato, mas sem
    # nome: so quem soubesse o numero conseguia listar a fila.
    ESGOTADA = "ESGOTADA"


CLAIMABLE_STATUSES: tuple[MessageStatus, ...] = (
    MessageStatus.RECEIVED,
    MessageStatus.QUEUED,
    MessageStatus.PROCESSING,
    MessageStatus.FAILED,
)

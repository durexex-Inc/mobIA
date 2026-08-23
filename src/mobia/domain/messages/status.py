from enum import StrEnum


class MessageStatus(StrEnum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


CLAIMABLE_STATUSES: tuple[MessageStatus, ...] = (
    MessageStatus.RECEIVED,
    MessageStatus.QUEUED,
    MessageStatus.PROCESSING,
    MessageStatus.FAILED,
)

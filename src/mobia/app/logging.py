import logging
import sys
from contextvars import ContextVar

import structlog
from structlog.typing import EventDict, WrappedLogger

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def _add_correlation_id(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    value = correlation_id.get()
    if value:
        event_dict["correlation_id"] = value
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

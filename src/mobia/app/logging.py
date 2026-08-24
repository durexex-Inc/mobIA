import logging
import re
import sys
from contextvars import ContextVar

import structlog
from structlog.typing import EventDict, ProcessorReturnValue, WrappedLogger

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def _add_correlation_id(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    value = correlation_id.get()
    if value:
        event_dict["correlation_id"] = value
    return event_dict


# 10 a 15 digitos seguidos: cobre telefone nacional com e sem DDI.
_CORRIDA_DE_DIGITOS = re.compile(r"\d{10,15}")

# Um UUID termina em 12 digitos hexadecimais que podem ser todos decimais, e o
# `message_id` aparece em quase todo evento de ingestao. Mascarar isso mataria a
# correlacao entre eventos sem proteger ninguem.
_UUID = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)

# Conteudo de lead: nao ha versao segura de logar, entao some inteiro.
_CHAVES_REDIGIDAS = frozenset({"text_body", "raw_payload", "envelope_context"})


def _mascarar_digitos(texto: str) -> str:
    if _UUID.match(texto):
        return texto
    return _CORRIDA_DE_DIGITOS.sub(
        lambda achado: "*" * (len(achado.group()) - 4) + achado.group()[-4:],
        texto,
    )


def _mascarar_pii(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Segunda linha de defesa do mascaramento.

    A primeira e nao logar conteudo, e ela ja vale hoje. Esta existe para o dia
    em que alguem esquecer: disciplina que depende de lembrar vaza uma hora.
    """
    for chave, valor in list(event_dict.items()):
        if chave in _CHAVES_REDIGIDAS:
            event_dict[chave] = "<redigido>"
        elif isinstance(valor, str):
            event_dict[chave] = _mascarar_digitos(valor)
        elif isinstance(valor, list):
            event_dict[chave] = [
                _mascarar_digitos(item) if isinstance(item, str) else item for item in valor
            ]
    return event_dict


_renderizar_json = structlog.processors.JSONRenderer()


def _finalizar(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> ProcessorReturnValue:
    """Serializa o evento e desarma o `exc_info` real do LogRecord.

    `logging.Logger.exception` religa `exc_info=True` por conta propria mesmo
    quando so passamos a linha ja pronta, entao sem isso o Formatter padrao
    duplica o traceback original -- sem mascara -- depois do JSON que ja o
    contem mascarado via `exception`.
    """
    linha = _renderizar_json(logger, method_name, event_dict)
    return (linha,), {"exc_info": False}


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            # sem isso o traceback so nasce depois do JSONRenderer, fora do
            # alcance do mascaramento: tem de virar chave do dict antes.
            structlog.processors.format_exc_info,
            _mascarar_pii,
            _finalizar,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

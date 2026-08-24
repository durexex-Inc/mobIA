import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

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

# Chaves estruturalmente livres de PII: digest, id de correlacao e id de
# mensagem. Sem esta lista o mascaramento come um sha256 sempre que ele tem 10
# ou mais digitos decimais seguidos -- cerca de um em cada cinco -- e
# `payload_sha256` e a unica alca de correlacao que sobra num webhook rejeitado,
# justamente o caso que alguem vai depurar depois. Mesma classe de falso
# positivo que o `_UUID` acima ja tratava.
_CHAVES_LIVRES = frozenset(
    {
        "payload_sha256",
        "correlation_id",
        "message_id",
        "message_ids",
        "provider_message_id",
    }
)

# Identificador do interlocutor. Hoje e sempre telefone brasileiro e a corrida
# de digitos pega por acidente; o widget web do TEC-124 vai trazer id de sessao
# ou e-mail, que nao sao digitos. Mascarar pela chave torna a garantia
# estrutural em vez de dependente do formato do canal.
_CHAVES_MASCARADAS = frozenset({"sender_external_id", "recipient_external_id", "conversation_key"})

_CAUDA_VISIVEL = 4


def _mascarar_digitos(texto: str) -> str:
    if _UUID.match(texto):
        return texto
    return _CORRIDA_DE_DIGITOS.sub(
        lambda achado: (
            "*" * (len(achado.group()) - _CAUDA_VISIVEL) + achado.group()[-_CAUDA_VISIVEL:]
        ),
        texto,
    )


def _mascarar_inteiro(texto: str) -> str:
    """Mesma forma do mascaramento por digito: so a cauda sobrevive.

    A cauda serve para o operador confirmar que dois eventos falam do mesmo
    interlocutor sem que o log carregue o identificador.
    """
    if len(texto) <= _CAUDA_VISIVEL:
        return "*" * len(texto)
    return "*" * (len(texto) - _CAUDA_VISIVEL) + texto[-_CAUDA_VISIVEL:]


def _mascarar_valor(chave: str | None, valor: Any) -> Any:
    """Desce por dict, list e tuple.

    Andar so no nivel de cima deixava PII escapar inteira um nivel abaixo de
    qualquer chave nao redigida -- o valor aninhado nunca chegava a ser visto.
    """
    if chave in _CHAVES_REDIGIDAS:
        return "<redigido>"
    if chave in _CHAVES_LIVRES:
        return valor
    if isinstance(valor, str):
        if chave in _CHAVES_MASCARADAS:
            return _mascarar_inteiro(valor)
        return _mascarar_digitos(valor)
    if isinstance(valor, dict):
        return {
            sub: _mascarar_valor(sub if isinstance(sub, str) else chave, item)
            for sub, item in valor.items()
        }
    if isinstance(valor, list):
        return [_mascarar_valor(chave, item) for item in valor]
    if isinstance(valor, tuple):
        return tuple(_mascarar_valor(chave, item) for item in valor)
    return valor


def _mascarar_pii(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Segunda linha de defesa do mascaramento.

    A primeira e nao logar conteudo, e ela ja vale hoje. Esta existe para o dia
    em que alguem esquecer: disciplina que depende de lembrar vaza uma hora.
    """
    for chave, valor in list(event_dict.items()):
        event_dict[chave] = _mascarar_valor(chave, valor)
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

import logging
import re
import sys
import traceback
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
# `resumo` (TEC-127) entra pela mesma razao de `text_body`: destila as mesmas
# frases do lead, so que condensadas. `corpo` (TEC-177) e o texto da
# notificacao ao corretor, que carrega o resumo decifrado (ou o literal de
# `TEXTO_SEM_RESUMO`) -- mesmo motivo de `resumo`, so que para o dia em que
# alguem esquecer.
_CHAVES_REDIGIDAS = frozenset({"text_body", "raw_payload", "envelope_context", "resumo", "corpo"})

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

# Identificador do interlocutor. Desde a TEC-203 o `conversation_key` (e a
# ponta do lead em sender/recipient) e o HMAC do telefone ou da sessao
# (`identidade/indice.py::chave_de`), e nao o valor cru -- mascarar um
# pseudonimo e inofensivo. A mascara continua pela chave, e nao pelo formato,
# porque a garantia tem de ser estrutural: a corrida de digitos so pegava o
# telefone por acidente, e nao pega sessao nem e-mail.
#
# `ip` (TEC-205) entra pelo mesmo argumento, e de forma ainda mais clara: a
# corrida de digitos NAO pega um IPv4, porque os pontos a quebram. A tabela
# `rate_limit_events` guarda o endereco inteiro, porque e ela que responde
# "quem foi" numa investigacao; o log, que vai para agregador e fica muito
# mais exposto, sai mascarado.
_CHAVES_MASCARADAS = frozenset(
    {"sender_external_id", "recipient_external_id", "conversation_key", "ip"}
)

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


# As duas frases que o proprio Python usa para ligar as secoes de uma cadeia.
# Copiadas literalmente porque quem le o log ja as reconhece; inventar frase
# nova aqui so tornaria o traceback estranho sem ganhar nada.
_ELO_CAUSA = "The above exception was the direct cause of the following exception:"
_ELO_CONTEXTO = "During handling of the above exception, another exception occurred:"


def _excecao_de(valor: object) -> BaseException | None:
    """Normaliza as tres formas que `exc_info` assume no structlog.

    `log.exception(...)` e `exc_info=True` chegam como `True`; um `except ... as
    erro` repassado chega como instancia; e o stdlib usa a tupla de tres.
    """
    if isinstance(valor, BaseException):
        return valor
    if isinstance(valor, tuple) and len(valor) == 3:
        segundo = valor[1]
        return segundo if isinstance(segundo, BaseException) else None
    if valor is True:
        return sys.exc_info()[1]
    return None


def _sanear_traceback(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Poe a pilha no log e deixa a mensagem da excecao de fora.

    Substitui `structlog.processors.format_exc_info`, que entregava o traceback
    inteiro -- terminando em `TipoDoErro: <mensagem>` em CADA secao da cadeia.
    Numa falha de gravacao, essa mensagem e a linha `DETAIL` que o Postgres
    escreve, e numa violacao de CHECK ela traz a linha inteira: medido na
    TEC-293, a fala do lead aparecia duas vezes, porque a SQLAlchemy reembala a
    excecao do asyncpg e as duas secoes repetem o texto.

    Por isso o corte e estrutural e nao textual: a mensagem nao esta so na
    ultima linha -- a da wrapper ocupa quatro, e a da causa fica no meio.

    **Nao troque isto pelo `ExceptionDictTransformer` do structlog.** Medido na
    TEC-293: ele nasce com `show_locals=True`, que despeja as variaveis locais
    de cada frame -- inclusive o objeto que estava sendo gravado --, e mesmo com
    `show_locals=False` mantem `exc_value`, que e a mensagem inteira. Adota-lo
    seria regressao, nao simplificacao.

    O que sai daqui: por secao da cadeia, uma linha por frame com arquivo,
    linha e funcao, e o tipo qualificado no lugar da mensagem. Sem a linha de
    codigo-fonte, que nao carrega valor de runtime (o argumento vem de
    variavel) e por isso e escolha de volume, nao de protecao.
    """
    excecao = _excecao_de(event_dict.pop("exc_info", None))
    if excecao is None:
        return event_dict

    # A travessia nao leva guarda de ciclo: quem corta `a.__cause__ = b;
    # b.__cause__ = a` e o proprio `TracebackException`, que guarda os nos
    # vistos ao construir. Guarda nossa por cima nunca dispararia, e
    # `test_cadeia_ciclica_nao_pendura` fixa a dependencia.
    cadeia: list[tuple[traceback.TracebackException, str | None]] = []
    atual: traceback.TracebackException | None = traceback.TracebackException(
        type(excecao), excecao, excecao.__traceback__
    )
    elo: str | None = None
    while atual is not None:
        cadeia.append((atual, elo))
        if atual.__cause__ is not None:
            atual, elo = atual.__cause__, _ELO_CAUSA
        elif atual.__context__ is not None and not atual.__suppress_context__:
            atual, elo = atual.__context__, _ELO_CONTEXTO
        else:
            atual, elo = None, None

    linhas: list[str] = []
    for item, ligacao in reversed(cadeia):
        linhas.append("Traceback (most recent call last):")
        for frame in item.stack:
            linhas.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
        linhas.append(item.exc_type_str)
        if ligacao is not None:
            linhas.extend(("", ligacao, ""))

    event_dict["exception"] = "\n".join(linhas)
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
    # TEC-132. O httpx loga em INFO a linha `HTTP Request: GET <url completa>`
    # de toda requisicao, fora do structlog e portanto fora do mascaramento
    # abaixo. Para o download de midia essa URL e credencial temporaria da
    # Meta (D3: "nunca a URL"), e com o nivel padrao ela ia para stdout a cada
    # arquivo baixado. WARNING corta tudo o que o logger `httpx` emite abaixo
    # disso -- a linha de requisicao em INFO e tambem o DEBUG dele, que some
    # mesmo com LOG_LEVEL=DEBUG. Como o httpx nao loga nada acima de INFO por
    # conta propria, na pratica o logger fica mudo, e erro de rede chega a
    # quem chama como excecao, nao como log dele. O `httpcore` e logger a
    # parte e nao e tocado aqui.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            # sem isso o traceback so nasce depois do JSONRenderer, fora do
            # alcance do mascaramento: tem de virar chave do dict antes. O
            # `format_exc_info` do structlog ocupava esta posicao ate a
            # TEC-293; ele entregava a mensagem da excecao junto, e sobre a
            # chave `exception` a unica defesa era a corrida de digitos, que
            # nao alcanca texto livre.
            _sanear_traceback,
            _mascarar_pii,
            _finalizar,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

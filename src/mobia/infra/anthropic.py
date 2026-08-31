from functools import lru_cache

from anthropic import APIStatusError, AsyncAnthropic

from mobia.app.config import ConfiguracaoInsegura, get_settings

# O default do SDK e 10 minutos por requisicao, com retentativa interna --
# muito acima do `job_timeout` do worker (240s). Sem um teto proprio, uma
# chamada lenta nao falha: ela e cancelada pelo ARQ. Desde a TEC-227 o
# cancelamento deixa de ser invisivel -- `process_message` marca FAILED e o
# `GuardedOutbound` libera a reserva -- mas continua sendo o desfecho pior:
# custa a passada inteira do turno, com as chamadas pagas ao modelo, e pode
# duplicar a entrega. Falha tipada e recuperavel de graca; cancelamento nao.
# 60s por tentativa, uma retentativa: no pior caso 120s por chamada.
#
# Isso nao sobra folga dentro dos 240s do `job_timeout`. O turno paga entre
# uma e tres chamadas deste cliente em sequencia -- `resumir` (as vezes, a
# cada ~40 mensagens), `classificar` (sempre) e, desde a TEC-135,
# `desambiguar` (so no turno ambiguo, logo depois de `classificar`). Duas
# delas ja fecham a conta em 240s (2 x 120s); com as tres, o pior caso soma
# 360s -- acima do teto antes mesmo de contar `count_tokens` ou o POST para a
# Meta. Ver o comentario de `job_timeout` em `workers/main.py`.
TIMEOUT_SEGUNDOS = 60.0
MAX_TENTATIVAS = 1


@lru_cache
def get_client() -> AsyncAnthropic:
    """Cliente unico do processo.

    Construido sob demanda e nao no import: importar o modulo nao pode exigir
    credencial, senao a suite inteira passa a precisar de chave para colecionar
    testes que nunca chamam o provedor.
    """
    chave = get_settings().anthropic_api_key
    if not chave:
        raise ConfiguracaoInsegura(
            "ANTHROPIC_API_KEY nao configurada. O resumo do TEC-127 precisa dela; "
            "defina no .env ou no ambiente antes de subir a API ou o worker."
        )
    return AsyncAnthropic(api_key=chave, timeout=TIMEOUT_SEGUNDOS, max_retries=MAX_TENTATIVAS)


# Teto do texto que vem do provedor. A mensagem que resolveu o incidente de
# 28/08 cabe em ~120 caracteres; o teto existe para o dia em que ela nao
# couber, porque log estruturado nao e lugar de despejo.
MAX_CARACTERES_DO_MOTIVO = 300


def motivo_do_provedor(exc: BaseException) -> str | None:
    """O porque de um erro de protocolo do provedor, sem conteudo do lead.

    **Isto e uma excecao deliberada a regra de nunca logar `str(exc)`**, e a
    regra continua valendo em todo o resto. A distincao que a justifica: o
    corpo de erro de um `APIStatusError` e **gerado pelo servidor** em resposta
    a requisicao, e nao o texto que uma excecao qualquer do Python monta
    interpolando o valor que a fez estourar. Um `KeyError` de um schema
    inesperado ecoa o valor recebido; um 400 da API devolve prosa que o
    servidor escreveu.

    Por isso o `isinstance` e a guarda inteira: qualquer excecao que nao seja
    `APIStatusError` devolve `None`, e nenhum texto dela chega a lugar nenhum.
    Nao ha ramo "melhor esforco" -- ele seria exatamente o buraco que esta
    funcao existe para nao abrir.

    **Por que a card existe (TEC-237).** Em 28/08/2026 o gate pago falhou em
    100% das chamadas com `BadRequestError`, e o diagnostico levou um dia por
    tres hipoteses erradas. A causa estava na primeira linha do corpo de erro,
    que ninguem via porque so o nome da classe era registrado:

        400 invalid_request_error: Your credit balance is too low to access
        the Anthropic API.

    Saldo esgotado volta como **400**, o mesmo codigo de um erro de contrato.
    Sem a mensagem nao ha como separar "a conta acabou" de "o schema quebrou".

    **O risco que sobra, e ele nao e zero.** A garantia depende de o provedor
    nao ecoar o payload no corpo de erro. Isso vale para os erros de conta,
    permissao e limite -- os que motivaram esta funcao --, mas um erro de
    validacao de schema poderia, em tese, citar o valor recusado. Tres coisas
    limitam o estrago: o teto de caracteres, o mascaramento de corrida de
    digitos que `app/logging.py` aplica a todo valor logado, e o fato de a
    chamada do classificador mandar a fala do lead em `messages`, que a API
    valida por forma e nao por conteudo. Nao e prova; e o balanco entre um dia
    de diagnostico e um risco estreito, tomado com os olhos abertos.
    """
    if not isinstance(exc, APIStatusError):
        return None

    corpo = exc.body if isinstance(exc.body, dict) else {}
    erro = corpo.get("error")
    erro = erro if isinstance(erro, dict) else {}

    tipo = erro.get("type")
    mensagem = erro.get("message")

    partes = [str(exc.status_code)]
    if isinstance(tipo, str) and tipo:
        partes.append(tipo)
    resumo = " ".join(partes)
    if isinstance(mensagem, str) and mensagem:
        cortada = mensagem[:MAX_CARACTERES_DO_MOTIVO]
        sufixo = "..." if len(mensagem) > MAX_CARACTERES_DO_MOTIVO else ""
        resumo = f"{resumo}: {cortada}{sufixo}"

    # `request_id` e o handle de correlacao com o suporte do provedor, e nao
    # tem conteudo nenhum. Ele nao estava no escopo da card e entra porque a
    # proxima investigacao vai querer citar um numero para quem atende.
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and request_id:
        resumo = f"{resumo} (request_id={request_id})"
    return resumo

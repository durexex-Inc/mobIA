import math
from functools import lru_cache

from anthropic import APIStatusError, AsyncAnthropic

from mobia.app.config import ConfiguracaoInsegura, get_settings

# O default do SDK e 10 minutos por requisicao -- muito acima do `job_timeout`
# do worker (240s). Sem teto proprio, uma chamada lenta nao falha: ela e
# cancelada pelo ARQ. Desde a TEC-227 o cancelamento deixa de ser invisivel --
# `process_message` marca FAILED e o `GuardedOutbound` libera a reserva -- mas
# continua sendo o desfecho pior: custa a passada inteira do turno, com as
# chamadas pagas ao modelo, e pode duplicar a entrega. Falha tipada e
# recuperavel de graca; cancelamento nao.
#
# Este numero e o PISO, e nao o teto de ninguem no turno: quem faz uma fatia do
# turno manda o seu proprio (abaixo). Ele governa quem nao pede teto nenhum --
# hoje `followup/prosa.py` e `handoff/resumo.py`, as duas chamadas de fora do
# turno, que ninguem mediu e que nao disputam este orcamento. Existe para que
# uma chamada nova que esqueca o override nao herde os dez minutos do SDK.
TIMEOUT_SEGUNDOS = 60.0

# Zero, e a razao esta na aritmetica logo abaixo: com uma retentativa o pior
# turno dobra para 324s e continua estourando o `job_timeout`, mesmo com todos
# os tetos por tipo. E a retentativa que come metade do orcamento.
#
# Nao e decisao nova -- a moderacao ja a tomou, citando esta card pelo nome
# (ver `MAX_TENTATIVAS_DA_MODERACAO` em `infra/moderacao.py`). O que mudou e o
# alcance: o mesmo argumento vale para o cliente que faz as cinco fatias.
#
# A medicao sustenta: as chamadas levam de 0,25s a 9,3s (relatorio de
# 16/09/2026 em `evals/relatorios/`). Estourar contra 25s nao e lentidao, e
# pane -- e retentar uma pane custa outros 25s pelo mesmo desfecho.
#
# **O que se perde, e nao e nada.** A retentativa tambem cobria 429, 5xx e
# queda de conexao, onde retentar e barato e costuma funcionar
# (`_should_retry_exception` do SDK). Sem ela, um 429 deixa de ser reparado
# dentro da requisicao e passa a ser reparado pelo sweeper, que refaz o turno
# INTEIRO e repaga as chamadas que ja tinham dado certo. A troca e deliberada:
# um orcamento que fecha vale mais que uma retentativa barata num caminho raro.
MAX_TENTATIVAS = 0

# Os tetos por tipo de chamada, derivados da medicao de 16/09/2026 com folga de
# ~3x sobre o maximo observado. A folga nao e arbitraria: as amostras repetiram
# o mesmo prompt de sistema e provavelmente pegaram prompt cache, entao sao
# otimistas para o primeiro turno de uma conversa, que e o caso frio.
#
#   chamada        teto   maximo medido   folga
#   count_tokens    5s        0,28s        18x
#   desambiguar    12s        1,69s         7x
#   resumir        25s        3,72s       6,7x
#   classificar    25s        7,49s       3,3x
#   investidor     35s        9,26s       3,8x
#
# **Por que teto por tipo e nao um numero so.** As chamadas vao de 0,25s a
# 9,3s. Um teto unico ou e frouxo para a mais rapida ou e apertado para a mais
# lenta; e as consequencias de estourar tambem sao diferentes -- `desambiguar`
# perde a pergunta daquele turno, `classificar` perde o turno inteiro.
#
# `count_tokens` fica em 5s por ser ida-e-volta de rede e nao geracao. A folga
# de 18x soa exagerada e nao e: 18x um maximo de 0,28s ainda da 5s, menos da
# metade do menor teto de geracao. Folga em percentual nao e folga em
# segundos, e o orcamento se paga em segundos.
#
# `reagir` nao foi medido. Herda o numero de `desambiguar` porque tem a mesma
# forma -- 300 tokens de saida, sem ferramenta, uma requisicao so -- e isso
# esta dito aqui em vez de escondido num numero de aparencia medida.
TETO_DO_COUNT_TOKENS = 5.0
TETO_DA_DESAMBIGUACAO = 12.0
TETO_DA_REACAO = 12.0
TETO_DO_RESUMO = 25.0
TETO_DA_CLASSIFICACAO = 25.0
TETO_DO_INVESTIDOR = 35.0


# O pior turno, fatia a fatia, com quantas REQUISICOES cada uma pode fazer.
#
# Sao cinco fatias: `count_tokens` e `resumir` em `montar_contexto`, `reagir`,
# a chamada 1 (`classificar` ou `qualificar_investidor`, conforme o lead ja
# seja investidor) e a chamada 2 (`desambiguar`, ou `qualificar_investidor` na
# virada). Todas em `turno.py`, citadas pelo nome e nao pela linha: este bloco
# ja nasceu de um comentario que envelheceu, e numero de linha e a parte que
# envelhece primeiro.
#
# **Duas fatias custam DUAS requisicoes.** O laco `for tentativa in (1, 2)` de
# `_chamar` bate no provedor de novo quando o modelo pede a ferramenta de
# busca. Contar uma requisicao por fatia subconta o pior caso pela metade nas
# duas fatias mais caras -- foi assim que o comentario anterior deste arquivo
# chegou a 360s quando o numero real era 840s.
#
# As duas chamadas de investidor sao exclusivas entre si: a da virada so
# dispara quando a chamada 1 NAO foi a do investidor. Por isso o pior par e
# `classificar` com busca seguido de `qualificar_investidor` com busca, e nao
# investidor duas vezes.
#
# **E duas fatias custam N requisicoes, derivadas da configuracao (TEC-229).**
# A versao anterior contava `resumir` e `count_tokens` uma vez cada, e era a
# mesma classe de erro do paragrafo acima, uma camada abaixo: `montar_contexto`
# nao chama nenhum dos dois uma vez so.
def _pior_turno() -> tuple[tuple[float, int], ...]:
    """As fatias do turno e quantas requisicoes cada uma faz no pior caso.

    Funcao e nao constante porque duas fatias dependem de `Settings`, e
    `get_settings()` no import seria pior que a constante que isto substitui.
    """
    settings = get_settings()

    # `resumir`: a dobra do gatilho de acumulacao (`deve_regenerar`), mais uma
    # por volta do laco `while tokens > teto`, que para em
    # `contexto_max_iteracoes`.
    resumos = 1 + settings.contexto_max_iteracoes

    # `count_tokens`: a contagem antes do laco, uma por volta, e as de
    # `_truncar_ate_caber` -- que corta a janela pela metade a cada passo,
    # chegando a uma literal em log2(N), mais uma contagem se ainda precisar
    # descartar o resumo.
    #
    # **N vem do gatilho, e isso e suposicao e nao teorema.** O gatilho dobra
    # em 40 literais, entao em regime normal a janela que chega ao truncamento
    # tem essa ordem de grandeza; se a dobra falhar, `literais` passa disso. O
    # `max(..., 1)` existe para que um gatilho mal configurado em 0 nao leve
    # `log2` a `-inf` -- o teto fica errado, mas a funcao nao explode.
    #
    # **O termo e pessimista de proposito.** `_contar_se_valer` so paga o
    # round trip acima do limiar, e cortar pela metade derruba a contagem
    # rapido: na pratica o truncamento nao paga todas estas. Um teto nao pode
    # depender de quao rapido o texto encolhe, e subcontar aqui e o defeito
    # que a TEC-229 veio matar.
    cortes = math.ceil(math.log2(max(settings.contexto_gatilho_de_regeneracao, 1))) + 1
    contagens = 1 + settings.contexto_max_iteracoes + cortes

    return (
        (TETO_DO_COUNT_TOKENS, contagens),
        (TETO_DO_RESUMO, resumos),
        (TETO_DA_REACAO, 1),
        (TETO_DA_CLASSIFICACAO, 2),
        (TETO_DO_INVESTIDOR, 2),
    )


def segundos_do_modelo_no_pior_turno() -> float:
    """O teto de tempo que um turno pode gastar falando com ESTE provedor.

    Existe para entrar na soma de `tests/unit/test_orcamento_do_turno.py`, que
    a compara com o `job_timeout` do worker.

    **Esse teste esta `xfail` desde a TEC-229 e nao guarda mais nada sozinho.**
    Quem guarda a derivacao sao os dois testes irmaos de la, que afirmam que
    subir `contexto_max_iteracoes` ou o gatilho move este numero. Enquanto a
    TEC-290 nao fechar o orcamento, apagar aqueles dois deixa esta funcao livre
    para voltar a ser constante sem nada perceber.

    **E so a parcela da Anthropic, e o nome diz isso de proposito.** O turno
    paga outros tres clientes externos -- o embed da busca (`infra/embeddings.py`,
    o MAIOR termo antes da TEC-228), a moderacao das duas pontas e o POST para a
    Meta --, alem do banco. Quem somar so esta funcao contra os 240s conclui que
    ha folga de sobra, que foi exatamente o erro do comentario que esta card
    encontrou. A soma inteira mora no teste.
    """
    return sum(teto * requisicoes for teto, requisicoes in _pior_turno()) * (MAX_TENTATIVAS + 1)


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

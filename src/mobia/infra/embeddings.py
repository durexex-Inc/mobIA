"""Cliente do provedor de embedding, no molde do `infra/anthropic.py`.

TEC-157. **Este NAO e o cliente da Anthropic**, e a razao e simples: a API da
Anthropic tem Messages, Batches, Files, Token Counting e Models, e nao tem
endpoint de embeddings. Esta card introduz necessariamente um segundo
provedor. O agente continua no `infra/anthropic.py`.

O teto por chamada segue o mesmo raciocinio do vizinho: o default do SDK e
alto demais para o `job_timeout` de 240s do worker, e uma chamada lenta sem
teto proprio nao falha -- e cancelada pelo ARQ, que e o desfecho pior. Com
50s e uma retentativa, o pior caso e 100s por lote; a varredura faz no maximo
dois lotes por passagem, o que fecha em 200s e cabe nos 240s. Ver o
comentario de `job_timeout` em `workers/main.py`.
"""

from functools import lru_cache

from openai import APIStatusError, AsyncOpenAI

from mobia.app.config import ConfiguracaoInsegura, get_settings

TIMEOUT_SEGUNDOS = 50.0
MAX_TENTATIVAS = 1

# O embed da busca DO TURNO tem teto proprio, e a razao e a mesma da TEC-228 no
# cliente da Anthropic: os 50s acima com uma retentativa dao 100s por busca, e
# um turno pode buscar duas vezes (uma em cada chamada paga de `turno.py`) --
# 200s sozinhos contra um `job_timeout` de 240s. Era o MAIOR termo do orcamento
# do turno, e nao era da Anthropic.
#
# Os 50s nao mudam para quem indexa: la o lote e grande, a varredura tem o
# tempo dela e a retentativa vale o que custa. O que muda e so a consulta do
# turno, que manda UMA frase curta (ver `busca.py:374`).
#
# **ESTE NUMERO NAO FOI MEDIDO, e isso e dito aqui em vez de escondido.** A
# TEC-228 mediu a Anthropic contra a API de verdade; para o OpenAI nao ha chave
# nesta maquina, entao a sonda nao rodou. Os 10s sao o dobro do teto que a
# medicao deu para `count_tokens` -- a chamada de forma mais parecida que
# existe medida no projeto: ida-e-volta de rede com payload minusculo e sem
# geracao, 0,28s de pior caso. O dobro porque e outro provedor e nenhuma
# amostra o cobre. Quem conseguir a chave mede e corrige.
TETO_DA_CONSULTA_DO_TURNO = 10.0

# Zero pelo mesmo argumento que zerou o da Anthropic: a retentativa dobra o
# termo mais caro do orcamento, e a busca ja tem desfecho definido para
# "nao deu" -- `busca.py` cai no filtro sem vetor e o turno segue.
MAX_TENTATIVAS_DA_CONSULTA_DO_TURNO = 0

MAX_CARACTERES_DO_MOTIVO = 300


@lru_cache
def get_client() -> AsyncOpenAI:
    """Cliente unico do processo.

    Construido sob demanda e nao no import, pelo mesmo motivo do
    `infra/anthropic.py`: importar o modulo nao pode exigir credencial, senao
    a suite inteira passa a precisar de chave para colecionar testes que
    nunca chamam o provedor.
    """
    chave = get_settings().openai_api_key
    if not chave:
        raise ConfiguracaoInsegura(
            "OPENAI_API_KEY nao configurada. A indexacao vetorial do TEC-157 "
            "precisa dela; defina no .env ou no ambiente antes de subir o worker."
        )
    return AsyncOpenAI(api_key=chave, timeout=TIMEOUT_SEGUNDOS, max_retries=MAX_TENTATIVAS)


async def embedar(textos: list[str]) -> list[list[float]]:
    """Os vetores dos textos, na mesma ordem.

    Lote vazio nao chama o provedor: a varredura pode terminar uma passagem
    sem candidato pendente, e pagar uma requisicao por isso seria absurdo.

    A chamada com array e tudo-ou-nada: falha inteira ou volta inteira. Isso
    e o que permite a varredura retentar um lote na integra, sem estado
    parcial para conciliar.
    """
    if not textos:
        return []

    return await _embedar(textos, get_client(), TIMEOUT_SEGUNDOS)


async def embedar_do_turno(textos: list[str]) -> list[list[float]]:
    """O mesmo embed, com o teto e as tentativas do TURNO.

    Existe porque `embedar` e usado por dois donos com orcamentos opostos: a
    indexacao, que tem a varredura inteira e lotes grandes, e a busca do turno,
    que divide 240s com cinco chamadas pagas ao modelo (TEC-228). Um parametro
    opcional em `embedar` deixaria o default sendo o caro -- e quem esquecesse
    de passa-lo no turno voltaria a gastar 100s numa consulta de uma frase.
    """
    return await _embedar(
        textos,
        get_client().with_options(max_retries=MAX_TENTATIVAS_DA_CONSULTA_DO_TURNO),
        TETO_DA_CONSULTA_DO_TURNO,
    )


async def _embedar(textos: list[str], cliente: AsyncOpenAI, teto: float) -> list[list[float]]:
    settings = get_settings()
    resposta = await cliente.embeddings.create(
        model=settings.embedding_modelo,
        input=textos,
        dimensions=settings.embedding_dimensoes,
        timeout=teto,
    )
    # A API nao garante a ordem de `data`; `index` e o que amarra cada vetor
    # ao texto que o gerou.
    return [item.embedding for item in sorted(resposta.data, key=lambda item: item.index)]


def motivo_do_provedor(exc: BaseException) -> str | None:
    """O porque de um erro de protocolo do provedor, sem conteudo do lead.

    Mesma excecao deliberada que o `infra/anthropic.py` abre e pelo mesmo
    motivo: o corpo de erro de um `APIStatusError` e gerado pelo servidor, e
    nao carrega texto do lead. Para qualquer outra excecao, devolve None --
    `str(exc)` de excecao arbitraria pode carregar o que nao deve ir para log.

    **Ate a TEC-292 esta funcao tinha a mesma primeira linha e a mesma
    promessa do vizinho, mas nao a mesma garantia**: repassava `str(exc)[:300]` cru em vez
    de extrair campos do `body`. O SDK da OpenAI renderiza `str()` de
    `APIStatusError` como `Error code: 400 - <corpo inteiro>`, entao o texto
    que vazava era o mesmo corpo que esta funcao existe para nao logar -- no
    caso que motivou o conserto, o documento do imovel montado a partir do
    arquivo importado. Agora ela extrai `status_code`, `error.type` e
    `error.message` do `body`, como o `infra/anthropic.py` ja fazia.
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
    return resumo

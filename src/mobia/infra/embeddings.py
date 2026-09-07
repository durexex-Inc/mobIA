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

    settings = get_settings()
    resposta = await get_client().embeddings.create(
        model=settings.embedding_modelo,
        input=textos,
        dimensions=settings.embedding_dimensoes,
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
    """
    if not isinstance(exc, APIStatusError):
        return None
    return f"{exc.status_code}: {str(exc)[:MAX_CARACTERES_DO_MOTIVO]}"

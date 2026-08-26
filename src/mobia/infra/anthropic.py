from functools import lru_cache

from anthropic import AsyncAnthropic

from mobia.app.config import ConfiguracaoInsegura, get_settings

# O default do SDK e 10 minutos por requisicao, com retentativa interna --
# muito acima do `job_timeout` do worker (240s). Sem um teto proprio, uma
# chamada lenta nao falha: ela e cancelada pelo ARQ, e `CancelledError` e
# BaseException, que o `except Exception` de `process_message` nao pega (a
# linha nunca vira FAILED e a reserva de envio fica presa). Falha tipada e
# recuperavel; cancelamento nao e. 60s por tentativa, uma retentativa: no pior
# caso 120s por chamada, entao mesmo o turno com dobra (resumir + classificar)
# tem folga dentro dos 240s antes de o ARQ cancelar.
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

from functools import lru_cache

from anthropic import AsyncAnthropic

from mobia.app.config import ConfiguracaoInsegura, get_settings

# O default do SDK e 10 minutos por requisicao, com retentativa interna --
# muito acima do `job_timeout` do worker (240s). Sem um teto proprio, uma
# chamada lenta nao falha: ela e cancelada pelo ARQ, e `CancelledError` e
# BaseException, que o `except Exception` de `process_message` nao pega (a
# linha nunca vira FAILED e a reserva de envio fica presa). Falha tipada e
# recuperavel; cancelamento nao e. 60s por tentativa, uma retentativa: no pior
# caso 120s por chamada.
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

"""O prefixo cacheavel tem de passar o minimo do modelo configurado.

Prefixo curto de mais **nao cacheia e nao da erro**: a API devolve
`cache_creation_input_tokens: 0` e a chamada segue normal, so mais cara. Nao
ha excecao, nao ha log, nao ha nada -- e a economia some sem ninguem notar.

O minimo e por modelo e **nao e monotonico entre geracoes**, o que torna a
armadilha pior: trocar `modelo_agente` pode desligar o cache em silencio, e
`config.py` esta fora do filtro de `evals.yml`, entao nem o gate pago
dispararia. E a mesma classe de problema da TEC-249, onde `modelo_moderacao`
nao achava preco: configuracao que muda comportamento sem nada acusar.
"""

import pytest

from mobia.app.config import get_settings

# Medido com `messages.count_tokens` em 30/08/2026 (TEC-251): 457 do
# `SISTEMA_DO_AGENTE` mais ~1.195 do schema de `output_config`. Confirmado
# contra a API, que devolveu `cache_creation_input_tokens=1652` na primeira
# chamada e `cache_read_input_tokens=1652` na segunda.
#
# Nao e estimativa por `len(texto)//4`: essa conta erra o suficiente para
# cruzar um limiar de 1.024 sem avisar, que e exatamente o erro que este
# modulo existe para impedir.
PREFIXO_CACHEAVEL_EM_TOKENS = 1652

# Minimos publicados por modelo. NAO sao monotonicos entre geracoes -- o
# sonnet-5 exige o dobro do opus-5, e o haiku-4-5 exige oito vezes.
MINIMO_CACHEAVEL_POR_MODELO = {
    "claude-opus-5": 512,
    "claude-sonnet-5": 1024,
    "claude-haiku-4-5": 4096,
}


def _minimo_de(modelo: str) -> int | None:
    """Reduz sufixo de snapshot, como `custo_em_dolar` faz desde a TEC-249."""
    import re

    if modelo in MINIMO_CACHEAVEL_POR_MODELO:
        return MINIMO_CACHEAVEL_POR_MODELO[modelo]
    return MINIMO_CACHEAVEL_POR_MODELO.get(re.sub(r"-\d{8}$", "", modelo))


def test_o_prefixo_cacheavel_passa_o_minimo_do_modelo() -> None:
    """A guarda principal: o cache so existe se o prefixo passar o minimo.

    Com `claude-sonnet-5` a folga e de 628 tokens (1.652 contra 1.024). Se
    alguem trocar para um modelo de minimo maior -- `claude-haiku-4-5` exige
    4.096 --, o cache morre em silencio e a conta sobe sem nenhum sinal. Este
    assert e o sinal.
    """
    modelo = get_settings().modelo_agente
    minimo = _minimo_de(modelo)
    assert minimo is not None, (
        f"modelo {modelo!r} sem minimo cacheavel conhecido: acrescente a "
        f"MINIMO_CACHEAVEL_POR_MODELO antes de confiar no cache."
    )
    assert PREFIXO_CACHEAVEL_EM_TOKENS >= minimo, (
        f"prefixo de {PREFIXO_CACHEAVEL_EM_TOKENS} tokens contra minimo de "
        f"{minimo} do {modelo}: o cache NAO vai funcionar, e a API nao avisa. "
        f"Ou o prefixo cresce, ou o modelo muda, ou o `cache_control` sai "
        f"junto com a expectativa de economia."
    )


def test_o_modelo_configurado_tem_minimo_conhecido() -> None:
    """Irma do teste de preco da TEC-249, pela mesma razao.

    Um modelo fora desta tabela nao e necessariamente incacheavel -- e
    desconhecido. A diferenca importa: desconhecido vira suposicao, e a
    suposicao aqui custa dinheiro em silencio.
    """
    modelo = get_settings().modelo_agente
    assert _minimo_de(modelo) is not None


def test_o_system_vai_como_bloco_com_cache_control() -> None:
    """Sem o marcador, nada cacheia -- e o prefixo passar o minimo nao basta.

    Guarda a forma que `_chamar` monta, e nao so o tamanho: os dois tem de
    valer juntos, e cada um sem o outro produz a mesma conta cara.
    """
    import inspect

    from mobia.domain.agente.classificador import ClassificadorAnthropic

    fonte = inspect.getsource(ClassificadorAnthropic._chamar)
    assert '"cache_control": {"type": "ephemeral"}' in fonte
    assert '"type": "text", "text": system' in fonte


@pytest.mark.parametrize(
    ("modelo", "esperado"),
    [
        ("claude-sonnet-5", 1024),
        ("claude-opus-5", 512),
        ("claude-haiku-4-5", 4096),
        # Snapshot datado reduz para o modelo base, como na TEC-249.
        ("claude-haiku-4-5-20251001", 4096),
        ("modelo-que-nao-existe", None),
    ],
)
def test_reducao_de_modelo_para_minimo(modelo: str, esperado: int | None) -> None:
    assert _minimo_de(modelo) == esperado

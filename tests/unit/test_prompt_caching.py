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

# Medido com `messages.count_tokens`. Nao e estimativa por `len(texto)//4`:
# essa conta erra o suficiente para cruzar um limiar de 1.024 sem avisar, que
# e exatamente o erro que este modulo existe para impedir.
#
# 30/08/2026 (TEC-251): 1.652 -- 457 do `SISTEMA_DO_AGENTE` mais ~1.195 do
# schema. Confirmado contra a API, que devolveu `cache_creation=1652` na
# primeira chamada e `cache_read=1652` na segunda.
#
# 30/08/2026 (TEC-250): **1.716**. As tres regras novas do prompt somaram 64
# tokens. A TEC-251 registrou como lacuna conhecida que este numero e copiado
# e nao calculado -- que mudar o prompt o invalida e nada recalcula sozinho --
# e a card seguinte ja o invalidou. Ele continua copiado de proposito: o
# alternativo e uma chamada paga a `count_tokens` dentro da suite, que nao
# toca a rede. Quem mexer no prompt ou no schema re-mede e atualiza aqui.
#
# 08/09/2026 (TEC-265): a ordem de renderizacao do cache e
# `tools` -> `system` -> `messages` (`classificador.py`, comentario de
# `_chamar`): a partir desta card `tools=[FERRAMENTA_DE_BUSCA]` passou a
# entrar ANTES do `system` com `cache_control`, ou seja, DENTRO do prefixo
# cacheado -- nao depois dele. A remedicao com `messages.count_tokens` foi
# tentada nesta correcao e nao completou por falta de saldo na chave
# configurada (`Your credit balance is too low`); resolvida na TEC-141
# abaixo.
#
# 10/09/2026 (TEC-141): **2.351**, medido com `claude-sonnet-5` (rota 1: a
# API aceitou `output_config` em `messages.count_tokens`, sem precisar cair
# para uma chamada real `messages.create`/TEC-251). A chamada mediu o
# prefixo de producao INTEIRO, no mesmo formato que `_chamar`/`classificar`
# mandam: `tools=[FERRAMENTA_DE_BUSCA]` + `system=[{"type": "text", "text":
# SISTEMA_DO_AGENTE, "cache_control": {"type": "ephemeral"}}]` +
# `output_config={"format": {"type": "json_schema", "schema":
# _SCHEMA_COMPILADO}}` + `messages=[{"role": "user", "content": "x"}]` --
# devolveu `input_tokens=2358`. Uma segunda chamada so com o mesmo
# `messages` (sem tools/system/output_config) devolveu 7, e 2358 - 7 = 2351
# e o valor abaixo.
#
# O prefixo cacheavel de producao e `tools` + `system` + o schema de
# `output_config` -- os tres viajam sob o MESMO `cache_control` porque
# `_chamar` so marca o bloco `system`, e tudo que a API renderiza antes
# dele (`tools`, `output_config`) entra dentro do prefixo quente por
# ordem de renderizacao, nao so `tools` + `system`. Uma primeira medicao
# desta mesma card cobriu so `tools` + `system` e achou 1.128 -- um
# subconjunto estrito do prefixo real (faltava o schema, ~1.195 tokens
# pela TEC-251), nao uma medicao menor dele. Corrigido aqui antes do
# commit final.
#
# Esta card tambem trocou uma frase do `SISTEMA_DO_AGENTE` (ganhou "Nao
# negocie valor: e com o corretor.", perdeu ", de 0 a 1"), entao o numero
# muda de novo por causa do prompt, alem da correcao de escopo acima.
PREFIXO_CACHEAVEL_EM_TOKENS = 2351

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

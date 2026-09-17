"""O orcamento de tempo de um turno, somado onde ele e visivel inteiro. TEC-228.

Este arquivo existe porque nenhum modulo conhece a conta toda. `infra/anthropic.py`
sabe quanto custam as chamadas de modelo, `infra/embeddings.py` quanto custa o
embed da busca, `infra/moderacao.py` as duas pontas moderadas e
`domain/outbound/whatsapp.py` o POST -- e cada um deles ja teve, em algum
momento, um comentario que somava a propria parcela e a chamava de total.

Foi assim que `infra/anthropic.py` chegou a afirmar 360s quando o pior caso era
840s, e foi assim que a TEC-228 quase fechou uma conta de 162s sem notar os
200s do embed. A soma so e confiavel num lugar que enxerga os quatro.

A TEC-229 acrescentou as voltas do laco de `montar_contexto` a conta, e com
elas a soma passou de 202s para 327s contra um `job_timeout` de 240: os dois
testes que somam estao `xfail(strict=True)` ate a TEC-290 decidir como fechar.
Os dois que afirmam a derivacao continuam verdes, e sao o que impede este
arquivo de virar decoracao no meio-tempo.
"""

import pytest

from mobia.app.config import get_settings
from mobia.domain.moderacao.port import Direcao
from mobia.domain.outbound.whatsapp import TIMEOUT_SEGUNDOS as TETO_DO_POST_A_META
from mobia.infra.anthropic import (
    MAX_TENTATIVAS,
    TETO_DA_CLASSIFICACAO,
    TETO_DO_COUNT_TOKENS,
    TETO_DO_INVESTIDOR,
    TETO_DO_RESUMO,
    segundos_do_modelo_no_pior_turno,
)
from mobia.infra.embeddings import (
    MAX_TENTATIVAS_DA_CONSULTA_DO_TURNO,
    TETO_DA_CONSULTA_DO_TURNO,
)
from mobia.infra.moderacao import (
    MAX_TENTATIVAS_DA_MODERACAO,
    TIMEOUT_DA_MODERACAO_SEGUNDOS,
)
from mobia.workers.main import WorkerSettings

# Duas, e sao as mesmas duas fatias que `_pior_turno()` conta em dobro: a chamada
# 1 (`turno.py`) e a chamada 2 podem, cada uma, pedir a ferramenta de busca uma
# vez -- o teto de um round-trip por turno e da D4 da TEC-265, e
# `disable_parallel_tool_use` impede duas buscas na mesma resposta.
BUSCAS_POR_TURNO = 2


def _segundos_do_embed_no_pior_turno() -> float:
    return BUSCAS_POR_TURNO * TETO_DA_CONSULTA_DO_TURNO * (MAX_TENTATIVAS_DA_CONSULTA_DO_TURNO + 1)


def _segundos_da_moderacao_no_pior_turno() -> float:
    # Uma por direcao: entrada e saida. `len(Direcao)` e nao o literal 2, para
    # que uma terceira direcao entre na conta sozinha.
    return len(Direcao) * TIMEOUT_DA_MODERACAO_SEGUNDOS * (MAX_TENTATIVAS_DA_MODERACAO + 1)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TEC-229 corrigiu o grafo de chamadas e a conta deixou de fechar: 327s "
        "contra um job_timeout de 240. Fechar exige mexer na janela do sweeper, "
        "que e decisao de produto -- ver TEC-290. Estrito de proposito: quem "
        "fechar o orcamento ve isto virar XPASS e e obrigado a tirar a marca."
    ),
)
def test_o_pior_turno_cabe_no_job_timeout() -> None:
    """A soma dos quatro clientes externos contra o `job_timeout` -- hoje NAO cabe.

    **O que este teste protege e a RELACAO, nao os numeros.** Nenhum dos tetos
    esta escrito aqui: todos sao importados de quem os define, e o
    `job_timeout` vem do `WorkerSettings` de verdade. Por isso ficou
    `xfail(strict=True)` na TEC-229 em vez de reescrito com um numero maior --
    ver a razao no decorador acima. Enquanto durar o xfail, subir qualquer
    teto sem olhar para o orcamento nao produz sinal nenhum aqui: quem produz
    e a prosa do comentario de `job_timeout` em `workers/main.py`.

    Estourar o `job_timeout` nao e so custo: o ARQ cancela a corrotina, o turno
    inteiro e repago pelo sweeper e a entrega pode duplicar se o cancelamento
    cair depois de o POST ter chegado a Meta. Ver o comentario de `job_timeout`.
    """
    soma = (
        segundos_do_modelo_no_pior_turno()
        + _segundos_do_embed_no_pior_turno()
        + _segundos_da_moderacao_no_pior_turno()
        + TETO_DO_POST_A_META
    )

    assert soma < WorkerSettings.job_timeout, (
        f"o pior turno soma {soma}s contra um job_timeout de "
        f"{WorkerSettings.job_timeout}s -- ver o comentario de `job_timeout` "
        f"em `workers/main.py` para a conta inteira"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TEC-229 corrigiu o grafo de chamadas e a conta deixou de fechar: 327s "
        "contra um job_timeout de 240. Fechar exige mexer na janela do sweeper, "
        "que e decisao de produto -- ver TEC-290. Estrito de proposito: quem "
        "fechar o orcamento ve isto virar XPASS e e obrigado a tirar a marca."
    ),
)
def test_a_folga_paga_o_banco() -> None:
    """Caber nao basta: sobrar 1s seria caber e estourar na primeira consulta.

    O turno faz dezenas de idas ao banco fora dos clientes externos -- ler
    mensagens, montar contexto, gravar intencao, reservar a saida, commitar. A
    reserva de 30s nao e medida (ninguem mediu), e por isso e declarada em vez
    de derivada: a varredura de follow-ups reservou 20s para o banco de UM
    candidato pelo mesmo motivo e com a mesma honestidade.
    """
    soma = (
        segundos_do_modelo_no_pior_turno()
        + _segundos_do_embed_no_pior_turno()
        + _segundos_da_moderacao_no_pior_turno()
        + TETO_DO_POST_A_META
    )

    assert WorkerSettings.job_timeout - soma >= 30


def test_o_investidor_e_o_teto_mais_alto_do_turno() -> None:
    """A chamada mais cara e a que gera mais, e e ela que manda na folga.

    Nao e afirmacao sobre gosto: se um dia `classificar` passar o investidor,
    a ordem que `_pior_turno()` usa para escolher o pior par deixa de valer --
    o pior par e `classificar` com busca SEGUIDO do investidor com busca, e
    isso so e o pior porque as duas chamadas de investidor sao exclusivas
    entre si.
    """
    assert TETO_DO_INVESTIDOR > TETO_DA_CLASSIFICACAO


def test_o_pior_turno_segue_contexto_max_iteracoes(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Subir o teto de iteracoes da montagem tem de mover o pior caso.

    E o criterio de pronto que a TEC-229 existe para fechar. Ate ela,
    `_PIOR_TURNO` contava `resumir` e `count_tokens` uma vez cada: dobrar
    `contexto_max_iteracoes` nao mexia em numero nenhum, e o laco de
    `montar_contexto` -- que roda ate esse teto, com um `resumir` e uma
    contagem por volta -- ficava fora da conta.

    **Enquanto a TEC-290 nao fechar o orcamento, este e o unico teste verde
    que guarda a derivacao.** Os dois que somam estao `xfail`, entao subir um
    teto ou uma iteracao nao os torna vermelhos -- eles ja sao. Se este aqui
    for apagado junto com aquela card, a derivacao volta a poder ser trocada
    por constantes sem nada perceber.

    O delta e afirmado exato, e nao so "maior": uma iteracao a mais custa
    UMA dobra e UMA contagem. Afirmar `>` passaria tambem se a implementacao
    multiplicasse a fatia errada.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv("CONTEXTO_MAX_ITERACOES", str(get_settings().contexto_max_iteracoes + 1))
    get_settings.cache_clear()

    uma_volta_a_mais = (TETO_DO_RESUMO + TETO_DO_COUNT_TOKENS) * (MAX_TENTATIVAS + 1)
    assert segundos_do_modelo_no_pior_turno() - antes == uma_volta_a_mais


def test_o_pior_turno_segue_o_gatilho_de_regeneracao(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O termo do truncamento tambem e derivado, e cresce em log.

    `_truncar_ate_caber` corta a janela pela metade a cada volta, entao
    dobrar o gatilho acrescenta UMA contagem, nao o dobro delas. O teste
    afirma essa forma: se alguem trocar o `log2` por multiplicacao, a
    igualdade quebra.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv(
        "CONTEXTO_GATILHO_DE_REGENERACAO",
        str(get_settings().contexto_gatilho_de_regeneracao * 2),
    )
    get_settings.cache_clear()

    um_corte_a_mais = TETO_DO_COUNT_TOKENS * (MAX_TENTATIVAS + 1)
    assert segundos_do_modelo_no_pior_turno() - antes == um_corte_a_mais

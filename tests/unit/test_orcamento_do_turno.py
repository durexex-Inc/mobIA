"""O orcamento de tempo de um turno, somado onde ele e visivel inteiro. TEC-228.

Este arquivo existe porque nenhum modulo conhece a conta toda. `infra/anthropic.py`
sabe quanto custam as chamadas de modelo, `infra/embeddings.py` quanto custa o
embed da busca, `infra/moderacao.py` as duas pontas moderadas e
`domain/outbound/whatsapp.py` o POST -- e cada um deles ja teve, em algum
momento, um comentario que somava a propria parcela e a chamava de total.

Foi assim que `infra/anthropic.py` chegou a afirmar 360s quando o pior caso era
840s, e foi assim que a TEC-228 quase fechou uma conta de 162s sem notar os
200s do embed. A soma so e confiavel num lugar que enxerga os quatro.
"""

from mobia.domain.moderacao.port import Direcao
from mobia.domain.outbound.whatsapp import TIMEOUT_SEGUNDOS as TETO_DO_POST_A_META
from mobia.infra.anthropic import (
    TETO_DA_CLASSIFICACAO,
    TETO_DO_INVESTIDOR,
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

# Duas, e sao as mesmas duas fatias que `_PIOR_TURNO` conta em dobro: a chamada
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


def test_o_pior_turno_cabe_no_job_timeout() -> None:
    """A soma dos quatro clientes externos cabe no `job_timeout`, com folga.

    **O que este teste protege e a RELACAO, nao os numeros.** Nenhum dos tetos
    esta escrito aqui: todos sao importados de quem os define, e o
    `job_timeout` vem do `WorkerSettings` de verdade. Subir qualquer teto sem
    olhar para o orcamento fica vermelho aqui, que e a unica coisa que impede o
    estado que a TEC-228 encontrou -- um comentario afirmando que a conta
    fechava enquanto ela estourava por 600s.

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
    a ordem que `_PIOR_TURNO` usa para escolher o pior par deixa de valer -- o
    pior par e `classificar` com busca SEGUIDO do investidor com busca, e isso
    so e o pior porque as duas chamadas de investidor sao exclusivas entre si.
    """
    assert TETO_DO_INVESTIDOR > TETO_DA_CLASSIFICACAO

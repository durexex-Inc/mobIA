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
testes que somam ficaram `xfail(strict=True)` ate a TEC-290 decidir como
fechar. A TEC-290 fechou com um deadline agregado para a fase de montagem, que
tira do laco a dependencia de `contexto_max_iteracoes` e do gatilho de
regeneracao -- por isso nenhum teste deste arquivo e mais `xfail`, e quem
guarda a derivacao agora sao os dois testes que afirmam que aqueles dois nao
movem mais o pior caso (`..._nao_cresce_mais_com_...`) mais o que afirma que
quem move e o deadline (`..._segue_o_deadline_da_montagem`).
"""

import pytest

import mobia.infra.anthropic as anthropic
from mobia.app.config import get_settings
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


def _soma_do_pior_turno() -> float:
    return (
        segundos_do_modelo_no_pior_turno()
        + _segundos_do_embed_no_pior_turno()
        + _segundos_da_moderacao_no_pior_turno()
        + TETO_DO_POST_A_META
    )


def test_o_pior_turno_cabe_no_job_timeout() -> None:
    """A soma dos quatro clientes externos contra o `job_timeout` -- hoje cabe.

    **O que este teste protege e a RELACAO, nao os numeros.** Nenhum dos tetos
    esta escrito aqui: todos sao importados de quem os define, e o
    `job_timeout` vem do `WorkerSettings` de verdade.

    Estourar o `job_timeout` nao e so custo: o ARQ cancela a corrotina, o turno
    inteiro e repago pelo sweeper e a entrega pode duplicar se o cancelamento
    cair depois de o POST ter chegado a Meta. Ver o comentario de `job_timeout`.
    """
    soma = _soma_do_pior_turno()

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
    soma = _soma_do_pior_turno()

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


def test_o_pior_turno_nao_cresce_mais_com_contexto_max_iteracoes(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Este teste afirmava o CONTRARIO ate a TEC-290, e a inversao e o entregavel.

    Ate aqui, `_pior_turno` somava uma dobra e uma contagem por volta do laco
    de `montar_contexto`, entao subir o teto de iteracoes movia o pior caso --
    e era isso que impedia a conta de fechar, porque ela crescia com uma
    configuracao que ninguem lia pensando em orcamento.

    Com o deadline agregado, a fase inteira custa o relogio dela, quantas
    voltas der. Apagar este teste em vez de inverte-lo deixaria a
    propriedade que a card comprou sem nada guardando.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv("CONTEXTO_MAX_ITERACOES", str(get_settings().contexto_max_iteracoes + 1))
    get_settings.cache_clear()

    assert segundos_do_modelo_no_pior_turno() == antes


def test_o_pior_turno_nao_cresce_mais_com_o_gatilho_de_regeneracao(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Mesma inversao, pelo outro caminho.

    O gatilho governava o termo `log2` das contagens de `_truncar_ate_caber`.
    O truncamento continua existindo e continua contando -- so que agora
    dentro do relogio da fase, e nao somado por fora dele.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv(
        "CONTEXTO_GATILHO_DE_REGENERACAO",
        str(get_settings().contexto_gatilho_de_regeneracao * 2),
    )
    get_settings.cache_clear()

    assert segundos_do_modelo_no_pior_turno() == antes


def test_o_deadline_da_montagem_entra_uma_vez_e_nao_por_tentativa(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O deadline e relogio de fase; as outras fatias sao teto por requisicao.

    Uma retentativa repete uma REQUISICAO dentro da fase, e a fase ja esta
    limitada pelo relogio -- multiplicar o deadline por tentativa contaria
    duas vezes o que o relogio conta uma.

    Com `MAX_TENTATIVAS = 0` a diferenca e invisivel, e e por isso que este
    teste mexe na constante: sem isso ele passaria com a implementacao errada.
    """
    deadline = get_settings().contexto_deadline_de_montagem_segundos
    sem_retentativa = segundos_do_modelo_no_pior_turno()

    monkeypatch.setattr(anthropic, "MAX_TENTATIVAS", 1)

    assert segundos_do_modelo_no_pior_turno() == (sem_retentativa - deadline) * 2 + deadline


def test_o_pior_turno_segue_o_deadline_da_montagem(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """A derivacao nao sumiu, mudou de dono: quem move o pior caso agora e o deadline.

    Sem este teste, a inversao dos dois acima deixaria `_pior_turno` livre
    para voltar a ser constante -- que e exatamente o que a TEC-229 tinha
    acabado de impedir.
    """
    antes = segundos_do_modelo_no_pior_turno()

    monkeypatch.setenv(
        "CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS",
        str(get_settings().contexto_deadline_de_montagem_segundos + 10),
    )
    get_settings.cache_clear()

    assert segundos_do_modelo_no_pior_turno() - antes == 10

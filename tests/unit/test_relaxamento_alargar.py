"""As formas puras do relaxamento da RN-09.3.

TEC-160. Basename distinto de tudo em `tests/integration/`.
"""

from mobia.domain.catalogo.enums import EstadoDoRelaxamento, Operacao
from mobia.domain.catalogo.schemas import FiltroDeBusca, ResultadoDaBusca


def test_o_filtro_nasce_nao_relaxado() -> None:
    """D2: o campo existe e o default e o passe duro."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA)

    assert filtro.relaxado is False


def test_o_resultado_nasce_sem_relaxamento() -> None:
    """D6: `buscar` nunca afirma relaxamento -- ela e um passe."""
    resultado = ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)

    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE


def test_os_tres_estados_sao_distintos() -> None:
    """Um booleano colapsaria os dois ultimos, e a regra 4 da card precisa
    dos tres separados: "nao relaxei" e "relaxei e nao achei" pedem mensagens
    diferentes ao lead."""
    assert len(set(EstadoDoRelaxamento)) == 3


def test_o_resultado_diz_quais_dimensoes_alargou() -> None:
    """D11. O aviso precisa saber EM QUE ampliou, e o estado nao carrega isso:
    `APLICADO` vale tanto para "so preco" quanto para "preco e bairro"."""
    resultado = ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)

    assert resultado.relaxou_preco is False
    assert resultado.relaxou_bairro is False

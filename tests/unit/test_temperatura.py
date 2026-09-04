"""A temperatura derivada do score, e o forcamento que ignora a faixa.

TEC-151, RN-06.2 e RN-06.3. Sem banco: a funcao e pura.
"""

import pytest

from mobia.domain.context.score import Score
from mobia.domain.context.temperatura import (
    CORTE_MORNO,
    CORTE_QUENTE,
    Temperatura,
    temperatura_de,
)


def score(total: int) -> Score:
    """Um Score com o total pedido, todo no engajamento.

    Qual fator carrega o numero nao importa para esta funcao -- ela le so
    `.total` --, e concentrar num fator deixa o teste legivel. Os pesos reais
    de cada fator sao assunto de `test_score.py`.
    """
    return Score(completude=0, urgencia=0, catalogo=0, engajamento=total, capacidade=0)


@pytest.mark.parametrize(
    ("total", "esperada"),
    [
        (85, Temperatura.QUENTE),
        (70, Temperatura.QUENTE),
        (69, Temperatura.MORNO),
        (40, Temperatura.MORNO),
        (39, Temperatura.FRIO),
    ],
)
def test_a_faixa_da_rn_06_2(total: int, esperada: Temperatura) -> None:
    """A tabela do criterio de aceite da card, literal."""
    assert temperatura_de(score(total), qualificado=True, forcada=False) is esperada


def test_o_lead_nao_qualificado_topa_em_morno() -> None:
    """A emenda E-01 a RN-06.2, e a divergencia que a TEC-150 declarou.

    Um lead com `intencao = None`, resto completo, IMEDIATA, forma de
    pagamento declarada e engajamento soma 70 com `esta_qualificado` False.
    Sem o teto ele chegaria QUENTE e faria o telefone do corretor tocar
    (RN-06.5) por um lead cuja intencao o sistema nunca determinou.
    """
    assert temperatura_de(score(70), qualificado=False, forcada=False) is Temperatura.MORNO


@pytest.mark.parametrize("total", [39, 40, 69])
def test_o_teto_so_morde_em_quente(total: int) -> None:
    """Abaixo de 70 a qualificacao nao muda nada: quem ja era MORNO ou FRIO
    continua igual. O teto impede a passagem para QUENTE, e mais nada."""
    assert temperatura_de(score(total), qualificado=False, forcada=False) is temperatura_de(
        score(total), qualificado=True, forcada=False
    )


def test_o_forcamento_ignora_o_score() -> None:
    """O cenario 2 da card: score 35, temperatura QUENTE."""
    assert temperatura_de(score(35), qualificado=False, forcada=True) is Temperatura.QUENTE


def test_o_forcamento_ignora_o_teto_de_qualificacao() -> None:
    """A RN-06.3 diz "independentemente do score", e quem pede visita esta
    pronto para agir mesmo sem os quatro obrigatorios. Um VENDER_IMOVEL que
    pede para falar com corretor chega QUENTE -- o que e exatamente o que a
    RN-03.4 ja quer para ele."""
    assert temperatura_de(score(0), qualificado=False, forcada=True) is Temperatura.QUENTE


def test_os_dois_flags_sao_keyword_only() -> None:
    """Dois `bool` adjacentes: trocar a ordem nao levanta, nao e erro de tipo,
    nao e visivel ao mypy, e devolveria temperatura errada em silencio. Mesma
    razao pela qual as duas contagens de `calcular_score` sao keyword-only."""
    with pytest.raises(TypeError):
        temperatura_de(score(0), False, True)  # type: ignore[misc]


def test_os_cortes_sao_os_do_srs() -> None:
    """A RN-06.2 corta em 70 e 40, e a decisao de 02/09/2026 foi NAO recalibrar
    para o teto real do score (75 sem catalogo). Se estes numeros mudarem, foi
    decisao de alguem -- nao deixe passar em silencio."""
    assert (CORTE_QUENTE, CORTE_MORNO) == (70, 40)

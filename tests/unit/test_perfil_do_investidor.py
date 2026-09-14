"""O perfil do investidor da RN-07.2. TEC-153, D4."""

import pytest

from mobia.domain.agente.investidor import Horizonte, PerfilInvestidor, RetornoEsperadoTipo
from mobia.domain.context.qualificacao import perfil_de

RENDA, VALORIZACAO, MISTO = (
    PerfilInvestidor.RENDA,
    PerfilInvestidor.VALORIZACAO,
    PerfilInvestidor.MISTO,
)


@pytest.mark.parametrize(
    ("tipo", "horizonte", "esperado"),
    [
        (RetornoEsperadoTipo.ALUGUEL, Horizonte.CURTO, MISTO),
        (RetornoEsperadoTipo.ALUGUEL, Horizonte.MEDIO, RENDA),
        (RetornoEsperadoTipo.ALUGUEL, Horizonte.LONGO, RENDA),
        (RetornoEsperadoTipo.REVENDA, Horizonte.CURTO, VALORIZACAO),
        (RetornoEsperadoTipo.REVENDA, Horizonte.MEDIO, VALORIZACAO),
        (RetornoEsperadoTipo.REVENDA, Horizonte.LONGO, MISTO),
        (RetornoEsperadoTipo.AMBOS, Horizonte.CURTO, MISTO),
        (RetornoEsperadoTipo.AMBOS, Horizonte.MEDIO, MISTO),
        (RetornoEsperadoTipo.AMBOS, Horizonte.LONGO, MISTO),
    ],
)
def test_a_tabela_do_perfil(tipo, horizonte, esperado) -> None:
    assert perfil_de(horizonte, tipo) is esperado


def test_o_cenario_do_gherkin_e_renda() -> None:
    """ "horizonte longo e expectativa de aluguel recorrente" -> RENDA."""
    assert perfil_de(Horizonte.LONGO, RetornoEsperadoTipo.ALUGUEL) is RENDA


def test_as_diagonais_discordantes_sao_misto() -> None:
    """ "quero aluguel mas saio em um ano" e "quero revender mas fico dez anos"
    sao sinais que se contradizem. Escolher um deles seria chute."""
    assert perfil_de(Horizonte.CURTO, RetornoEsperadoTipo.ALUGUEL) is MISTO
    assert perfil_de(Horizonte.LONGO, RetornoEsperadoTipo.REVENDA) is MISTO


@pytest.mark.parametrize(
    ("horizonte", "tipo"),
    [
        (None, RetornoEsperadoTipo.ALUGUEL),
        (Horizonte.LONGO, None),
        (None, None),
    ],
)
def test_sem_um_dos_dois_o_perfil_e_none_e_nao_misto(horizonte, tipo) -> None:
    """NULL e "ainda nao sei"; MISTO e "sei, e e misto". Colapsar os dois faria
    a TEC-154 exibir indicador de perfil para quem nunca respondeu."""
    assert perfil_de(horizonte, tipo) is None

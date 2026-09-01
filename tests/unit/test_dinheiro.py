from decimal import Decimal

import pytest

from mobia.domain.agente.dinheiro import _Valor, _valor_de


@pytest.mark.parametrize(
    ("texto", "centavos", "tinha_marcador"),
    [
        ("500 mil", 50_000_000, True),
        ("500k", 50_000_000, True),
        ("R$ 500.000", 50_000_000, False),
        ("uns 500 mil", 50_000_000, True),
        ("1,5 milhao", 150_000_000, True),
        ("2 milhoes", 200_000_000, True),
        ("500", 50_000, False),
        ("cerca de 800 mil reais", 80_000_000, True),
    ],
)
def test_valor_unico(texto, centavos, tinha_marcador):
    assert _valor_de(texto) == _Valor(centavos=centavos, tinha_marcador=tinha_marcador)


@pytest.mark.parametrize("texto", ["", "o que der", "quinhentos mil", "sei la"])
def test_sem_numero_devolve_none(texto):
    """A gramatica e lista fixa: numero por extenso nao e resolvido, e isso e
    lacuna declarada da spec, nao bug."""
    assert _valor_de(texto) is None


def test_ponto_e_milhar_virgula_e_decimal():
    assert _valor_de("500.000").centavos == 50_000_000
    assert _valor_de("1,5").centavos == 150


def test_ruido_r_dollar_com_sem_espaco():
    """Verifica que a limpeza de R$ funciona com e sem espaco apos o simbolo."""
    # "R$ " com espaco entre simbolo e numero
    com_espaco = _valor_de("R$ 500.000")
    assert com_espaco is not None
    assert com_espaco.centavos == 50_000_000

    # "R$" sem espaco
    sem_espaco = _valor_de("R$500.000")
    assert sem_espaco is not None
    assert sem_espaco.centavos == 50_000_000


@pytest.mark.parametrize(
    ("texto", "fator_esperado"),
    [
        # Marcador "mil"
        ("500 mil", Decimal(1_000)),
        ("500k", Decimal(1_000)),
        # Marcador "milhao"
        ("1,5 milhao", Decimal(1_000_000)),
        ("2 milhoes", Decimal(1_000_000)),
        # Sem marcador
        ("500", Decimal(1)),
        ("R$ 500.000", Decimal(1)),
    ],
)
def test_fator_rastreia_multiplicador(texto, fator_esperado):
    """Verifica que fator rastreia o multiplicador de grandeza aplicado."""
    resultado = _valor_de(texto)
    assert resultado is not None
    assert resultado.fator == fator_esperado

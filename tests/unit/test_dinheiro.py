from decimal import Decimal

import pytest

from mobia.domain.agente.dinheiro import _RUIDO, _Valor, _valor_de


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


def test_ruido_stripping_direto():
    """Testa remocao de ruido diretamente no regex, nao em valor final.

    _RUIDO e privado, mas testar a remocao direto e necessario porque o caminho
    publico (_valor_de) e insensivel ao ruido quando o numero esta presente:
    _NUMERO.search encontra a faixa de digitos independente de lixo na frente.
    Isto era o problema original: "R$ 500.000" nao limpava o "R$ " e o teste
    passava mesmo assim porque _NUMERO achava "500.000". O teste aqui valida
    o regex diretamente, forçando a falha se a limpeza regredir.
    """
    # Forma com espaco (era quebrada, precisava da fix r\$\s*)
    resultado_com_espaco = _RUIDO.sub(" ", "r$ 500.000".casefold())
    assert "r$" not in resultado_com_espaco

    # Forma sem espaco (ja funcionava, precisa nao regredir)
    resultado_sem_espaco = _RUIDO.sub(" ", "r$500".casefold())
    assert "r$" not in resultado_sem_espaco

    # Guarda: palavras inteiras com \b nao sao comidas (reaisimo, algumas, etc)
    assert _RUIDO.sub(" ", "reaisimo") == "reaisimo"
    assert _RUIDO.sub(" ", "algumas") == "algumas"


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

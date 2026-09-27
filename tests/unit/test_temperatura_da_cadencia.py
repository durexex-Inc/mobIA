"""TEC-385: a regua de reengajamento nao sente a penalidade de no-show."""

import pytest

from mobia.domain.context.score import Score
from mobia.domain.context.temperatura import (
    Temperatura,
    temperatura_da_cadencia_de,
    temperatura_de,
)


def _score(bruto: int, penalidade: int) -> Score:
    return Score(
        completude=bruto, urgencia=0, catalogo=0, engajamento=0, capacidade=0, penalidade=penalidade
    )


@pytest.mark.parametrize(
    ("bruto", "viva", "cadencia"),
    [
        # Os dois exemplos da TEC-375: 72 -> 57 e 50 -> 35.
        (72, Temperatura.MORNO, Temperatura.QUENTE),
        (50, Temperatura.FRIO, Temperatura.MORNO),
        (30, Temperatura.FRIO, Temperatura.FRIO),
    ],
)
def test_so_a_penalidade_sai_da_conta(bruto: int, viva: Temperatura, cadencia: Temperatura) -> None:
    score = _score(bruto, penalidade=15)

    assert temperatura_de(score, qualificado=True, forcada=False) is viva
    assert temperatura_da_cadencia_de(score, qualificado=True, forcada=False) is cadencia


def test_o_teto_de_qualificado_vale_para_a_cadencia() -> None:
    """O que o lead nao respondeu continua segurando o QUENTE: faltar nao
    desfaz nem acrescenta sinal nenhum dele."""
    score = _score(72, penalidade=15)

    assert temperatura_da_cadencia_de(score, qualificado=False, forcada=False) is Temperatura.MORNO


def test_o_forcamento_vale_para_a_cadencia() -> None:
    score = _score(10, penalidade=15)

    assert temperatura_da_cadencia_de(score, qualificado=False, forcada=True) is Temperatura.QUENTE


@pytest.mark.parametrize("bruto", [0, 39, 40, 69, 70, 95])
def test_sem_penalidade_as_duas_sao_a_mesma(bruto: int) -> None:
    score = _score(bruto, penalidade=0)

    for qualificado in (True, False):
        assert temperatura_da_cadencia_de(
            score, qualificado=qualificado, forcada=False
        ) is temperatura_de(score, qualificado=qualificado, forcada=False)

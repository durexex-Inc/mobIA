import pytest

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.score import Score, calcular_score


def _estado(**campos) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste tirar."""
    base = {
        "channel": "whatsapp",
        "conversation_key": "5511999999999",
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 60_000_000,
        "regiao": "zona sul",
        "urgencia": Urgencia.IMEDIATA.value,
    }
    return LeadQualification(**{**base, **campos})


def test_estado_inexistente_zera_tudo():
    obtido = calcular_score(None)
    assert obtido == Score(completude=0, urgencia=0, catalogo=0, engajamento=0, capacidade=0)
    assert obtido.total == 0


@pytest.mark.parametrize(
    ("preenchidos", "pontos"),
    [(4, 20), (3, 15), (2, 10), (1, 5), (0, 0)],
)
def test_completude_e_cinco_por_campo(preenchidos, pontos):
    ausentes = ["urgencia", "regiao", "faixa_preco_max_centavos", "intencao"][: 4 - preenchidos]
    obtido = calcular_score(_estado(**dict.fromkeys(ausentes)))
    assert obtido.completude == pontos


@pytest.mark.parametrize(
    ("urgencia", "pontos"),
    [
        (Urgencia.IMEDIATA, 25),
        (Urgencia.ATE_3_MESES, 15),
        (Urgencia.ATE_6_MESES, 8),
        (Urgencia.SEM_PRESSA, 0),
    ],
)
def test_urgencia_por_faixa(urgencia, pontos):
    assert calcular_score(_estado(urgencia=urgencia.value)).urgencia == pontos


def test_urgencia_ausente_nao_pontua():
    assert calcular_score(_estado(urgencia=None)).urgencia == 0


@pytest.mark.parametrize(
    ("imoveis", "pontos"),
    [(9, 20), (5, 20), (4, 12), (1, 12), (0, 0)],
)
def test_catalogo_por_faixa(imoveis, pontos):
    assert calcular_score(_estado(), imoveis_compativeis=imoveis).catalogo == pontos


def test_catalogo_e_zero_por_default():
    """Enquanto a TEC-158 nao existir, ninguem passa o parametro e o fator
    contribui zero -- que e o que a card prescreve."""
    assert calcular_score(_estado()).catalogo == 0


@pytest.mark.parametrize(
    ("mensagens", "pontos"),
    [(10, 15), (6, 15), (5, 10), (3, 10), (2, 5), (1, 5), (0, 0)],
)
def test_engajamento_por_faixa(mensagens, pontos):
    assert calcular_score(_estado(), mensagens_do_lead=mensagens).engajamento == pontos


@pytest.mark.parametrize(
    ("forma", "pontos"),
    [
        (FormaPagamento.A_VISTA, 15),
        (FormaPagamento.FINANCIAMENTO, 12),
        (FormaPagamento.CONSORCIO, 12),
        (FormaPagamento.FGTS, 12),
        (FormaPagamento.INDEFINIDA, 6),
    ],
)
def test_capacidade_por_forma_de_pagamento(forma, pontos):
    assert calcular_score(_estado(forma_pagamento=forma.value)).capacidade == pontos


def test_capacidade_ausente_vale_a_avaliar():
    """Coluna nula e INDEFINIDA significam a mesma coisa para este fator: o
    lead nao disse como pagaria, entao e "a avaliar"."""
    assert calcular_score(_estado(forma_pagamento=None)).capacidade == 6

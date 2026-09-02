import pytest

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import CAMPOS_OBRIGATORIOS
from mobia.domain.context.score import PONTOS_POR_CAMPO_OBRIGATORIO, Score, calcular_score


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


def test_o_cenario_de_aceite_da_card():
    """Quatro obrigatorios, prazo de 20 dias, seis imoveis compativeis,
    pagamento a vista -> pelo menos 70.

    Com catalogo, como a card escreveu o cenario.
    """
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=4,
        imoveis_compativeis=6,
    )
    assert obtido.total >= 70


def test_o_mesmo_cenario_sem_catalogo_ainda_fecha():
    """A diferenca que a TEC-158 fara, pinada desde ja. Sem o catalogo o
    mesmo lead perde 20 pontos e ainda precisa alcancar 70 -- e o que forcou
    a calibragem das faixas de engajamento."""
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=4,
    )
    assert obtido.total >= 70


def test_a_completude_maxima_acompanha_a_lista_de_obrigatorios():
    """Impede a divergencia que a TEC-146 gastou uma card consertando: se
    alguem acrescentar um quinto obrigatorio na RN-05.3, este teste quebra e
    obriga a decidir o peso, em vez de o score simplesmente pontuar a menos
    em silencio."""
    maximo = calcular_score(_estado(), mensagens_do_lead=99, imoveis_compativeis=99).completude
    assert maximo == len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO


def test_o_total_e_a_soma_dos_cinco():
    """Quebraria se um fator fosse esquecido na soma -- que e o defeito mais
    facil de introduzir num dataclass que cresce."""
    s = calcular_score(
        _estado(forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=6,
        imoveis_compativeis=6,
    )
    assert s.total == s.completude + s.urgencia + s.catalogo + s.engajamento + s.capacidade


def test_o_teto_com_catalogo_e_95():
    """Nao 100. Ver D3: 5 pontos por campo com quatro obrigatorios da 20, e o
    peso 25 da tabela da RN-06.1 nao fecha com a lista da RN-05.3."""
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=99,
        imoveis_compativeis=99,
    )
    assert obtido.total == 95


def test_o_teto_sem_catalogo_e_75():
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=99,
    )
    assert obtido.total == 75


def test_o_calculo_e_deterministico():
    """A igualdade do dataclass compara os cinco fatores, nao so o total --
    entao dois calculos que somassem igual por caminhos diferentes seriam
    pegos aqui."""
    estado = _estado(forma_pagamento=FormaPagamento.FINANCIAMENTO.value)
    assert calcular_score(estado, 4, 3) == calcular_score(estado, 4, 3)


def test_nenhum_fator_e_negativo():
    """Contagem negativa nao e alcancavel por chamador nenhum, mas um peso
    trocado por engano poderia produzi-la, e um score negativo passaria
    despercebido numa fila ordenada."""
    s = calcular_score(_estado(), mensagens_do_lead=0, imoveis_compativeis=0)
    assert min(s.completude, s.urgencia, s.catalogo, s.engajamento, s.capacidade) >= 0

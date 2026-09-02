import pytest

from mobia.domain.agente.schemas import FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import CAMPOS_OBRIGATORIOS
from mobia.domain.context.score import (
    _PONTOS_POR_CAPACIDADE,
    _PONTOS_POR_URGENCIA,
    PONTOS_POR_CAMPO_OBRIGATORIO,
    Score,
    calcular_score,
)


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
    [(10, 15), (6, 15), (5, 10), (3, 10), (2, 10), (1, 10), (0, 0)],
)
def test_engajamento_por_faixa(mensagens, pontos):
    """Tres faixas, e as duas bordas pinadas: 5/6 separa 10 de 15, e 0/1
    separa nao falar de falar. Nao ha degrau em 3 -- ver a docstring de
    `_pontos_do_engajamento`."""
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
    """Documenta o cenario que a card escreveu, literal: quatro obrigatorios,
    prazo de 20 dias, seis imoveis compativeis, pagamento a vista -> >=70.

    O `>=70` sozinho e frouxo aqui: o cenario COM catalogo da 90, vinte
    pontos de folga, e nenhuma mutacao de constante o derrubaria. O segundo
    assert e o que faz este teste poder falhar; o primeiro e o criterio da
    card, mantido porque e o que a card diz. Quem pina a diferenca que a
    TEC-158 fara sao os dois testes de teto, e nao este.
    """
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=4,
        imoveis_compativeis=6,
    )
    assert obtido.total >= 70
    assert obtido.total == 90


@pytest.mark.parametrize("mensagens", [1, 2, 3, 5, 6, 99])
def test_o_cenario_de_aceite_sem_catalogo_fecha_em_qualquer_contagem(mensagens):
    """Sem catalogo o mesmo lead perde 20 pontos e ainda precisa alcancar 70,
    e precisa alcancar **em qualquer contagem de mensagens >=1**.

    A versao anterior deste teste fixava `mensagens_do_lead=4` e afirmava o
    criterio de aceite sob exatamente a premissa usada para derivar as
    faixas -- circular, e por isso nao pegou que o lead que diz tudo numa
    unica mensagem somava 65 e reprovava o criterio da propria card. O caso
    `mensagens=1` e o que estava vermelho antes da mudanca de faixas, e e o
    que trava a calibragem agora: baixar a faixa de baixo para 5 deixa quatro
    destes casos vermelhos.
    """
    obtido = calcular_score(
        _estado(urgencia=Urgencia.IMEDIATA.value, forma_pagamento=FormaPagamento.A_VISTA.value),
        mensagens_do_lead=mensagens,
    )
    assert obtido.total >= 70


def test_a_completude_maxima_acompanha_a_lista_de_obrigatorios():
    """Impede a divergencia que a TEC-146 gastou uma card consertando: se
    alguem acrescentar um quinto obrigatorio na RN-05.3, este teste quebra e
    obriga a decidir o peso, em vez de o score simplesmente pontuar a menos
    em silencio."""
    maximo = calcular_score(_estado(), mensagens_do_lead=99, imoveis_compativeis=99).completude
    assert maximo == len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO


def test_o_mapa_de_urgencia_cobre_o_enum():
    """Um membro novo em `Urgencia` -- operacao que as docstrings de `Intencao`
    e `TipoImovel` tratam como desenhada -- cairia no default do `.get` e
    pontuaria 0, identico a `SEM_PRESSA`, colapsando em silencio um fator de
    25 pontos com toda a suite verde.

    E a mesma defesa que `test_a_completude_maxima_acompanha_a_lista_de_obrigatorios`
    da a `CAMPOS_OBRIGATORIOS`, aplicada a segunda das tres acoplagens deste
    modulo com um vocabulario que mora fora dele.
    """
    assert set(_PONTOS_POR_URGENCIA) == {membro.value for membro in Urgencia}


def test_o_mapa_de_capacidade_cobre_o_enum():
    """Um membro novo em `FormaPagamento` receberia em silencio os 6 de "a
    avaliar", que e o default reservado a coluna nula -- e um caminho de
    pagamento definido valeria menos que dizer "ainda nao decidi"."""
    assert set(_PONTOS_POR_CAPACIDADE) == {membro.value for membro in FormaPagamento}


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
    """Duas chamadas com o mesmo estado dao o mesmo `Score`.

    Vale dizer o que isto pega, que e estreito: mutacao de `estado` pela
    propria funcao, e qualquer impureza introduzida depois -- relogio,
    aleatorio, leitura de fora. Nao compara fatores contra total, porque uma
    chamada comparada consigo mesma nao pode fazer isso; quem faz e
    `test_o_total_e_a_soma_dos_cinco`. Nenhuma mutacao de constante derruba
    este teste: e guarda prospectiva, declarada como tal.
    """
    estado = _estado(forma_pagamento=FormaPagamento.FINANCIAMENTO.value)
    antes = calcular_score(estado, mensagens_do_lead=4, imoveis_compativeis=3)
    assert antes == calcular_score(estado, mensagens_do_lead=4, imoveis_compativeis=3)


def test_nenhum_fator_e_negativo():
    """Um peso digitado com o sinal trocado deixa este teste vermelho: mutar
    `_PONTOS_SEM_FORMA_DE_PAGAMENTO` para -6 basta. Contagem negativa em si
    nao e alcancavel por chamador nenhum, porque as faixas usam `>=`.

    O que ele NAO faz e falhar sozinho: toda mutacao que o mata mata tambem
    um teste de faixa, que aponta direto para a constante errada. Ele nao
    acrescenta poder de deteccao sobre a suite -- documenta a propriedade
    "nenhum fator e negativo" no unico lugar onde ela e verificavel.
    """
    s = calcular_score(_estado(), mensagens_do_lead=0, imoveis_compativeis=0)
    assert min(s.completude, s.urgencia, s.catalogo, s.engajamento, s.capacidade) >= 0

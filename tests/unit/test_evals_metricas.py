from decimal import Decimal

import pytest

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.metricas import (
    Classificacao,
    Faixa,
    acuracia_de_intencao,
    acuracia_efetiva,
    bloqueia,
    erros,
    faixa_de,
    matriz_de_confusao,
    resumo_de_confianca,
    sem_mecanismo,
)

# Acima do limiar: a intencao efetiva e o proprio palpite, entao a confianca
# sai do caminho e o teste mede so o que quer medir.
CONFIANTE = Decimal("0.90")
# Abaixo do limiar: producao rebaixaria este palpite para INDEFINIDA.
INSEGURA = Decimal("0.50")


def classificacao(
    esperada: Intencao,
    obtida: Intencao,
    *,
    confianca: Decimal = CONFIANTE,
    conversa_id: str = "c-01",
    indice: int = 0,
) -> Classificacao:
    return Classificacao(
        conversa_id=conversa_id,
        indice=indice,
        esperada=esperada,
        obtida=obtida,
        confianca=confianca,
    )


@pytest.mark.parametrize(
    ("acertos", "total", "esperada"),
    [
        (135, 150, Faixa.VERDE),  # exatamente 90%
        (134, 150, Faixa.AMARELO),  # um abaixo do alvo
        (126, 150, Faixa.AMARELO),  # exatamente 84%, o piso -- ainda passa
        (125, 150, Faixa.VERMELHO),  # um abaixo do piso
        (150, 150, Faixa.VERDE),
        (0, 150, Faixa.VERMELHO),
    ],
)
def test_bordas_exatas_da_faixa(acertos: int, total: int, esperada: Faixa) -> None:
    """As bordas sao o unico lugar onde a faixa pode estar errada.

    126/150 e exatamente 84%, o piso, e 135/150 exatamente 90%, o alvo. Os
    dois casos passam em float tambem (`126/150 >= 0.84` e True) -- a
    aritmetica inteira nao esta aqui para consertar uma borda que float
    erraria, e sim para que a corretude na borda seja obvia por construcao em
    vez de depender de conferir a representacao binaria de cada literal.
    O que este teste guarda e o sentido de cada comparacao: `>=` no alvo e no
    piso, e nao `>`.
    """
    assert faixa_de(acertos, total) is esperada


def test_total_zero_e_erro_e_nao_verde() -> None:
    """Nada medido nao e sucesso. Sem esta guarda, um corpus que falhou ao
    carregar produziria 0/0 e o gate abriria."""
    with pytest.raises(ValueError):
        faixa_de(0, 0)


def test_acuracia_conta_acertos_por_turno() -> None:
    classificacoes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=0),
        classificacao(Intencao.ALUGUEL, Intencao.COMPRA, indice=1),
    ]

    resultado = acuracia_de_intencao(classificacoes)

    assert resultado.acertos == 1
    assert resultado.total == 2
    assert resultado.faixa is Faixa.VERMELHO


def test_matriz_agrupa_esperada_contra_obtida() -> None:
    """Saber que a acuracia caiu nao diz o que fazer. Saber que INVESTIMENTO
    vira COMPRA, sim."""
    classificacoes = [
        classificacao(Intencao.INVESTIMENTO, Intencao.COMPRA, conversa_id="c-01"),
        classificacao(Intencao.INVESTIMENTO, Intencao.COMPRA, conversa_id="c-02"),
        classificacao(Intencao.INVESTIMENTO, Intencao.INVESTIMENTO, conversa_id="c-03"),
    ]

    matriz = matriz_de_confusao(classificacoes)

    assert matriz[Intencao.INVESTIMENTO][Intencao.COMPRA] == 2
    assert matriz[Intencao.INVESTIMENTO][Intencao.INVESTIMENTO] == 1


def test_matriz_agrupa_pelo_palpite_cru_e_nao_pela_efetiva() -> None:
    """A matriz diz para onde a intencao escorreu, e isso e sobre o
    classificador. Se ela agrupasse pela efetiva, este caso viraria uma
    contagem em INDEFINIDA e ninguem saberia que o palpite foi COMPRA."""
    classificacoes = [classificacao(Intencao.INVESTIMENTO, Intencao.COMPRA, confianca=INSEGURA)]

    matriz = matriz_de_confusao(classificacoes)

    assert matriz[Intencao.INVESTIMENTO] == {Intencao.COMPRA: 1}


def test_metrica_sem_mecanismo_nunca_e_verde_e_nunca_bloqueia() -> None:
    """As duas metades importam. Verde esconderia que a metrica nao mede nada;
    bloquear deixaria o gate permanentemente vermelho, e gate sempre vermelho
    e desligado em uma semana.
    """
    metrica = sem_mecanismo("taxa de alucinacao", "bloqueada pela TEC-161")

    assert metrica.faixa is Faixa.SEM_MECANISMO
    assert metrica.faixa is not Faixa.VERDE
    assert metrica.acertos is None
    assert not bloqueia([metrica])


def test_apenas_vermelho_bloqueia() -> None:
    verde = acuracia_de_intencao([classificacao(Intencao.COMPRA, Intencao.COMPRA)])
    vermelho = acuracia_de_intencao([classificacao(Intencao.COMPRA, Intencao.ALUGUEL)])

    assert not bloqueia([verde])
    assert bloqueia([vermelho])
    assert bloqueia([verde, vermelho])


def test_acuracia_efetiva_conta_o_palpite_rebaixado_como_erro() -> None:
    """O palpite esta certo e producao nao o usa: abaixo do limiar,
    `executar_turno` responde com a pergunta de desambiguacao. A acuracia crua
    ve um acerto; a efetiva ve o que o lead recebeu."""
    classificacoes = [classificacao(Intencao.COMPRA, Intencao.COMPRA, confianca=INSEGURA)]

    assert acuracia_de_intencao(classificacoes).acertos == 1
    assert acuracia_efetiva(classificacoes).acertos == 0


def test_acuracia_efetiva_respeita_a_borda_fechada_por_cima_do_limiar() -> None:
    """`>= LIMIAR` nao desambigua, e "confianca exatamente 0,6 nao desambigua"
    e criterio de aceite do TEC-135. O eval le o limiar de producao pela
    `intencao_efetiva`, entao esta borda tem de ser a mesma nos dois lados --
    e ela e a que uma reimplementacao com `<=` erraria em silencio.
    """
    na_borda = [classificacao(Intencao.COMPRA, Intencao.COMPRA, confianca=LIMIAR_DE_DESAMBIGUACAO)]

    assert acuracia_efetiva(na_borda).acertos == 1


def test_acuracia_efetiva_bloqueia_quando_a_crua_esta_verde() -> None:
    """A regressao que motiva a metrica: o classificador continua acertando
    tudo e a confianca desabou. Sem esta metrica o gate ficaria verde
    enquanto producao desambigua em metade dos turnos.
    """
    confiantes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=i, confianca=CONFIANTE)
        for i in range(5)
    ]
    inseguras = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=5 + i, confianca=INSEGURA)
        for i in range(5)
    ]
    classificacoes = confiantes + inseguras

    crua = acuracia_de_intencao(classificacoes)
    efetiva = acuracia_efetiva(classificacoes)

    assert crua.faixa is Faixa.VERDE
    assert efetiva.faixa is Faixa.VERMELHO
    assert bloqueia([crua, efetiva])


def test_acuracia_efetiva_pode_passar_da_crua_em_turno_indefinido() -> None:
    """Nao e bug: quando o rotulo e INDEFINIDA, rebaixar um palpite
    mal-confiante acerta o rotulo. Documentado por teste para que a
    desigualdade nao seja lida como inversao de sinal em algum lugar."""
    classificacoes = [classificacao(Intencao.INDEFINIDA, Intencao.COMPRA, confianca=INSEGURA)]

    assert acuracia_de_intencao(classificacoes).acertos == 0
    assert acuracia_efetiva(classificacoes).acertos == 1


def test_resumo_de_confianca_separa_rebaixado_de_recuperado() -> None:
    """Os tres numeros que a recalibragem do limiar precisa, e que nenhuma
    outra execucao produz."""
    classificacoes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=0, confianca=CONFIANTE),
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=1, confianca=INSEGURA),
        classificacao(Intencao.INDEFINIDA, Intencao.ALUGUEL, indice=2, confianca=INSEGURA),
        classificacao(Intencao.ALUGUEL, Intencao.COMPRA, indice=3, confianca=CONFIANTE),
    ]

    resumo = resumo_de_confianca(classificacoes)

    assert resumo.turnos == 4
    assert resumo.abaixo_do_limiar == 2
    assert resumo.acertos_rebaixados == 1
    assert resumo.acertos_recuperados == 1


def test_erros_incluem_o_acerto_rebaixado_e_excluem_o_acerto_confiante() -> None:
    """O acerto rebaixado nao aparece na acuracia crua nem na matriz. Se
    tambem nao aparecesse aqui, o unico jeito de descobri-lo seria outra
    execucao paga."""
    confiante_certo = classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=0)
    rebaixado = classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=1, confianca=INSEGURA)
    errado = classificacao(Intencao.ALUGUEL, Intencao.COMPRA, indice=2)

    assert erros([confiante_certo, rebaixado, errado]) == [rebaixado, errado]

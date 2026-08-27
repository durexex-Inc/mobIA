import pytest

from mobia.domain.agente.schemas import Intencao
from mobia.evals.metricas import (
    Classificacao,
    Faixa,
    acuracia_de_intencao,
    bloqueia,
    faixa_de,
    matriz_de_confusao,
    sem_mecanismo,
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
        Classificacao("c-01", 0, Intencao.COMPRA, Intencao.COMPRA),
        Classificacao("c-01", 1, Intencao.ALUGUEL, Intencao.COMPRA),
    ]

    resultado = acuracia_de_intencao(classificacoes)

    assert resultado.acertos == 1
    assert resultado.total == 2
    assert resultado.faixa is Faixa.VERMELHO


def test_matriz_agrupa_esperada_contra_obtida() -> None:
    """Saber que a acuracia caiu nao diz o que fazer. Saber que INVESTIMENTO
    vira COMPRA, sim."""
    classificacoes = [
        Classificacao("c-01", 0, Intencao.INVESTIMENTO, Intencao.COMPRA),
        Classificacao("c-02", 0, Intencao.INVESTIMENTO, Intencao.COMPRA),
        Classificacao("c-03", 0, Intencao.INVESTIMENTO, Intencao.INVESTIMENTO),
    ]

    matriz = matriz_de_confusao(classificacoes)

    assert matriz[Intencao.INVESTIMENTO][Intencao.COMPRA] == 2
    assert matriz[Intencao.INVESTIMENTO][Intencao.INVESTIMENTO] == 1


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
    verde = acuracia_de_intencao([Classificacao("c", 0, Intencao.COMPRA, Intencao.COMPRA)])
    vermelho = acuracia_de_intencao([Classificacao("c", 0, Intencao.COMPRA, Intencao.ALUGUEL)])

    assert not bloqueia([verde])
    assert bloqueia([vermelho])
    assert bloqueia([verde, vermelho])

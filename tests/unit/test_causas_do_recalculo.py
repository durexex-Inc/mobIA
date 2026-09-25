"""As causas de um recalculo, derivadas do diff entre dois Score.

TEC-152. Sem banco: a funcao e pura.
"""

from dataclasses import fields

import pytest

from mobia.domain.context.auditoria import (
    _CAUSA_POR_FATOR,
    CAUSA_CAMPOS_OBRIGATORIOS,
    CAUSA_CATALOGO,
    CAUSA_ENGAJAMENTO,
    CAUSA_FORMA_DE_PAGAMENTO,
    CAUSA_PENALIDADE,
    CAUSA_PRIMEIRO_CALCULO,
    CAUSA_URGENCIA,
    causas_do_recalculo,
)
from mobia.domain.context.score import Score


def score(**ajustes: int) -> Score:
    """Um Score com os fatores zerados, menos os que o teste ajusta."""
    base = {
        "completude": 0,
        "urgencia": 0,
        "catalogo": 0,
        "engajamento": 0,
        "capacidade": 0,
        "penalidade": 0,
    }
    return Score(**{**base, **ajustes})


@pytest.mark.parametrize(
    ("fator", "causa"),
    [
        ("completude", CAUSA_CAMPOS_OBRIGATORIOS),
        ("urgencia", CAUSA_URGENCIA),
        ("catalogo", CAUSA_CATALOGO),
        ("engajamento", CAUSA_ENGAJAMENTO),
        ("capacidade", CAUSA_FORMA_DE_PAGAMENTO),
    ],
)
def test_cada_fator_movendo_sozinho_produz_a_sua_causa_e_so_ela(fator: str, causa: str) -> None:
    assert causas_do_recalculo(score(), score(**{fator: 5})) == (causa,)


def test_o_fator_caindo_produz_a_mesma_causa_que_subindo() -> None:
    """O vocabulario e do dominio, nao da direcao: subiu ou caiu se le nos numeros."""
    assert causas_do_recalculo(score(urgencia=25), score(urgencia=8)) == (CAUSA_URGENCIA,)


def test_duas_causas_no_mesmo_passo() -> None:
    """A mensagem que informa a forma de pagamento tambem move o engajamento."""
    anterior = score(capacidade=6, engajamento=10)
    novo = score(capacidade=15, engajamento=15)
    assert causas_do_recalculo(anterior, novo) == (
        CAUSA_ENGAJAMENTO,
        CAUSA_FORMA_DE_PAGAMENTO,
    )


def test_total_identico_com_composicao_diferente_produz_causas() -> None:
    """O caso da D3, e o unico em que comparar totais devolveria "nada aconteceu".

    O lead so tinha informado urgencia (completude 5, urgencia 15) e diz "quero
    comprar apto ate 500 mil na Vila Mariana, mas sem pressa": intencao, faixa
    de preco e regiao entram de uma vez (+15) e a urgencia cai para SEM_PRESSA
    (-15). O total nao se move e o lead passou de quase anonimo a quase
    completo.
    """
    anterior = score(completude=5, urgencia=15)
    novo = score(completude=20, urgencia=0)

    assert anterior.total == novo.total
    assert causas_do_recalculo(anterior, novo) == (
        CAUSA_CAMPOS_OBRIGATORIOS,
        CAUSA_URGENCIA,
    )


def test_nada_se_movendo_devolve_vazio() -> None:
    """Tupla vazia e o sinal de "nao grave" -- a regra da D3 mora aqui, e nao
    num `if` do chamador."""
    igual = score(completude=20, urgencia=15, engajamento=10, capacidade=6)
    assert causas_do_recalculo(igual, igual) == ()


def test_sem_anterior_e_primeiro_calculo_e_so_ele() -> None:
    """Nao a lista dos fatores diferentes de zero: nao houve movimento a explicar."""
    novo = score(completude=20, urgencia=15, engajamento=10, capacidade=6)
    assert causas_do_recalculo(None, novo) == (CAUSA_PRIMEIRO_CALCULO,)


def test_o_mapa_cobre_exatamente_os_fatores_do_Score() -> None:
    """Um fator no Score sem causa correspondente tem de deixar isto vermelho,
    e nao passar em silencio -- e a mesma defesa que a TEC-150 deu aos dois
    mapas de pontos, amarrando-os aos seus enums.

    Foi "os cinco fatores" ate a TEC-172, que acrescentou `penalidade`. Este
    teste e o que fez aquela card lembrar de mapear a causa junto: sem o par
    novo, uma penalidade que se move nao produziria causa nenhuma e a linha da
    trilha nao existiria.
    """
    assert {fator for fator, _ in _CAUSA_POR_FATOR} == {campo.name for campo in fields(Score)}


def test_a_penalidade_que_se_move_produz_a_propria_causa() -> None:
    """TEC-172. Derivada do diff, como os outros fatores.

    `CAUSA_NAO_COMPARECIMENTO` e outra coisa: ela e informada pelo chamador
    como causa EXTERNA, e diz por que a penalidade se moveu. As duas juntas
    sao o que a trilha precisa -- o que mudou e por que mudou --, e usar so
    uma apagaria metade da resposta.
    """
    antes = score()
    depois = score(penalidade=15)
    assert causas_do_recalculo(antes, depois) == (CAUSA_PENALIDADE,)

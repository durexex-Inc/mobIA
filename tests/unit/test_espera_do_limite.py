"""A espera ate caber de novo um pedido na janela deslizante. TEC-346, D1.

O zset guarda os `limite + 1` pedidos mais recentes (o barrado incluso). Um
pedido novo cabe quando sobram no maximo `limite - 1` antigos na janela, ou
seja, quando os DOIS mais velhos saem dela: a espera e `score[1] + janela -
agora`.
"""

import pytest

from mobia.infra.rate_limit import ESPERA_PADRAO_EM_SEGUNDOS, espera_para_caber


def test_espera_ate_o_segundo_mais_velho_sair_da_janela() -> None:
    # limite 2: zset com 3 pedidos, em 0, 40 e 50. O de 40 sai em 100.
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=80.0) == 20


def test_arredonda_para_cima() -> None:
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=80.5) == 20
    assert espera_para_caber([0.0, 40.2, 50.0], janela_segundos=60, agora=80.0) == 21


def test_nunca_menos_de_um_segundo() -> None:
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=100.0) == 1
    assert espera_para_caber([0.0, 40.0, 50.0], janela_segundos=60, agora=500.0) == 1


def test_limite_um_espera_a_janela_desde_o_ultimo() -> None:
    # limite 1: zset com 2 pedidos; o segundo e o proprio barrado.
    assert espera_para_caber([10.0, 30.0], janela_segundos=60, agora=30.0) == 60


@pytest.mark.parametrize("scores", [[], [10.0]])
def test_sem_dados_suficientes_vale_o_padrao(scores: list[float]) -> None:
    assert espera_para_caber(scores, janela_segundos=60, agora=30.0) == ESPERA_PADRAO_EM_SEGUNDOS

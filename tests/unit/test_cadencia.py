"""A regua da RN-13.1: qual tentativa de follow-up esta vencida agora.

TEC-183. Sem banco: a funcao e pura.
"""

from datetime import UTC, datetime, timedelta

import pytest

from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA, INTERVALO_MINIMO, tentativa_devida

ANCORA = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def devida(temperatura: Temperatura, passado: timedelta, ja_disparada: int = 0) -> int | None:
    return tentativa_devida(
        temperatura=temperatura,
        ultima_fala=ANCORA,
        ja_disparada=ja_disparada,
        agora=ANCORA + passado,
    )


@pytest.mark.parametrize(
    ("temperatura", "tentativas"),
    [(Temperatura.QUENTE, 4), (Temperatura.MORNO, 3), (Temperatura.FRIO, 2)],
)
def test_o_numero_de_tentativas_por_temperatura(temperatura: Temperatura, tentativas: int) -> None:
    """A tabela da RN-13.1, e o criterio de aceite que a repete."""
    assert len(CADENCIA[temperatura]) == tentativas


def test_os_intervalos_sao_os_do_srs() -> None:
    """Se estes numeros mudarem, foi decisao de alguem -- nao deixe passar em
    silencio. A RN-13.1 fixa os tres conjuntos."""
    assert CADENCIA[Temperatura.QUENTE] == (
        timedelta(hours=2),
        timedelta(hours=24),
        timedelta(days=3),
        timedelta(days=7),
    )
    assert CADENCIA[Temperatura.MORNO] == (
        timedelta(hours=24),
        timedelta(days=4),
        timedelta(days=10),
    )
    assert CADENCIA[Temperatura.FRIO] == (timedelta(days=3), timedelta(days=14))


def test_a_primeira_tentativa_do_quente_vence_em_duas_horas() -> None:
    """A CA-13.1: parou as 18h, follow-up as 20h."""
    assert devida(Temperatura.QUENTE, timedelta(hours=2)) == 1


def test_um_minuto_antes_nao_vence() -> None:
    assert devida(Temperatura.QUENTE, timedelta(hours=1, minutes=59)) is None


def test_a_borda_e_inclusiva() -> None:
    """`>=` e nao `>`: no instante exato do deslocamento a tentativa vence.
    Com `>` um disparo poderia escorregar para a varredura seguinte por um
    microssegundo, e a diferenca so apareceria em producao."""
    assert devida(Temperatura.QUENTE, CADENCIA[Temperatura.QUENTE][0]) == 1


def test_os_deslocamentos_sao_desde_a_ancora_e_nao_encadeados() -> None:
    """A RN-13.1 diz "contada a partir da ultima mensagem do lead". A segunda
    tentativa do QUENTE vence em +24h desde a ANCORA, nao 24h depois da
    primeira -- se fosse encadeada, venceria so em +26h."""
    assert devida(Temperatura.QUENTE, timedelta(hours=24), ja_disparada=1) == 2
    assert devida(Temperatura.QUENTE, timedelta(hours=23), ja_disparada=1) is None


def test_o_lead_muito_atrasado_recebe_so_a_ultima_vencida() -> None:
    """A decisao mais facil de errar do desenho.

    Dez dias de silencio deixam as quatro tentativas do QUENTE vencidas ao
    mesmo tempo. Devolvendo "a proxima", este lead receberia quatro follow-ups
    em vinte minutos (uma por varredura de 5 min). Devolve a MAIOR vencida, e a
    cadencia fecha de uma vez.
    """
    assert devida(Temperatura.QUENTE, timedelta(days=10)) == 4


def test_depois_do_salto_nao_sobra_nada_para_tras() -> None:
    """O motivo de `ja_disparada` ser o MAX e nao um COUNT.

    Com contagem, o lead do teste acima teria `ja_disparada=1` na varredura
    seguinte, a regua acharia que so uma foi feita e disparia a 2 -- refazendo
    para tras uma tentativa que o salto ja tornou obsoleta.
    """
    assert devida(Temperatura.QUENTE, timedelta(days=10), ja_disparada=4) is None


def test_a_cadencia_esgotada_devolve_none() -> None:
    assert devida(Temperatura.FRIO, timedelta(days=30), ja_disparada=2) is None


def test_esfriar_encurta_a_cadencia_restante() -> None:
    """ "Mudanca de temperatura recalcula a cadencia restante": um lead que
    recebeu tres tentativas como QUENTE e esfriou para MORNO nao recebe a
    quarta, porque MORNO tem tres."""
    assert devida(Temperatura.MORNO, timedelta(days=30), ja_disparada=3) is None


def test_esquentar_alonga_a_cadencia_restante() -> None:
    """O outro lado da mesma regra: MORNO esgotado que esquenta ganha a quarta
    do QUENTE."""
    assert devida(Temperatura.QUENTE, timedelta(days=30), ja_disparada=3) == 4


def test_o_intervalo_minimo_e_derivado_e_nao_escrito_a_mao() -> None:
    """A varredura usa este valor como corte barato: nada abaixo dele pode
    estar devido em temperatura nenhuma. Derivado de `CADENCIA` para nao virar
    uma segunda fonte que diverge quando alguem mexer na tabela."""
    assert INTERVALO_MINIMO == timedelta(hours=2)
    assert INTERVALO_MINIMO == min(intervalos[0] for intervalos in CADENCIA.values())


def test_os_argumentos_sao_keyword_only() -> None:
    """`ultima_fala` e `agora` sao dois `datetime` adjacentes: trocar a ordem
    nao levanta, nao e erro de tipo, nao e visivel ao mypy, e devolve a
    tentativa errada em silencio. Mesma razao dos flags de `temperatura_de`."""
    with pytest.raises(TypeError):
        tentativa_devida(Temperatura.QUENTE, ANCORA, 0, ANCORA)  # type: ignore[misc]

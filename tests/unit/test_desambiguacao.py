"""As duas decisoes do TEC-135, sem banco e sem modelo.

O cenario de aceite "confianca exatamente 0,6 nao desambigua" mora aqui e nao
num teste de integracao: e uma comparacao de borda, e o resto do turno nao
acrescenta nada a prova.
"""

from datetime import UTC, datetime
from decimal import Decimal

from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao

JA_PERGUNTOU = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def test_confianca_no_limiar_exato_nao_desambigua() -> None:
    """Criterio de aceite: 0,6 e fechado por cima."""
    assert deve_desambiguar(Decimal("0.6"), None) is False


def test_logo_abaixo_do_limiar_desambigua() -> None:
    assert deve_desambiguar(Decimal("0.59"), None) is True


def test_marcador_preenchido_impede_a_segunda_pergunta() -> None:
    """Ambiguidade persistente nao vira insistencia."""
    assert deve_desambiguar(Decimal("0.45"), JA_PERGUNTOU) is False


def test_confianca_alta_nao_desambigua_com_ou_sem_marcador() -> None:
    assert deve_desambiguar(Decimal("0.91"), None) is False
    assert deve_desambiguar(Decimal("0.91"), JA_PERGUNTOU) is False


def test_intencao_abaixo_do_limiar_e_indefinida() -> None:
    """O palpite existe na tabela, mas ninguem roteia por ele."""
    assert intencao_efetiva(Intencao.COMPRA, Decimal("0.45")) is Intencao.INDEFINIDA


def test_intencao_no_limiar_exato_e_preservada() -> None:
    assert intencao_efetiva(Intencao.COMPRA, LIMIAR_DE_DESAMBIGUACAO) is Intencao.COMPRA


def test_intencao_confiante_passa_intacta() -> None:
    assert intencao_efetiva(Intencao.ALUGUEL, Decimal("0.91")) is Intencao.ALUGUEL

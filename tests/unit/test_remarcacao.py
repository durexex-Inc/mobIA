"""A regua do convite de remarcacao, o kind e o texto. TEC-172, RN-12.3.

Puro: nada aqui toca banco nem rede.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from mobia.domain.agendamento.remarcacao import (
    ANTECEDENCIA_DO_CONVITE,
    TEMPLATE_DO_CONVITE,
    TEXTO_DO_CONVITE_DE_REMARCACAO,
    VALIDADE_DO_CONVITE,
    convite_devido,
    kind_do_convite,
    template_do_convite,
)

CANCELADO = datetime(2026, 9, 25, 17, tzinfo=UTC)
DEVIDO = CANCELADO + ANTECEDENCIA_DO_CONVITE
AGENDAMENTO = uuid.UUID("3f2504e0-4f89-11d3-9a0c-0305e82c3301")
OUTRO = uuid.UUID("a1b2c3d4-4f89-11d3-9a0c-0305e82c3301")


def test_devido_no_piso_da_faixa() -> None:
    """RN-12.3: "agenda tentativa de remarcacao em 24 horas"."""
    assert convite_devido(cancelado_em=CANCELADO, agora=DEVIDO) is True


def test_nao_devido_antes_das_vinte_e_quatro_horas() -> None:
    assert convite_devido(cancelado_em=CANCELADO, agora=DEVIDO - timedelta(minutes=1)) is False


def test_devido_no_meio_da_faixa() -> None:
    assert convite_devido(cancelado_em=CANCELADO, agora=DEVIDO + timedelta(days=3)) is True


def test_nao_devido_no_teto() -> None:
    """O teto e exclusivo, e resolve dois problemas de uma vez: o convite que
    perdeu o sentido, e o backfill de todo cancelamento anterior a esta card.
    """
    assert convite_devido(cancelado_em=CANCELADO, agora=DEVIDO + VALIDADE_DO_CONVITE) is False


def test_cancelamento_sem_carimbo_nao_autoriza_envio() -> None:
    """Nulo com status CANCELADO e um estado que `cancelar` nao produz."""
    assert convite_devido(cancelado_em=None, agora=DEVIDO) is False


def test_a_regua_exige_datetime_com_fuso() -> None:
    with pytest.raises(ValueError, match="sem tzinfo"):
        convite_devido(cancelado_em=CANCELADO.replace(tzinfo=None), agora=DEVIDO)


def test_o_kind_cabe_nos_trinta_e_dois_caracteres() -> None:
    assert len(kind_do_convite(AGENDAMENTO)) == 32


def test_dois_agendamentos_tem_kinds_diferentes() -> None:
    """Dois cancelamentos do mesmo lead caem na mesma mensagem-ancora: com um
    kind fixo, o segundo convite seria suprimido como reentrega."""
    assert kind_do_convite(AGENDAMENTO) != kind_do_convite(OUTRO)


def test_o_texto_convida_e_nao_promete() -> None:
    """Nada le a resposta -- nem aqui nem no lembrete da TEC-171.

    O texto tambem nao repete a data do que foi cancelado: lembrar o lead do
    que ele proprio desmarcou nao ajuda ninguem.
    """
    assert "remarcar" in TEXTO_DO_CONVITE_DE_REMARCACAO
    assert "já remarquei" not in TEXTO_DO_CONVITE_DE_REMARCACAO


def test_sem_template_aprovado_nao_ha_template() -> None:
    assert template_do_convite(aprovados=frozenset()) is None


def test_com_o_template_aprovado_ele_e_escolhido() -> None:
    assert template_do_convite(aprovados=frozenset({TEMPLATE_DO_CONVITE})) == TEMPLATE_DO_CONVITE

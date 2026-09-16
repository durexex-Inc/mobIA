"""Quando tres mensagens fora de escopo encerram a conversa. TEC-138.

Puro: nao toca banco nem modelo.
"""

import pytest

from mobia.domain.conversa.regras import TETO_DE_FORA_DE_ESCOPO, deve_encerrar


@pytest.mark.parametrize("seguidas", [0, 1, 2])
def test_abaixo_do_teto_a_conversa_segue(seguidas: int) -> None:
    """As duas primeiras sao redirecionadas, nao encerradas.

    O zero entra porque e o estado de toda conversa que nunca teve mensagem
    fora de escopo, e a guarda roda em todo turno.
    """
    assert deve_encerrar(seguidas) is False


def test_no_teto_a_conversa_encerra() -> None:
    """A TERCEIRA encerra -- a card conta mensagens, nao turnos depois delas."""
    assert deve_encerrar(TETO_DE_FORA_DE_ESCOPO) is True


def test_acima_do_teto_continua_encerrando() -> None:
    """Defensivo, e o caso existe: um turno concorrente pode ter passado do
    teto entre a contagem deste e a decisao dele. Encerrar de novo e
    idempotente; parar de encerrar seria perder o caso.
    """
    assert deve_encerrar(TETO_DE_FORA_DE_ESCOPO + 1) is True


def test_o_teto_e_tres() -> None:
    """A card diz tres, e este e o unico lugar em que o numero esta escrito."""
    assert TETO_DE_FORA_DE_ESCOPO == 3

"""O roteamento por faixa de ticket da RN-07.4. TEC-153, D5."""

import pytest

from mobia.domain.corretores.vocabulario import (
    TICKET_DE_ALTO_TICKET_CENTAVOS,
    Especialidade,
    especialidade_de,
)


def test_o_limiar_e_um_milhao_de_reais() -> None:
    """Pinado: e o numero da RN-07.4, e o unico lugar em que ele esta escrito."""
    assert TICKET_DE_ALTO_TICKET_CENTAVOS == 100_000_000


@pytest.mark.parametrize(
    ("ticket", "esperada"),
    [
        (80_000_000, Especialidade.INVESTIMENTO),
        (100_000_000, Especialidade.INVESTIMENTO_ALTO_TICKET),
        (250_000_000, Especialidade.INVESTIMENTO_ALTO_TICKET),
    ],
)
def test_o_esquema_de_cenario_da_card(ticket, esperada) -> None:
    assert especialidade_de(ticket) is esperada


def test_um_centavo_abaixo_do_limiar_ainda_e_investimento() -> None:
    """A RN-07.4 diz "a partir de", entao o limiar PERTENCE ao alto ticket. E
    a fronteira que o Esquema de Cenario nao exercita sozinho."""
    assert especialidade_de(TICKET_DE_ALTO_TICKET_CENTAVOS - 1) is Especialidade.INVESTIMENTO

"""O ticket do investidor reusa o parser de dinheiro. TEC-153, D6."""

from mobia.domain.agente.dinheiro import ticket_de


def test_o_cenario_do_gherkin() -> None:
    """ "uns 800 mil" informado como ticket vira 80000000 centavos."""
    assert ticket_de("uns 800 mil") == 80_000_000


def test_um_milhao_e_o_limiar_do_alto_ticket() -> None:
    assert ticket_de("1 milhao") == 100_000_000


def test_expressao_sem_valor_devolve_none() -> None:
    """Recusa e caminho normal desde a TEC-148, nao excecao."""
    assert ticket_de("prefiro nao dizer") is None


def test_faixa_colapsa_no_extremo_superior() -> None:
    """Numa busca "ate 800 mil" e teto; num ticket e o montante disponivel.
    A semantica difere, e o colapso acontece aqui, na borda."""
    assert ticket_de("ate 800 mil") == 80_000_000

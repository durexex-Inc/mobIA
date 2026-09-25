from mobia.domain.agente.schemas import Intencao
from mobia.domain.corretores.vocabulario import (
    CAPACIDADE_MINIMA,
    HORA_MAXIMA,
    HORA_MINIMA,
    Especialidade,
    jornada_valida,
)


def test_sao_as_quatro_especialidades_da_card() -> None:
    assert {e.value for e in Especialidade} == {
        "COMPRA",
        "ALUGUEL",
        "INVESTIMENTO",
        "INVESTIMENTO_ALTO_TICKET",
    }


def test_a_grafia_das_tres_compartilhadas_bate_com_intencao() -> None:
    """D3: e por igualdade de string que `criterio_de` (TEC-166) mapeia.

    Se alguem renomear um membro de qualquer um dos dois enums, este teste
    reprova -- que e exatamente o ponto. Sem ele, a divergencia so apareceria
    na alocacao, como lead que nao casa com corretor nenhum.
    """
    compartilhadas = {"COMPRA", "ALUGUEL", "INVESTIMENTO"}
    especialidades = {e.value for e in Especialidade}
    intencoes = {i.value for i in Intencao}

    assert compartilhadas <= especialidades
    assert compartilhadas <= intencoes


def test_alto_ticket_nao_e_intencao() -> None:
    """E segmentacao de ticket, nao intencao de conversa -- ver a D3."""
    assert "INVESTIMENTO_ALTO_TICKET" not in {i.value for i in Intencao}


def test_jornada_valida_exige_inicio_antes_do_fim() -> None:
    assert jornada_valida(9, 18) is True
    assert jornada_valida(18, 9) is False
    assert jornada_valida(9, 9) is False


def test_jornada_valida_recusa_hora_fora_do_relogio() -> None:
    assert jornada_valida(-1, 18) is False
    assert jornada_valida(9, 24) is False
    assert jornada_valida(HORA_MINIMA, HORA_MAXIMA) is True


def test_a_capacidade_minima_e_uma_visita() -> None:
    # Corretor com capacidade zero nao e corretor desativado -- para isso ha
    # `ativo`. Zero aqui seria uma linha que nunca recebe alocacao e que
    # ninguem consegue explicar depois.
    assert CAPACIDADE_MINIMA == 1

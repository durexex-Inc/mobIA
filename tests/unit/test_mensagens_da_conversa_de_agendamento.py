"""Os textos dos tres turnos que marcam a visita. TEC-371, D11.

O que estes testes protegem e o que a RN-11.3 exige: toda janela dita ao lead
carrega dia da semana, dia do mes e hora, e nenhuma delas e relativa.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.agendamento.mensagens import (
    TEXTO_DA_ESCOLHA,
    TEXTO_DAS_JANELAS,
    linhas_das_janelas,
)

SP = ZoneInfo("America/Sao_Paulo")
QUINTA_9H = datetime(2026, 10, 1, 9, 0, tzinfo=SP)
QUINTA_11H30 = datetime(2026, 10, 1, 11, 30, tzinfo=SP)
SEXTA_11H = datetime(2026, 10, 2, 11, 0, tzinfo=SP)


def test_cada_janela_sai_numerada_e_absoluta() -> None:
    assert linhas_das_janelas([QUINTA_9H, QUINTA_11H30, SEXTA_11H]) == (
        "1. quinta-feira, 1º de outubro, às 9h\n"
        "2. quinta-feira, 1º de outubro, às 11h30\n"
        "3. sexta-feira, 2 de outubro, às 11h"
    )


def test_uma_janela_so_nao_deixa_lista_torta() -> None:
    assert linhas_das_janelas([QUINTA_9H]) == "1. quinta-feira, 1º de outubro, às 9h"


def test_nenhuma_janela_e_string_vazia() -> None:
    """Quem chama nao monta oferta sem janela -- mas a funcao nao levanta por isso."""
    assert linhas_das_janelas([]) == ""


def test_a_oferta_pergunta_e_nao_promete() -> None:
    texto = TEXTO_DAS_JANELAS.format(janelas=linhas_das_janelas([QUINTA_9H]))
    assert texto.endswith("Qual deles fica melhor?")
    assert "corretor vai" not in texto
    assert "avisei" not in texto


def test_a_pergunta_de_confirmacao_repete_o_horario_por_extenso() -> None:
    """A protecao do RT-10: se a escolha foi lida errado, e aqui que o lead corrige."""
    texto = TEXTO_DA_ESCOLHA.format(
        quando="quinta-feira, 1º de outubro, às 9h", corretor="Paula M."
    )
    assert "quinta-feira, 1º de outubro, às 9h" in texto
    assert "esse horário" not in texto.lower()


@pytest.mark.parametrize("relativo", ["amanhã", "que vem", "hoje", "depois de amanhã"])
def test_nenhum_texto_usa_data_relativa(relativo: str) -> None:
    montado = "\n".join(
        [
            TEXTO_DAS_JANELAS,
            TEXTO_DA_ESCOLHA,
            linhas_das_janelas([QUINTA_9H, SEXTA_11H]),
        ]
    )
    assert relativo not in montado.lower()

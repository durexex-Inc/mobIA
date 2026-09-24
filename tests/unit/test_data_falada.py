"""A data falada pelo lead, resolvida. TEC-167, RN-11.3.

Puro: `agora` e sempre um literal com fuso. O `agora` padrao e o da card:
terca-feira, 25/08/2026, 14h.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.agendamento.data_falada import (
    TEXTO_DA_DATA_INEXISTENTE,
    TEXTO_DA_NOITE,
    TEXTO_DO_DOMINGO,
    TEXTO_DO_PASSADO,
    Ambigua,
    Dia,
    Instante,
    NaoReconhecida,
    Periodo,
    PeriodoDoDia,
    Semana,
    data_absoluta,
    data_e_hora_absolutas,
    resolver,
)

SP = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 8, 25, 14, 0, tzinfo=SP)


def _ago(dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    return datetime(2026, 8, dia, hora, minuto, tzinfo=SP)


def _set(dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    return datetime(2026, 9, dia, hora, minuto, tzinfo=SP)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # a tabela da card
        ("amanhã de tarde", Periodo(date(2026, 8, 26), PeriodoDoDia.TARDE)),
        ("quinta às 15h", Instante(_ago(27, 15))),
        ("semana que vem", Semana(date(2026, 8, 31))),
        # o primeiro cenario da card
        ("pode ser quinta de manhã", Periodo(date(2026, 8, 27), PeriodoDoDia.MANHA)),
        # dias
        ("próxima semana", Semana(date(2026, 8, 31))),
        ("quinta", Dia(date(2026, 8, 27))),
        ("quinta-feira", Dia(date(2026, 8, 27))),
        ("sexta que vem", Dia(date(2026, 8, 28))),
        ("próxima sexta", Dia(date(2026, 8, 28))),
        ("sábado", Dia(date(2026, 8, 29))),
        ("segunda", Dia(date(2026, 8, 31))),
        ("amanhã", Dia(date(2026, 8, 26))),
        ("depois de amanhã", Dia(date(2026, 8, 27))),
        ("dia 3", Dia(date(2026, 9, 3))),
        ("dia 25", Dia(date(2026, 9, 25))),
        ("dia 21", Dia(date(2026, 9, 21))),
        ("3/9", Dia(date(2026, 9, 3))),
        ("03/09", Dia(date(2026, 9, 3))),
        ("quinta da semana que vem", Dia(date(2026, 9, 3))),
        # periodos e horas
        ("hoje de tarde", Periodo(date(2026, 8, 25), PeriodoDoDia.TARDE)),
        ("hoje às 16h30", Instante(_ago(25, 16, 30))),
        ("amanhã 10h", Instante(_ago(26, 10))),
        ("amanha as 15:30", Instante(_ago(26, 15, 30))),
        ("quinta 3 da tarde", Instante(_ago(27, 15))),
        ("sexta 10 da manhã", Instante(_ago(28, 10))),
        ("às 16h", Instante(_ago(25, 16))),
        ("AMANHÃ DE TARDE", Periodo(date(2026, 8, 26), PeriodoDoDia.TARDE)),
    ],
)
def test_resolve_expressoes_comuns(texto: str, esperado: object) -> None:
    assert resolver(texto, agora=AGORA) == esperado


def test_amanha_numa_sexta_e_o_sabado() -> None:
    sexta = _ago(28, 14)
    assert resolver("amanhã", agora=sexta) == Dia(date(2026, 8, 29))


# --- o que pergunta ---


def _pergunta(texto: str, agora: datetime = AGORA) -> str:
    resolucao = resolver(texto, agora=agora)
    assert isinstance(resolucao, Ambigua), resolucao
    return resolucao.pergunta


def test_fim_de_semana_pergunta_pelo_sabado() -> None:
    pergunta = _pergunta("no fim de semana")
    assert "sábado, 29 de agosto" in pergunta
    assert "domingo" in pergunta.lower()


def test_domingo_pergunta_outro_dia() -> None:
    assert _pergunta("domingo") == TEXTO_DO_DOMINGO


def test_amanha_num_sabado_cai_no_domingo_e_pergunta() -> None:
    assert _pergunta("amanhã", agora=_ago(29, 14)) == TEXTO_DO_DOMINGO


def test_o_dia_da_semana_de_hoje_pergunta_qual() -> None:
    pergunta = _pergunta("terça")
    assert "25 de agosto" in pergunta
    assert "1º de setembro" in pergunta


def test_hora_de_1_a_7_sem_periodo_pergunta() -> None:
    assert "15h" in _pergunta("quinta às 3")


def test_passado_pergunta() -> None:
    assert _pergunta("hoje às 10h") == TEXTO_DO_PASSADO
    assert _pergunta("3/8") == TEXTO_DO_PASSADO
    assert _pergunta("hoje de manhã") == TEXTO_DO_PASSADO
    assert _pergunta("hoje de tarde", agora=_ago(25, 19, 30)) == TEXTO_DO_PASSADO


def test_dois_dias_pergunta_qual() -> None:
    pergunta = _pergunta("quinta ou sexta")
    assert "27 de agosto" in pergunta
    assert "28 de agosto" in pergunta


def test_noite_pergunta_pelo_fim_da_tarde() -> None:
    assert _pergunta("quinta à noite") == TEXTO_DA_NOITE


def test_data_inexistente_pergunta() -> None:
    assert _pergunta("31/9") == TEXTO_DA_DATA_INEXISTENTE
    assert _pergunta("dia 31", agora=_set(5, 14)) == TEXTO_DA_DATA_INEXISTENTE


def test_dia_do_mes_que_cai_no_domingo_pergunta() -> None:
    """20/09/2026 e domingo: a data existe, mas nao ha atendimento."""
    assert _pergunta("dia 20") == TEXTO_DO_DOMINGO


# --- o que nao reconhece, e o que nao pode derrubar ---


def test_texto_sem_data_nao_e_reconhecido() -> None:
    assert resolver("tanto faz", agora=AGORA) == NaoReconhecida()
    assert resolver("", agora=AGORA) == NaoReconhecida()


@pytest.mark.parametrize(
    "texto",
    [
        "9" * 10_000,
        "23793.38128 60000.000003 00000.000400 1 84340000012345",
        "15h75",
        "quinta às 99h",
        "33/13",
        "dia 0",
    ],
)
def test_lixo_nao_levanta(texto: str) -> None:
    resolver(texto, agora=AGORA)


def test_hora_com_minuto_invalido_e_ignorada() -> None:
    assert resolver("quinta 15h75", agora=AGORA) == Dia(date(2026, 8, 27))


def test_agora_sem_fuso_reprova() -> None:
    with pytest.raises(ValueError):
        resolver("amanhã", agora=datetime(2026, 8, 25, 14))


# --- a data absoluta ---


def test_data_e_hora_absolutas() -> None:
    assert data_e_hora_absolutas(_ago(27, 15)) == "quinta-feira, 27 de agosto, às 15h"
    assert data_e_hora_absolutas(_ago(27, 15, 30)) == "quinta-feira, 27 de agosto, às 15h30"


def test_data_e_hora_absolutas_converte_para_sao_paulo() -> None:
    em_utc = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
    assert data_e_hora_absolutas(em_utc) == "quinta-feira, 27 de agosto, às 15h"


def test_data_absoluta_usa_ordinal_no_dia_primeiro() -> None:
    assert data_absoluta(date(2026, 9, 1)) == "terça-feira, 1º de setembro"
    assert data_absoluta(date(2026, 8, 29)) == "sábado, 29 de agosto"

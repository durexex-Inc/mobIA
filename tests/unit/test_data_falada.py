"""A data falada pelo lead, resolvida. TEC-167, RN-11.3.

Puro: `agora` e sempre um literal com fuso. O `agora` padrao e o da card:
terca-feira, 25/08/2026, 14h.
"""

from datetime import UTC, date, datetime, timedelta
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
    janelas_para,
    resolver,
)
from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso

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
        # C1: mes e ano falados
        ("dia 3 de outubro", Dia(date(2026, 10, 3))),
        ("3 de setembro", Dia(date(2026, 9, 3))),
        ("dia 1º", Dia(date(2026, 9, 1))),
        ("1º/9", Dia(date(2026, 9, 1))),
        ("03/09/2027", Dia(date(2027, 9, 3))),
        ("3/9/27", Dia(date(2027, 9, 3))),
        # residual: "N de <mes>" tambem honra o ano falado, igual a dd/mm/aaaa
        # (2027-10-03 seria domingo -- usa-se o dia 4 nos dois testes que
        # falam outubro de 2027, ver o relato)
        ("4 de outubro de 2027", Dia(date(2027, 10, 4))),
        ("2 de agosto de 2027", Dia(date(2027, 8, 2))),
        ("4 de outubro de 27", Dia(date(2027, 10, 4))),
        # I3: hora nua de 7 nao e mais ambigua, vira Instante direto
        ("amanhã às 7", Instante(_ago(26, 7))),
        # I4: hora qualificada ou duas horas na frase nunca viram Instante
        ("quinta entre 14 e 16h", Dia(date(2026, 8, 27))),
        ("trabalho até as 18, pode ser quinta", Dia(date(2026, 8, 27))),
        ("quinta às 10 ou às 11", Dia(date(2026, 8, 27))),
        ("quinta a partir das 16h", Dia(date(2026, 8, 27))),
        # M10: "meio-dia" e "N hora(s) da tarde/manha"
        ("quinta meio-dia", Instante(_ago(27, 12))),
        ("amanhã 1 hora da tarde", Instante(_ago(26, 13))),
    ],
)
def test_resolve_expressoes_comuns(texto: str, esperado: object) -> None:
    assert resolver(texto, agora=AGORA) == esperado


def test_amanha_numa_sexta_e_o_sabado() -> None:
    sexta = _ago(28, 14)
    assert resolver("amanhã", agora=sexta) == Dia(date(2026, 8, 29))


def test_ano_falado_antes_do_mes_corrente_vira_ano_que_vem() -> None:
    """C1. Com agora = 20/12/2026, "5/1" e "5 de janeiro" ainda nao passaram
    -- sao o janeiro que vem, nao um 5/1 que ja foi."""
    agora = datetime(2026, 12, 20, 14, 0, tzinfo=SP)
    assert resolver("5/1", agora=agora) == Dia(date(2027, 1, 5))
    assert resolver("5 de janeiro", agora=agora) == Dia(date(2027, 1, 5))


def test_semana_que_vem_com_periodo() -> None:
    """I5. Periodo dito junto de "semana que vem" vira o periodo da Semana;
    hora sem periodo vira MANHA/TARDE pela mesma regra, e a hora exata cai."""
    assert resolver("semana que vem à tarde", agora=AGORA) == Semana(
        date(2026, 8, 31), PeriodoDoDia.TARDE
    )
    assert resolver("semana que vem as 16h", agora=AGORA) == Semana(
        date(2026, 8, 31), PeriodoDoDia.TARDE
    )


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


def test_hora_6_ainda_pergunta_mas_7_nao_mais() -> None:
    """I3. So 1 a 6 ficam ambiguos (13h..18h cabem no atendimento); 7 vira
    Instante direto (ver "amanhã às 7" no parametrize acima)."""
    assert "18h" in _pergunta("quinta às 6")


def test_passado_pergunta() -> None:
    assert _pergunta("hoje às 10h") == TEXTO_DO_PASSADO
    assert _pergunta("3/8") == TEXTO_DO_PASSADO
    assert _pergunta("hoje de manhã") == TEXTO_DO_PASSADO
    assert _pergunta("hoje de tarde", agora=_ago(25, 19, 30)) == TEXTO_DO_PASSADO


def test_passado_com_ano_falado_pergunta() -> None:
    """C1. Ano falado nao poupa de "ja passou": "3/8/2026" e antes de hoje
    (25/08/2026), mesmo com o ano dito por extenso."""
    assert _pergunta("3/8/2026") == TEXTO_DO_PASSADO


def test_passado_com_mes_e_ano_por_extenso_pergunta() -> None:
    """Residual da revisao final: `_DIA_DE_MES_EXTENSO` ignorava o ano
    falado -- "2 de agosto de 2025" virava 02/08/2026 (ano corrente), no
    futuro, em vez do 02/08/2025 que o lead disse, que ja passou."""
    assert _pergunta("2 de agosto de 2025") == TEXTO_DO_PASSADO


def test_dois_dias_pergunta_qual() -> None:
    pergunta = _pergunta("quinta ou sexta")
    assert "27 de agosto" in pergunta
    assert "28 de agosto" in pergunta


def test_dois_dias_nao_descarta_o_dia_de_hoje_falado_por_nome() -> None:
    """Regressao: um return precoce no "hoje ou a proxima" descartava o
    segundo dia da frase. "terca" e o dia de hoje (AGORA e terca-feira), e
    "segunda" nao pode sumir da pergunta."""
    pergunta = _pergunta("pode ser segunda ou terça de tarde")
    assert "31 de agosto" in pergunta
    assert "25 de agosto" in pergunta


def test_dois_dias_nao_descarta_amanha() -> None:
    """Regressao: o mesmo return precoce descartava "amanha" quando o outro
    dia da frase caia no dia de hoje falado por nome."""
    pergunta = _pergunta("amanhã ou terça")
    assert "26 de agosto" in pergunta
    assert "25 de agosto" in pergunta


def test_dois_dias_nao_descarta_sabado_quando_o_outro_e_domingo() -> None:
    """Regressao: o return precoce de "domingo" descartava o sabado dito na
    mesma frase. Domingo com outro dia vira a pergunta do fim de semana, que
    serve para qualquer dia -- nao a generica de TEXTO_DO_DOMINGO."""
    pergunta = _pergunta("sábado ou domingo")
    assert "sábado, 29 de agosto" in pergunta
    assert "domingos" in pergunta


def test_dois_dias_concordancia_no_texto() -> None:
    """I2. "Pode ser {dia}?" sem artigo: "no segunda-feira" soava errado."""
    pergunta = _pergunta("domingo ou segunda")
    assert pergunta.endswith("Pode ser segunda-feira, 31 de agosto?")


def test_hoje_ou_proxima_concordancia_no_texto() -> None:
    """I2. Sem "a proxima," fixo: "a proxima, sabado" tambem soava errado."""
    agora_sabado = datetime(2026, 8, 29, 10, 0, tzinfo=SP)
    assert _pergunta("sábado", agora=agora_sabado) == (
        "Você quer dizer hoje, sábado, 29 de agosto, ou sábado, 5 de setembro?"
    )


def test_noite_pergunta_pelo_fim_da_tarde() -> None:
    assert _pergunta("quinta à noite") == TEXTO_DA_NOITE


def test_data_inexistente_pergunta() -> None:
    assert _pergunta("31/9") == TEXTO_DA_DATA_INEXISTENTE
    assert _pergunta("dia 31", agora=_set(5, 14)) == TEXTO_DA_DATA_INEXISTENTE


def test_mes_por_extenso_inexistente_pergunta() -> None:
    """C1. Setembro nao tem dia 31, esteja o mes por extenso ou nao."""
    assert _pergunta("31 de setembro") == TEXTO_DA_DATA_INEXISTENTE


def test_dia_do_mes_que_cai_no_domingo_pergunta() -> None:
    """20/09/2026 e domingo: a data existe, mas nao ha atendimento."""
    assert _pergunta("dia 20") == TEXTO_DO_DOMINGO


def test_fim_de_semana_apos_as_18h_num_sabado_oferece_o_seguinte() -> None:
    """M11. As 18h de sabado so resta 1h de atendimento -- perto demais para
    valer como oferta de "hoje"."""
    agora = datetime(2026, 8, 29, 18, 0, tzinfo=SP)
    assert "5 de setembro" in _pergunta("fim de semana", agora=agora)


# --- o que nao reconhece, e o que nao pode derrubar ---


def test_texto_sem_data_nao_e_reconhecido() -> None:
    assert resolver("tanto faz", agora=AGORA) == NaoReconhecida()
    assert resolver("", agora=AGORA) == NaoReconhecida()


def test_hora_qualificada_sem_dia_nem_periodo_nao_e_reconhecida() -> None:
    """I4. Sem dia nem periodo sobrando, a hora descartada nao deixa nada."""
    assert resolver("antes das 10", agora=AGORA) == NaoReconhecida()


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


# --- a ponte com o motor ---


def _janela(inicio: datetime, minutos: int = 60) -> Intervalo:
    return Intervalo(inicio, inicio + timedelta(minutes=minutos))


def _janelas(texto: str, ocupados: tuple[Intervalo, ...] = ()) -> object:
    return janelas_para(
        resolver(texto, agora=AGORA),
        agora=AGORA,
        jornada_inicio=9,
        jornada_fim=19,
        ocupados=list(ocupados),
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
    )


def test_quinta_de_manha_propoe_so_a_manha_de_quinta() -> None:
    """O primeiro cenario da card."""
    assert _janelas("pode ser quinta de manhã") == [
        _janela(_ago(27, 9)),
        _janela(_ago(27, 9, 30)),
        _janela(_ago(27, 10)),
    ]


def test_instante_livre_devolve_so_ele() -> None:
    assert _janelas("quinta às 15h") == [_janela(_ago(27, 15))]


def test_instante_ocupado_devolve_as_janelas_do_dia() -> None:
    ocupado = Intervalo(_ago(27, 15), _ago(27, 16))
    assert _janelas("quinta às 15h", (ocupado,)) == [
        _janela(_ago(27, 9)),
        _janela(_ago(27, 9, 30)),
        _janela(_ago(27, 10)),
    ]


def test_instante_fora_da_grade_devolve_as_janelas_do_dia() -> None:
    assert _janelas("quinta às 15h10") == [
        _janela(_ago(27, 9)),
        _janela(_ago(27, 9, 30)),
        _janela(_ago(27, 10)),
    ]


def test_dia_propoe_janelas_do_dia() -> None:
    assert _janelas("sexta") == [
        _janela(_ago(28, 9)),
        _janela(_ago(28, 9, 30)),
        _janela(_ago(28, 10)),
    ]


def test_semana_propoe_uma_por_dia_da_semana_que_vem() -> None:
    assert _janelas("semana que vem") == [
        _janela(_ago(31, 9)),
        _janela(_set(1, 9)),
        _janela(_set(2, 9)),
    ]


def test_semana_com_periodo_propoe_a_primeira_janela_de_cada_dia() -> None:
    """I5. Com periodo, um dia de cada vez -- segunda, terca, quarta -- e so
    a primeira janela de cada, ate 3."""
    assert _janelas("semana que vem à tarde") == [
        _janela(_ago(31, 12)),
        _janela(_set(1, 12)),
        _janela(_set(2, 12)),
    ]


def test_ambigua_e_nao_reconhecida_passam_sem_chamar_o_motor() -> None:
    assert isinstance(_janelas("no fim de semana"), Ambigua)
    assert _janelas("tanto faz") == NaoReconhecida()

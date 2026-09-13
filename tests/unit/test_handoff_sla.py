from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from mobia.domain.handoff.sla import (
    PRAZO_PADRAO_MINUTOS,
    PRAZO_QUENTE_MINUTOS,
    limite_de_aceite,
    prazo_em_minutos,
)

SP = ZoneInfo("America/Sao_Paulo")


def _em_sp(ano: int, mes: int, dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(ano, mes, dia, hora, minuto, tzinfo=SP)


def test_quente_tem_quinze_minutos() -> None:
    assert prazo_em_minutos("QUENTE") == PRAZO_QUENTE_MINUTOS == 15


def test_morno_e_frio_tem_quatro_horas() -> None:
    assert prazo_em_minutos("MORNO") == PRAZO_PADRAO_MINUTOS == 240
    assert prazo_em_minutos("FRIO") == PRAZO_PADRAO_MINUTOS


def test_temperatura_nula_conta_como_nao_quente() -> None:
    """D2: dar 15 minutos a um lead cuja temperatura ninguem calculou
    inventaria urgencia. NULL e "linha anterior a TEC-151", nao FRIO."""
    assert prazo_em_minutos(None) == PRAZO_PADRAO_MINUTOS


def test_dentro_da_jornada_soma_direto() -> None:
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 10, 0),
        minutos=15,
        jornada_inicio=9,
        jornada_fim=18,
        fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 15, 10, 15)


def test_fora_da_jornada_comeca_na_proxima_abertura() -> None:
    """Terceiro cenario do Gherkin: as 22h de terca conta a partir das 9h de quarta."""
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 22, 0),
        minutos=15,
        jornada_inicio=9,
        jornada_fim=18,
        fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 16, 9, 15)


def test_antes_da_abertura_no_mesmo_dia_espera_a_abertura() -> None:
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 6, 0),
        minutos=30,
        jornada_inicio=9,
        jornada_fim=18,
        fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 15, 9, 30)


def test_o_que_nao_cabe_antes_do_fechamento_continua_no_dia_seguinte() -> None:
    """Comecar as 17h50 com 30 minutos: 10 antes do fechamento, 20 depois."""
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 17, 50),
        minutos=30,
        jornada_inicio=9,
        jornada_fim=18,
        fuso=SP,
    )
    assert limite == _em_sp(2026, 9, 16, 9, 20)


def test_um_prazo_maior_que_o_dia_atravessa_varios_dias() -> None:
    """Quatro horas comecando as 17h30 de uma jornada que fecha as 18h."""
    limite = limite_de_aceite(
        inicio=_em_sp(2026, 9, 15, 17, 30),
        minutos=PRAZO_PADRAO_MINUTOS,
        jornada_inicio=9,
        jornada_fim=18,
        fuso=SP,
    )
    # 30 minutos hoje, 210 restantes a partir das 9h de amanha.
    assert limite == _em_sp(2026, 9, 16, 12, 30)


def test_jornada_degenerada_levanta() -> None:
    """M4 da revisao final: a validacao (Task 1, ledger) nao tinha teste --
    quem apagasse o `raise` ficaria com a suite verde e um `while True` que
    nunca termina, porque a janela disponivel por dia nunca seria positiva.
    """
    import pytest

    with pytest.raises(ValueError, match="degenerada"):
        limite_de_aceite(
            inicio=_em_sp(2026, 9, 15, 10, 0),
            minutos=15,
            jornada_inicio=18,
            jornada_fim=9,
            fuso=SP,
        )


def test_instante_ingenuo_levanta() -> None:
    """Mesma razao de `horario_permite_envio`: `astimezone` num naive assume o
    fuso do SISTEMA, e esta maquina difere do runner do CI."""
    import pytest

    with pytest.raises(ValueError, match="tzinfo"):
        limite_de_aceite(
            inicio=datetime(2026, 9, 15, 10, 0),
            minutos=15,
            jornada_inicio=9,
            jornada_fim=18,
            fuso=SP,
        )


def test_o_limite_devolvido_e_aware_e_em_utc() -> None:
    """`tzinfo is not None` nao provaria UTC -- `limite_de_aceite` recusa
    `inicio` ingenuo, entao o resultado e sempre aware, mesmo trocando o
    `.astimezone(UTC)` final por `.astimezone(fuso)`. `utcoffset() ==
    timedelta(0)` e a assercao que so passa mesmo em UTC.
    """
    limite = limite_de_aceite(
        inicio=datetime(2026, 9, 15, 13, 0, tzinfo=UTC),
        minutos=15,
        jornada_inicio=9,
        jornada_fim=18,
        fuso=SP,
    )
    assert limite.utcoffset() == timedelta(0)

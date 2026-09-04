"""A janela de horario de envio automatico. TEC-185, RN-13.3.

O nome do arquivo e `horario` e nao `janela` de proposito: `test_janela.py`
ja existe neste diretorio e pertence a janela de CONTEXTO. Colisao de
basename entre unit e integration aborta a coleta da suite inteira.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.outbound.horario import horario_permite_envio

FUSO = ZoneInfo("America/Sao_Paulo")


def _local(hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    """Um instante aware de 04/09/2026, dado em hora LOCAL de Sao Paulo."""
    return datetime(2026, 9, 4, hora, minuto, segundo, tzinfo=FUSO)


def _permite(momento: datetime) -> bool:
    """A janela default da card: 9h as 20h."""
    return horario_permite_envio(momento=momento, inicio=9, fim=20, fuso=FUSO)


def test_o_meio_da_tarde_permite() -> None:
    assert _permite(_local(14, 30)) is True


def test_antes_das_nove_recusa() -> None:
    assert _permite(_local(8, 59)) is False


def test_a_madrugada_recusa() -> None:
    """A historia da card, literal: "nao quero receber mensagem da imobiliaria
    as tres da manha"."""
    assert _permite(_local(3)) is False


def test_as_nove_em_ponto_permite() -> None:
    """A borda de baixo e inclusiva: o criterio de aceite do adiamento manda o
    follow-up "as 9h do dia seguinte"."""
    assert _permite(_local(9, 0)) is True


def test_as_vinte_em_ponto_permite() -> None:
    """Os dois primeiros criterios de aceite da card sao esta mesma borda: um
    lead QUENTE que parou de falar as 18h vence a primeira tentativa (+2h) as
    20h em ponto, e "um disparo agendado para exatamente 20h" e enviado."""
    assert _permite(_local(20, 0)) is True


def test_as_vinte_com_tres_segundos_permite() -> None:
    """A regressao que separa "passa no teste" de "funciona no cron".

    O cron dispara em `minute={0, 5, ...}`, mas `agora` e lido DENTRO do job --
    na pratica 20:00:00,04. Com uma comparacao de `time` cheio esse sweep
    ficaria FORA da janela, e este teste seria o unico a notar: o da borda
    exata passaria, e producao falharia o criterio de aceite.
    """
    assert _permite(_local(20, 0, 3)) is True


def test_as_vinte_e_cinco_recusa() -> None:
    """O outro lado da mesma truncagem: os segundos morrem, o minuto nao."""
    assert _permite(_local(20, 5)) is False


def test_o_momento_ingenuo_levanta() -> None:
    """Um naive faz `astimezone` assumir o fuso do SISTEMA -- UTC-3 nesta
    maquina, UTC no runner do CI --, e o erro seria invisivel em um dos dois."""
    with pytest.raises(ValueError, match="tzinfo"):
        horario_permite_envio(momento=datetime(2026, 9, 4, 14, 0), inicio=9, fim=20, fuso=FUSO)


def test_a_conversao_de_fuso_acontece_de_verdade() -> None:
    """23h UTC e 20h em Sao Paulo (dentro); 00h UTC e 21h (fora).

    E o teste que morre se alguem ler `momento.hour` direto em vez de
    converter -- pelo relogio UTC as duas respostas se invertem.
    """
    assert _permite(datetime(2026, 9, 4, 23, 0, tzinfo=UTC)) is True
    assert _permite(datetime(2026, 9, 5, 0, 0, tzinfo=UTC)) is False


def test_a_janela_configurada_e_lida() -> None:
    """Os parametros nao sao decorativos: uma janela de madrugada permite as 3h
    e recusa as 14h, invertendo as duas respostas do default."""
    assert horario_permite_envio(momento=_local(3), inicio=0, fim=5, fuso=FUSO) is True
    assert horario_permite_envio(momento=_local(14), inicio=0, fim=5, fuso=FUSO) is False

"""O recorte do painel e a recusa do filtro invalido. TEC-190, RN-17.3."""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.metricas.filtros import FiltroInvalido, montar_recorte

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def test_o_dia_comeca_a_meia_noite_do_fuso_e_nao_de_utc() -> None:
    """Sem isto, o lead da madrugada cai no dia errado.

    Sao Paulo e UTC-3, entao 2026-08-01 00:00 local e 2026-08-01 03:00Z.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.inicio == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)


def test_o_intervalo_e_semiaberto_e_inclui_o_dia_final_inteiro() -> None:
    """`fim` e a meia-noite do dia SEGUINTE, entao 22/08 23:59 entra.

    Um `<=` sobre 22/08 23:59:59 deixaria de fora o que acontecesse no ultimo
    segundo, e um `<= 23:59:59.999999` e a mesma aproximacao escrita pior.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.fim == datetime(2026, 8, 23, 3, 0, tzinfo=UTC)


def test_um_dia_so_e_periodo_valido() -> None:
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 1), fuso=SAO_PAULO)

    assert recorte.fim > recorte.inicio


def test_de_depois_de_ate_e_recusado() -> None:
    """422, e nao funil vazio: vazio se le como "nenhum lead"."""
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(de=date(2026, 8, 22), ate=date(2026, 8, 1), fuso=SAO_PAULO)

    assert erro.value.campo == "de"


def test_doze_meses_exatos_e_periodo_valido() -> None:
    """O mesmo dia, um ano depois -- o limite e inclusivo."""
    recorte = montar_recorte(de=date(2025, 9, 24), ate=date(2026, 9, 24), fuso=SAO_PAULO)

    assert recorte.fim > recorte.inicio


def test_doze_meses_e_um_dia_e_recusado() -> None:
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(de=date(2025, 9, 24), ate=date(2026, 9, 25), fuso=SAO_PAULO)

    assert erro.value.campo == "ate"
    assert "12 meses" in str(erro.value)


def test_o_exemplo_da_card_e_recusado() -> None:
    """O cenario 3 do Gherkin da TEC-316."""
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(de=date(2025, 1, 1), ate=date(2026, 9, 24), fuso=SAO_PAULO)

    assert erro.value.campo == "ate"


def test_29_de_fevereiro_sem_ano_bissexto_seguinte_vira_28() -> None:
    """O limite de um `de` em ano bissexto e 28/02 do ano seguinte, nao 01/03
    nem uma recusa por o dia nao existir."""
    recorte = montar_recorte(de=date(2024, 2, 29), ate=date(2025, 2, 28), fuso=SAO_PAULO)

    assert recorte.fim > recorte.inicio

    with pytest.raises(FiltroInvalido):
        montar_recorte(de=date(2024, 2, 29), ate=date(2025, 3, 1), fuso=SAO_PAULO)


def test_temperatura_fora_do_vocabulario_e_recusada() -> None:
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(
            de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, temperatura="MORNA"
        )

    assert erro.value.campo == "temperatura"
    assert "MORNA" in str(erro.value)


def test_intencao_fora_do_vocabulario_e_recusada() -> None:
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(
            de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, intencao="BANANA"
        )

    assert erro.value.campo == "intencao"


def test_os_valores_do_vocabulario_passam() -> None:
    recorte = montar_recorte(
        de=date(2026, 8, 1),
        ate=date(2026, 8, 22),
        fuso=SAO_PAULO,
        temperatura="QUENTE",
        intencao="COMPRA",
    )

    assert recorte.temperatura == "QUENTE"
    assert recorte.intencao == "COMPRA"


def test_canal_e_texto_livre_e_nao_e_recusado() -> None:
    """`messages.channel` e `String(32)` sem CHECK: nao ha vocabulario fechado
    para recusar contra. Hoje so `whatsapp` e produzido; o canal web e a
    TEC-124.
    """
    recorte = montar_recorte(
        de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO, canal="web"
    )

    assert recorte.canal == "web"


def test_filtro_ausente_fica_nulo() -> None:
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.canal is None
    assert recorte.intencao is None
    assert recorte.temperatura is None
    assert recorte.corretor_id is None


def test_sem_corretor_o_recorte_nasce_com_o_campo_nulo() -> None:
    """O campo continua existindo no `Recorte` -- a consulta que o consome ja
    esta escrita e correta, esperando quem escreva `handoffs.corretor_id`. O
    que a borda recusa e o PEDIDO, nao a forma do recorte.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 22), fuso=SAO_PAULO)

    assert recorte.corretor_id is None


def test_filtro_por_corretor_e_recusado_enquanto_ninguem_aloca() -> None:
    """`handoffs.corretor_id` NUNCA e escrito em producao.

    A Emenda E-01 da RN-16.2 diz isso por extenso, e a TEC-166 nao mudou
    isso -- ela aloca corretor ao agendamento, nao ao handoff --, entao a
    coluna e nula em toda linha. Filtrar por ela devolvia 200 com o funil
    inteiro zerado, e a gerente leria "este corretor nao recebeu lead
    nenhum" sobre QUALQUER corretor.

    Zero universal com cara de medicao e pior que recusa: e a mesma classe de
    defeito que a D1 recusou para `Agendado`.
    """
    with pytest.raises(FiltroInvalido) as erro:
        montar_recorte(
            de=date(2026, 8, 1),
            ate=date(2026, 8, 22),
            fuso=SAO_PAULO,
            corretor_id=uuid.uuid4(),
        )

    assert erro.value.campo == "corretorId"
    assert "o funil ainda nao sabe qual corretor atende cada handoff" in str(erro.value)

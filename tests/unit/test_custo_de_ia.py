"""As contas puras do painel de custo de IA. TEC-191, D1 e D3 do desenho."""

from decimal import Decimal

from mobia.domain.metricas.custo import avaliar_orcamento, media, orcamento_do_periodo


def test_media_com_denominador_zero_e_nula() -> None:
    """Nula, e nao zero: "nao houve conversa" nao e "custou zero"."""
    assert media(Decimal("0"), 0) is None
    assert media(Decimal("0.84"), 0) is None


def test_media_divide_o_total() -> None:
    assert media(Decimal("0.84"), 7) == Decimal("0.120000")


def test_trinta_dias_e_o_orcamento_mensal_inteiro() -> None:
    assert orcamento_do_periodo(Decimal("100"), dias=30) == Decimal("100")


def test_quinze_dias_e_metade() -> None:
    assert orcamento_do_periodo(Decimal("100"), dias=15) == Decimal("50")


def test_oitenta_por_cento_exato_acende_o_alerta() -> None:
    """O terceiro cenario da card: orcamento de 100, custo de 80."""
    orcamento = avaliar_orcamento(Decimal("100"), dias=30, consumido=Decimal("80"))
    assert orcamento.alerta is True
    assert orcamento.consumido_pct == Decimal("80.00")


def test_abaixo_de_oitenta_nao_acende() -> None:
    orcamento = avaliar_orcamento(Decimal("100"), dias=30, consumido=Decimal("79.99"))
    assert orcamento.alerta is False


def test_o_limiar_e_sobre_o_orcamento_do_periodo_e_nao_o_mensal() -> None:
    """Em 15 dias o orcamento e 50: gastar 40 ja e 80%."""
    orcamento = avaliar_orcamento(Decimal("100"), dias=15, consumido=Decimal("40"))
    assert orcamento.do_periodo_usd == Decimal("50")
    assert orcamento.alerta is True

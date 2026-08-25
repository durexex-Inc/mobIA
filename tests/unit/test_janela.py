import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.context.janela import deve_regenerar, dividir


def mensagens(quantidade: int) -> list[object]:
    """Dubles posicionais: `dividir` so olha a ordem, nao o conteudo."""
    base = datetime.now(UTC)
    return [
        type("M", (), {"id": uuid.uuid4(), "created_at": base + timedelta(seconds=i)})()
        for i in range(quantidade)
    ]


def test_gatilho_dispara_em_quarenta_e_nao_em_trinta_e_nove() -> None:
    assert deve_regenerar(40, gatilho=40) is True
    assert deve_regenerar(39, gatilho=40) is False
    assert deve_regenerar(41, gatilho=40) is True


def test_dividir_deixa_exatamente_o_piso() -> None:
    """A invariante das vinte, no menor nivel possivel.

    Se `dividir` dobrasse tudo, a marca colaria no presente e o turno seguinte a
    cada resumo teria uma ou duas mensagens literais.
    """
    a_dobrar, a_manter = dividir(mensagens(40), minimas=20)

    assert len(a_dobrar) == 20
    assert len(a_manter) == 20


def test_dividir_nunca_dobra_abaixo_do_piso() -> None:
    """Com menos que o piso nao ha o que dobrar, mesmo que alguem chame."""
    a_dobrar, a_manter = dividir(mensagens(15), minimas=20)

    assert a_dobrar == []
    assert len(a_manter) == 15


def test_dividir_preserva_a_ordem_e_nao_perde_ninguem() -> None:
    todas = mensagens(40)
    a_dobrar, a_manter = dividir(todas, minimas=20)

    assert a_dobrar + a_manter == todas, "nenhuma mensagem some nem troca de lugar"

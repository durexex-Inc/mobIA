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


def test_dividir_so_dobra_abaixo_do_piso_com_o_opt_in() -> None:
    """O piso e default; ceder e escolha explicita de quem chama.

    Sem a flag, vinte literais nao produzem nada a dobrar -- e o que fazia o
    laco do estouro cair direto no descarte, jogando fora dezenove das vinte
    mensagens do lead em vez de dobra-las.
    """
    a_dobrar, a_manter = dividir(mensagens(20), minimas=20)
    assert a_dobrar == []
    assert len(a_manter) == 20

    a_dobrar, a_manter = dividir(mensagens(20), minimas=20, piso_pode_ceder=True)
    assert len(a_dobrar) == 19
    assert len(a_manter) == 1, "a mais recente fica: e a fala a que o modelo tem de responder"


def test_dividir_com_o_opt_in_preserva_a_ordem_e_nao_perde_ninguem() -> None:
    todas = mensagens(20)
    a_dobrar, a_manter = dividir(todas, minimas=20, piso_pode_ceder=True)

    assert a_dobrar + a_manter == todas, "ceder o piso nao pode perder mensagem"


def test_dividir_com_o_opt_in_nao_dobra_a_ultima_mensagem() -> None:
    """Uma literal sozinha nao tem o que dobrar nem com o piso cedendo.

    E o que garante que o laco do estouro termina: o degrau de dobrar abaixo
    do piso para de ter efeito e o proximo degrau assume.
    """
    a_dobrar, a_manter = dividir(mensagens(1), minimas=20, piso_pode_ceder=True)

    assert a_dobrar == []
    assert len(a_manter) == 1

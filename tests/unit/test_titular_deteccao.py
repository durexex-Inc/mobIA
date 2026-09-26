import pytest

from mobia.domain.optout.deteccao import pediu_optout
from mobia.domain.titular.deteccao import pedido_de_titular
from mobia.domain.titular.vocabulario import TipoDeSolicitacao


@pytest.mark.parametrize(
    "texto",
    [
        "quero apagar meus dados",
        "Apague meus dados, por favor",
        "excluir meus dados",
        "deletem os meus dados",
        "podem esquecer meus dados?",
        "quero que apaguem todos os meus dados pessoais",
    ],
)
def test_pedido_de_eliminacao(texto: str) -> None:
    assert pedido_de_titular(texto) is TipoDeSolicitacao.ELIMINACAO


@pytest.mark.parametrize(
    "texto",
    [
        "quero meus dados",
        "quais dados vocês têm de mim?",
        "quero ver os meus dados",
        "me mandem uma cópia dos meus dados",
    ],
)
def test_pedido_de_acesso(texto: str) -> None:
    assert pedido_de_titular(texto) is TipoDeSolicitacao.ACESSO


@pytest.mark.parametrize(
    "texto",
    [
        "remover meu contato",
        "parar",
        "quero um apartamento",
        "os dados do imóvel estão errados",
        "vocês têm os dados do condomínio?",
        "não quero apagar meus dados",
        "",
    ],
)
def test_nao_e_pedido_de_titular(texto: str) -> None:
    assert pedido_de_titular(texto) is None


@pytest.mark.parametrize(
    "texto",
    [
        "quero apagar meus dados",
        "Apague meus dados, por favor",
        "excluir meus dados",
        "deletem os meus dados",
        "podem esquecer meus dados?",
        "quero que apaguem todos os meus dados pessoais",
        "quero meus dados",
        "quais dados vocês têm de mim?",
        "quero ver os meus dados",
        "me mandem uma cópia dos meus dados",
    ],
)
def test_pedido_de_titular_nao_depende_do_resultado_do_optout(texto: str) -> None:
    """A precedencia e sobre o QUE o turno faz, nao sobre os dois detectores
    concordarem. `pediu_optout` pode devolver qualquer coisa para estas frases --
    o unico contrato aqui e o de `pedido_de_titular`.
    """
    pedido_de_titular(texto)


def test_remover_contato_e_optout_mas_nao_pedido_de_titular() -> None:
    """A colisao nomeada no desenho D3: fala de CONTATO e opt-out, fala de
    DADOS e pedido de titular. "remover meu contato" e so o primeiro.
    """
    assert pedido_de_titular("remover meu contato") is None
    assert pediu_optout("remover meu contato") is True

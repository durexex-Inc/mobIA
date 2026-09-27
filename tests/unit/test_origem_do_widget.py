"""A comparacao do `Origin` do handshake do widget. TEC-365, D1 e D3."""

import pytest

from mobia.api.routes.widget import origem_permitida

PERMITIDAS = frozenset({"https://painel.exemplo.com.br", "http://localhost:3000"})


@pytest.mark.parametrize(
    "origem",
    ["https://painel.exemplo.com.br", "HTTPS://Painel.Exemplo.com.br", "http://localhost:3000"],
)
def test_origem_da_lista_passa(origem: str) -> None:
    assert origem_permitida(origem, PERMITIDAS)


@pytest.mark.parametrize(
    "origem",
    [
        None,
        "null",
        "",
        "https://copia-do-site.com",
        # Subdominio nao herda: a comparacao e exata.
        "https://x.painel.exemplo.com.br",
        # Outro esquema e outra porta sao outra origem.
        "http://painel.exemplo.com.br",
        "http://localhost:3001",
    ],
)
def test_origem_fora_da_lista_e_recusada(origem: str | None) -> None:
    assert not origem_permitida(origem, PERMITIDAS)


def test_lista_vazia_recusa_ate_a_origem_do_painel() -> None:
    assert not origem_permitida("https://painel.exemplo.com.br", frozenset())

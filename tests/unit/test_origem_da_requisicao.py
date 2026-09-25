"""O `ip` que a trilha grava tem de ser IP. TEC-206, Review Focus 1.

`resolver_ip` devolve o que o socket ou o `X-Forwarded-For` disserem, e a
coluna e `inet`: um valor que nao e endereco viraria `DataError` no INSERT --
e um 403 viraria 500.
"""

import pytest

from mobia.api.middleware import ip_valido_ou_nulo


@pytest.mark.parametrize("texto", ["127.0.0.1", "::1", "2001:db8::1"])
def test_ip_valido_passa(texto: str) -> None:
    assert ip_valido_ou_nulo(texto) == texto


@pytest.mark.parametrize("texto", [None, "", "testclient", "1.2.3.4:5678", "abc", "999.1.1.1"])
def test_o_que_nao_e_ip_vira_nulo(texto: str | None) -> None:
    assert ip_valido_ou_nulo(texto) is None


@pytest.mark.parametrize("texto", ["fe80::1%eth0", "fe80::1%1"])
def test_ipv6_com_zona_vira_nulo(texto: str) -> None:
    """O `inet` do Postgres recusa o `%zona`; aceitar aqui faria um 403 virar 500."""
    assert ip_valido_ou_nulo(texto) is None

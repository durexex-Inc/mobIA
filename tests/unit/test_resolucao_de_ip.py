"""De qual valor sai o IP que o limitador conta (TEC-205, D7)."""

from mobia.api.middleware import resolver_ip


def test_sem_confiar_usa_o_socket() -> None:
    assert (
        resolver_ip(
            socket_host="10.0.0.1",
            forwarded_for="203.0.113.7",
            confiar_em_forwarded_for=False,
        )
        == "10.0.0.1"
    )


def test_confiando_usa_o_ultimo_salto() -> None:
    """O ULTIMO, nao o primeiro: e o unico que o proxy imediato escreveu, e
    portanto o unico que o cliente nao controla. Confiar no primeiro deixaria
    qualquer um escapar do limite mandando um X-Forwarded-For forjado.
    """
    assert (
        resolver_ip(
            socket_host="10.0.0.1",
            forwarded_for="1.2.3.4, 5.6.7.8, 203.0.113.7",
            confiar_em_forwarded_for=True,
        )
        == "203.0.113.7"
    )


def test_confiando_sem_header_cai_no_socket() -> None:
    assert (
        resolver_ip(socket_host="10.0.0.1", forwarded_for=None, confiar_em_forwarded_for=True)
        == "10.0.0.1"
    )


def test_confiando_com_header_vazio_cai_no_socket() -> None:
    assert (
        resolver_ip(socket_host="10.0.0.1", forwarded_for="  ,  ", confiar_em_forwarded_for=True)
        == "10.0.0.1"
    )


def test_sem_socket_e_sem_header_devolve_none() -> None:
    """Cliente sem endereco existe -- ASGI de teste, socket unix. Quem chama
    trata None deixando passar (fail-open).
    """
    assert resolver_ip(socket_host=None, forwarded_for=None, confiar_em_forwarded_for=False) is None


def test_o_valor_e_truncado_para_caber_na_coluna() -> None:
    """`rate_limit_events.chave` e String(64), e o header e entrada externa:
    sem teto, um X-Forwarded-For longo viraria erro de INSERT na hora de
    registrar justamente o abuso.
    """
    longo = "x" * 500
    assert (
        len(resolver_ip(socket_host=None, forwarded_for=longo, confiar_em_forwarded_for=True) or "")
        <= 64
    )

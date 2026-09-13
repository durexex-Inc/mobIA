"""O vocabulario de kinds de saida e os grupos. TEC-273."""

from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA, KINDS_DA_RESPOSTA, grupo_de


def test_as_duas_partes_da_resposta_sao_um_grupo() -> None:
    """Qualquer parte da resposta devolve as DUAS, e nao so ela.

    E o que faz uma falha retentavel na parte 2 liberar tambem a reserva da
    parte 1: sem isso, a retentativa reentrega so a parte 2, com o texto de
    uma geracao nova, colada a parte 1 da geracao velha.
    """
    assert grupo_de(KIND_DA_RESPOSTA) == KINDS_DA_RESPOSTA
    assert grupo_de(KINDS_DA_RESPOSTA[1]) == KINDS_DA_RESPOSTA


def test_kind_sem_grupo_devolve_so_ele_mesmo() -> None:
    """O chamador libera `grupo_de(kind)` sempre, sem ramo para o caso comum.

    Devolver `()` obrigaria o port a lembrar de somar o proprio kind, e
    esquecer disso deixaria presa justamente a reserva que falhou.
    """
    assert grupo_de("ack") == ("ack",)


def test_as_fichas_nao_formam_grupo() -> None:
    """Decisao D1, e nao omissao.

    A retentativa de uma apresentacao REPETE o lote persistido (TEC-275), sem
    chamar o modelo -- nao ha duas geracoes para misturar. A reserva de uma
    ficha e o que impede o lead de receber a mesma ficha duas vezes, e
    liberar em grupo esvaziaria o sinal de que `_continuar_entrega` depende.
    """
    for kind in ("ficha_1", "ficha_2", "ficha_3"):
        assert grupo_de(kind) == (kind,)

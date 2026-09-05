"""O maximo absoluto de mensagens automaticas sem resposta. TEC-188, RN-13.7."""

from mobia.domain.outbound.antispam import MAXIMO_SEM_RESPOSTA, antispam_permite_envio


def test_lead_que_nao_recebeu_nada_pode_receber() -> None:
    assert antispam_permite_envio(ja_enviadas=0) is True


def test_uma_abaixo_do_maximo_ainda_pode() -> None:
    """Tres nao respondidas ainda permitem a quarta, e a quarta e a ultima."""
    assert antispam_permite_envio(ja_enviadas=MAXIMO_SEM_RESPOSTA - 1) is True


def test_no_maximo_nao_pode() -> None:
    assert antispam_permite_envio(ja_enviadas=MAXIMO_SEM_RESPOSTA) is False


def test_acima_do_maximo_continua_nao_podendo() -> None:
    """A defesa contra um `!=` no lugar do `<`.

    Uma contagem acima do maximo nao deveria existir hoje, mas se existir --
    um segundo produtor de automacao (TEC-171), ou uma cadencia mais longa via
    RF-19 -- ela tem de continuar barrando, e nao voltar a permitir.
    """
    assert antispam_permite_envio(ja_enviadas=MAXIMO_SEM_RESPOSTA + 1) is False


def test_o_maximo_e_o_numero_da_regra() -> None:
    """RN-13.7 fixa o numero em 4 mensagens sem resposta consecutivas.

    Este teste fixa o numero na base de codigo de modo que uma mudanca nele
    seja deliberada e visivel. Mas NAO detecta se o numero foi derivado de
    `CADENCIA` -- hoje `len(CADENCIA[Temperatura.QUENTE])` tambem e 4, entao
    nenhuma assercao sobre valor consegue discernir um 4 escrito a mao de um
    derivado. O que protege contra derivacao e o comentario no `MAXIMO_SEM_RESPOSTA`
    e a revisao, nao este teste.
    """
    assert MAXIMO_SEM_RESPOSTA == 4

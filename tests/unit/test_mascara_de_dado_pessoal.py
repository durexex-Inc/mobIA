"""A forma da mascara, sem banco. TEC-195, RN-18.5.

O que se afirma aqui e o CONTRATO com a tela (TEC-330), que escreve
`+55 48 9****-**21` por extenso -- e a propriedade que vale para toda entrada:
a mascara nunca revela mais do que a regra descreve.
"""

import pytest

from mobia.domain.leads.mascara import mascarar_email, mascarar_telefone


def test_o_telefone_sai_na_forma_que_a_tela_espera() -> None:
    """O literal da TEC-330, que e o contrato com quem desenha a tela."""
    assert mascarar_telefone("5548999990021") == "+55 48 9****-**21"


def test_celular_de_oito_digitos_ganha_o_nove_antes_de_mascarar() -> None:
    """`normalizar` insere o 9 do `wa_id` da Meta, e a mascara ve o canonico.

    Sem isso, o mesmo lead sairia com duas mascaras diferentes conforme a Meta
    tivesse mandado o numero com ou sem o 9.
    """
    assert mascarar_telefone("554899990021") == mascarar_telefone("5548999990021")


def test_telefone_com_pontuacao_sai_igual_ao_cru() -> None:
    assert mascarar_telefone("+55 (48) 99999-0021") == "+55 48 9****-**21"


def test_fixo_de_oito_digitos_tambem_mascara() -> None:
    """Fixo comeca de 2 a 5 e nao ganha o 9 -- sao 8 digitos de assinante."""
    assert mascarar_telefone("554832100021") == "+55 48 3***-**21"


def test_o_que_nao_e_telefone_sai_nulo_e_nao_formatado() -> None:
    """A `conversation_key` do canal web e UUID de sessao, nao numero.

    Formata-la como telefone mentiria sobre o que ela e.
    """
    assert mascarar_telefone("4f2c1b8e-0d3a-4c9f-9a1e-7b6d5c4e3f21") is None
    assert mascarar_telefone("") is None
    assert mascarar_telefone("12345") is None


@pytest.mark.parametrize(
    "bruto",
    [
        "5548999990021",
        "554832100021",
        "+55 (11) 98888-7766",
    ],
)
def test_a_mascara_do_telefone_nunca_mostra_o_miolo(bruto: str) -> None:
    """A propriedade, dita como propriedade e nao como exemplo.

    Dos digitos do assinante, so o primeiro e os dois ultimos podem aparecer.
    Uma regra que revelasse um digito a mais passaria nos exemplos acima e
    seria pega aqui.
    """
    mascarado = mascarar_telefone(bruto)
    assert mascarado is not None

    _, _, assinante_mascarado = mascarado.partition(" ")[2].partition(" ")
    digitos_visiveis = [c for c in assinante_mascarado if c.isdigit()]
    assert len(digitos_visiveis) == 3


def test_o_email_sai_na_forma_que_a_tela_espera() -> None:
    assert mascarar_email("marina@exemplo.com") == "m****a@e*****o.com"


def test_o_tld_fica_inteiro_e_o_dominio_composto_mascara_so_o_nome() -> None:
    """`rpartition` pelo ULTIMO ponto: de `exemplo.com.br` sobra so o `br`.

    O `m` visivel no fim e o do `.com`, que entrou no miolo mascarado junto
    com o resto -- dominio de segundo nivel nao e dado pessoal, e preserva-lo
    exigiria uma lista de sufixos publicos para ganhar nada.
    """
    assert mascarar_email("marina@exemplo.com.br") == "m****a@e*********m.br"


def test_parte_curta_demais_esconde_em_vez_de_revelar() -> None:
    """O degrau e sempre para o lado de esconder.

    Com dois caracteres, mostrar o primeiro E o ultimo mostraria a parte
    inteira -- entao sobra so o ultimo.
    """
    assert mascarar_email("ab@cd.io") == "*b@*d.io"
    assert mascarar_email("a@b.io") == "*a@*b.io"


def test_dominio_sem_ponto_mascara_o_dominio_inteiro() -> None:
    assert mascarar_email("marina@localhost") == "m****a@l*******t"


def test_o_que_nao_e_email_sai_nulo() -> None:
    assert mascarar_email("marina") is None
    assert mascarar_email("@exemplo.com") is None
    assert mascarar_email("marina@") is None


@pytest.mark.parametrize(
    "bruto",
    ["marina@exemplo.com", "ab@cd.io", "a@b.io", "marina@exemplo.com.br"],
)
def test_a_mascara_do_email_nunca_devolve_o_original(bruto: str) -> None:
    """A propriedade que fecha o conjunto: nenhuma entrada passa inteira."""
    mascarado = mascarar_email(bruto)
    assert mascarado is not None
    assert mascarado != bruto
    assert "*" in mascarado

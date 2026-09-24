"""Regex e normalizacao de telefone brasileiro. TEC-129, D2."""

import pytest

from mobia.domain.identidade.telefone import extrair_telefone, normalizar


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("meu whats e (48) 99999-0000", "5548999990000"),
        ("+55 48 99999-0000", "5548999990000"),
        ("+5548999990000", "5548999990000"),
        ("48999990000", "5548999990000"),
        # o 9 separado do resto do celular, como muita gente escreve
        ("48 9 9999 0000", "5548999990000"),
        ("(48) 9 9999-0000", "5548999990000"),
        ("+55 48 9 9999-0000", "5548999990000"),
        # o zero de tronco antes do DDD, de quem aprendeu a discar interurbano
        ("(048) 99999-0000", "5548999990000"),
        ("048 99999-0000", "5548999990000"),
        ("fixo (011) 3222-1234", "551132221234"),
        ("liga no 48.99999.0000", "5548999990000"),
        # celular sem o 9: ganha o 9
        ("(48) 9999-0000", "5548999990000"),
        # fixo: fica com 12
        ("fixo (48) 3222-1234", "554832221234"),
    ],
)
def test_extrai_as_mascaras_comuns(texto: str, esperado: str | None) -> None:
    assert extrair_telefone(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "o CEP e 88010-400",
        "ate R$ 1.250.000",
        "orcamento de 900000",
        "meu CPF e 123.456.789-09",
        "visita dia 24/09/2026",
        "DDD invalido (20) 99999-0000",
        "tres quartos e duas vagas",
        # CPF cru comecando por zero: o zero so e de tronco quando a mascara o
        # separa do resto (parenteses ou separador depois do DDD)
        "meu CPF e 01234567890",
        "meu CPF e 012.345.678-90",
        # o separador depois do 9 so vale depois de um 9
        "(48) 8 9999-0000",
    ],
)
def test_nao_casa_o_que_nao_e_telefone(texto: str) -> None:
    assert extrair_telefone(texto) is None


def test_cpf_cru_com_9_na_terceira_posicao_e_falso_positivo_conhecido() -> None:
    # Onze digitos com DDD valido e 9 na terceira posicao sao indistinguiveis
    # de um celular. A spec aceita o falso positivo (D2); este teste existe
    # para que ninguem o "conserte" sem reler a decisao.
    assert extrair_telefone("12945678909") == "5512945678909"


def test_dois_telefones_diferentes_nao_devolvem_nenhum() -> None:
    assert extrair_telefone("(48) 99999-0000 ou (48) 98888-1111") is None


def test_o_mesmo_telefone_duas_vezes_devolve_ele() -> None:
    assert extrair_telefone("(48) 99999-0000, repito: 48999990000") == "5548999990000"


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        # wa_id da Meta com o 9 e sem ele: a mesma forma canonica
        ("5548999990000", "5548999990000"),
        ("554899990000", "5548999990000"),
        ("554832221234", "554832221234"),
        # estrangeiro, curto, lixo
        ("14155550123", None),
        ("12345", None),
        ("", None),
    ],
)
def test_normaliza_o_wa_id(bruto: str, esperado: str | None) -> None:
    assert normalizar(bruto) == esperado


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("(048) 99999-0000", "5548999990000"),
        ("048 99999-0000", "5548999990000"),
        ("048.3222.1234", "554832221234"),
        # sem mascara nenhuma o zero nao e tronco: onze digitos comecando por
        # zero sao CPF cru tanto quanto telefone, e o DDD "01" nao existe
        ("04899990000", None),
        ("01234567890", None),
    ],
)
def test_normaliza_descarta_o_zero_de_tronco_so_com_mascara(
    bruto: str, esperado: str | None
) -> None:
    assert normalizar(bruto) == esperado

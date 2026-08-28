from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from mobia.domain.agente.schemas import (
    Extracao,
    FormaPagamento,
    TipoImovel,
    Urgencia,
)


def test_vocabulario_de_tipo_de_imovel():
    assert [membro.value for membro in TipoImovel] == [
        "APARTAMENTO",
        "CASA",
        "TERRENO",
        "COMERCIAL",
        "RURAL",
    ]


def test_vocabulario_de_urgencia():
    assert [membro.value for membro in Urgencia] == [
        "IMEDIATA",
        "ATE_3_MESES",
        "ATE_6_MESES",
        "SEM_PRESSA",
    ]


def test_vocabulario_de_forma_de_pagamento():
    assert [membro.value for membro in FormaPagamento] == [
        "A_VISTA",
        "FINANCIAMENTO",
        "CONSORCIO",
        "FGTS",
        "INDEFINIDA",
    ]


def test_extracao_sem_argumento_e_toda_none():
    vazia = Extracao()
    assert vazia.vazia() is True
    assert vazia.preenchidos() == {}


def test_preenchidos_devolve_so_os_campos_com_valor():
    extracao = Extracao(quartos=2, regiao="zona sul")
    assert extracao.vazia() is False
    assert extracao.preenchidos() == {"quartos": 2, "regiao": "zona sul"}


def test_preenchidos_nao_esconde_falso_nem_zero():
    """`if valor` descartaria `False` e `0`; a regra e `is not None`.

    Um lead que diz "nao tenho imovel pra vender" informou algo, e "sem vaga"
    e um criterio de busca tao real quanto "duas vagas".
    """
    extracao = Extracao(tem_imovel_para_vender=False, vagas=0)
    assert extracao.preenchidos() == {"tem_imovel_para_vender": False, "vagas": 0}


def test_extracao_e_imutavel():
    extracao = Extracao(quartos=2)
    with pytest.raises(FrozenInstanceError):
        extracao.quartos = 3  # type: ignore[misc]


def test_preco_guarda_precisao_de_decimal():
    extracao = Extracao(faixa_preco_max=Decimal("600000.00"))
    assert extracao.preenchidos() == {"faixa_preco_max": Decimal("600000.00")}

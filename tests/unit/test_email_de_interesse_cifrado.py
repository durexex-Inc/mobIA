"""TEC-404, D3 e D3a: o e-mail do pedido de interesse e coluna cifrada coberta pela rotacao."""

import uuid

from mobia.admin.recifrar import COLUNAS_CIFRADAS
from mobia.domain.portal.interesse import aad_do_email_de_interesse


def test_a_aad_amarra_o_email_a_linha() -> None:
    um, outro = uuid.uuid4(), uuid.uuid4()
    assert aad_do_email_de_interesse(um) != aad_do_email_de_interesse(outro)
    assert str(um) in aad_do_email_de_interesse(um)


def test_a_coluna_esta_na_rotacao_de_chave() -> None:
    # A guarda de `test_colunas_cifradas.py` so varre modulos `models.py`, e
    # `SolicitacaoDeInteresse` mora em `portal/interesse.py` (D3a da spec).
    alvo = next(
        c
        for c in COLUNAS_CIFRADAS
        if (c.tabela, c.coluna) == ("solicitacoes_de_interesse", "email_cifrado")
    )
    linha = uuid.uuid4()
    assert alvo.aad(linha) == aad_do_email_de_interesse(linha)

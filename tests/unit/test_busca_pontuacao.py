"""As partes puras da busca hibrida.

TEC-158. Basename distinto de tudo em `tests/integration/`.

**A aderencia NAO e testada aqui, e isso e deliberado.** Ela existe uma vez,
como expressao SQL montada em Python -- o score tem de estar no ORDER BY para
o LIMIT significar algo, entao o calculo mora no banco. Uma funcao Python
gemea que devolvesse o mesmo numero seria uma segunda definicao da mesma
regra, e o unitario sobre ela testaria uma funcao que a consulta nao usa. Os
tres valores da D7 sao afirmados em `tests/integration/test_busca_hibrida.py`,
contra o que realmente roda.
"""

import pytest

from mobia.domain.catalogo.busca import MAX_CANDIDATOS, zonas_de
from mobia.domain.catalogo.enums import Operacao, Zona
from mobia.domain.catalogo.schemas import FiltroDeBusca


def test_zona_pelo_nome_nu_e_pelo_prefixo() -> None:
    assert zonas_de(("sul",)) == (Zona.SUL,)
    assert zonas_de(("zona sul",)) == (Zona.SUL,)


def test_bairro_nao_deriva_zona() -> None:
    assert zonas_de(("moema",)) == ()


def test_centro_deriva_zona_e_segue_sendo_bairro() -> None:
    """O caso que fez a D4 recusar classificacao.

    "centro" e nome de zona E de bairro em quase toda cidade brasileira. A
    derivacao devolve a zona; quem NAO some e o texto, que continua sendo
    comparado contra `bairro_busca` no `OR` da consulta. A metade "e segue
    sendo bairro" e afirmada na integracao, onde ha as duas linhas.
    """
    assert zonas_de(("centro",)) == (Zona.CENTRO,)


def test_varias_regioes_derivam_varias_zonas_sem_duplicar() -> None:
    assert zonas_de(("zona sul", "sul", "norte")) == (Zona.NORTE, Zona.SUL)


def test_o_teto_de_candidatos_e_dez() -> None:
    """RN-09.2. Constante de modulo e nao `Settings` -- ver D11."""
    assert MAX_CANDIDATOS == 10


def test_busca_de_ambos_e_recusada_na_construcao() -> None:
    """`AMBOS` e o que um imovel pode ser, nunca o que uma busca pede.

    A guarda mora na construcao do filtro e nao no uso: sem ela, o
    `COLUNA_DE_PRECO[operacao]` levantava `KeyError` cru, e a borda HTTP da
    TEC-158 aceita `AMBOS` como valor de enum -- ou seja, 500 com entrada
    sintaticamente valida.
    """
    with pytest.raises(ValueError, match="nao e buscavel"):
        FiltroDeBusca(operacao=Operacao.AMBOS)


def test_as_duas_operacoes_buscaveis_constroem() -> None:
    assert FiltroDeBusca(operacao=Operacao.VENDA).operacao is Operacao.VENDA
    assert FiltroDeBusca(operacao=Operacao.ALUGUEL).operacao is Operacao.ALUGUEL

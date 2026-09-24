"""A forma do `X-Request-Id` aceita na entrada (TEC-368).

Os valores de borda aqui sao DE PROPOSITO os mesmos de
`frontend/src/lib/servidor/bff.test.ts`. As duas expressoes precisam continuar
iguais e nenhum gate liga uma a outra -- sao linguagens diferentes --, entao o
que existe contra a divergencia e este par de testes exercitando os mesmos
valores dos dois lados da fronteira.
"""

import re

from mobia.api.middleware import _id_de_requisicao

_UUID_GERADO = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


def test_propaga_o_id_de_entrada_quando_a_forma_e_aceitavel() -> None:
    assert _id_de_requisicao("01JB2Z3K4M5N6P7Q8R9S") == "01JB2Z3K4M5N6P7Q8R9S"
    assert (
        _id_de_requisicao("3f1a2b4c-5d6e-7f80-9a1b-2c3d4e5f6071")
        == "3f1a2b4c-5d6e-7f80-9a1b-2c3d4e5f6071"
    )
    assert _id_de_requisicao("req.abc:123_x-1") == "req.abc:123_x-1"


def test_gera_um_id_novo_quando_nao_ha_entrada() -> None:
    assert _UUID_GERADO.match(_id_de_requisicao(None))
    assert _UUID_GERADO.match(_id_de_requisicao(""))


def test_substitui_em_vez_de_recusar_quando_a_entrada_e_malformada() -> None:
    """Substituir e nao recusar: ninguem deve perder a requisicao por causa de
    um cabecalho de diagnostico. Mas propagar sem olhar seria deixar entrada
    nao confiavel escrever no log de quem esta do outro lado.
    """
    for malformado in ("tem espaco", "quebra\nde\nlinha", "acentuado-ç", "com/barra", "a" * 201):
        assert _UUID_GERADO.match(_id_de_requisicao(malformado)), malformado


def test_a_borda_e_200_aceito_e_201_substituido() -> None:
    """A MESMA borda que `bff.test.ts` exercita do outro lado da fronteira.

    Se este lado ficasse mais estrito, ele descartaria ids que o BFF propagou:
    os dois lados logariam ids diferentes para a mesma requisicao, e quem
    depurasse concluiria que sao requisicoes distintas.
    """
    assert _id_de_requisicao("a" * 200) == "a" * 200
    assert _id_de_requisicao("a" * 201) != "a" * 201

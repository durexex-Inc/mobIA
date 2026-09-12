"""As regras puras da recomendacao e da reacao.

TEC-163. Sem banco, sem I/O. Basename distinto de tudo em
`tests/integration/`.
"""

import uuid

from mobia.domain.agente.recomendacao import (
    LIMIAR_DE_DESCARTES,
    DescartePorBairro,
    bairros_a_excluir,
    motivo_do_match,
    resolver_ordinais,
)
from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoDoImovel, ReacaoLead

PRIMEIRO = uuid.uuid4()
SEGUNDO = uuid.uuid4()
TERCEIRO = uuid.uuid4()


def test_o_motivo_lista_os_criterios_que_casaram() -> None:
    """D5: derivado do que a busca sabe, nunca escrito pelo modelo."""
    assert motivo_do_match(["3 quartos", "Trindade", "ate R$ 400 mil"]) == (
        "3 quartos, Trindade, ate R$ 400 mil"
    )


def test_um_criterio_so_nao_ganha_virgula() -> None:
    assert motivo_do_match(["Trindade"]) == "Trindade"


def test_busca_sem_criterio_diz_isso_em_vez_de_ficar_vazia() -> None:
    """`motivo_match` e NOT NULL, e string vazia num campo de explicabilidade
    e pior que uma frase honesta: quem le a linha meses depois precisa saber
    que nao houve filtro, nao ficar sem saber o que aconteceu."""
    assert motivo_do_match([]) == "sem filtro: o lead nao restringiu a busca"


def test_o_motivo_e_ascii() -> None:
    """Vai para o banco e pode ser lido em relatorio; segue a disciplina do
    repo para texto que nao e prosa de docs."""
    assert motivo_do_match(["3 quartos", "Trindade"]).isascii()


def test_o_ordinal_vira_o_imovel_daquela_posicao() -> None:
    """D7: o modelo devolve ordinal, e o codigo resolve."""
    apresentados = [PRIMEIRO, SEGUNDO, TERCEIRO]
    reacoes = (ReacaoDoImovel(ordinal=2, reacao=ReacaoLead.INTERESSE, categoria=None),)

    assert resolver_ordinais(reacoes, apresentados) == ((SEGUNDO, reacoes[0]),)


def test_ordinal_fora_de_faixa_nao_derruba_os_outros() -> None:
    """D7 e a degradacao do desenho. Um ordinal inventado nao pode invalidar
    os que o modelo acertou -- o lead perderia a reacao correta junto com a
    errada, e o turno nao tem como pedir de novo."""
    apresentados = [PRIMEIRO, SEGUNDO]
    reacoes = (
        ReacaoDoImovel(
            ordinal=1, reacao=ReacaoLead.DESCARTE, categoria=CategoriaDescarte.DISTANCIA
        ),
        ReacaoDoImovel(ordinal=9, reacao=ReacaoLead.INTERESSE, categoria=None),
    )

    resolvidas = resolver_ordinais(reacoes, apresentados)

    assert [imovel for imovel, _ in resolvidas] == [PRIMEIRO]


def test_ordinal_zero_e_negativo_tambem_saem() -> None:
    """`apresentados[-1]` em Python devolve o ULTIMO item, entao um ordinal
    negativo que passasse pela guarda marcaria o imovel errado -- e o lead
    veria a reacao dele aplicada a outro imovel."""
    apresentados = [PRIMEIRO, SEGUNDO]
    reacoes = (
        ReacaoDoImovel(ordinal=0, reacao=ReacaoLead.INTERESSE, categoria=None),
        ReacaoDoImovel(ordinal=-1, reacao=ReacaoLead.INTERESSE, categoria=None),
    )

    assert resolver_ordinais(reacoes, apresentados) == ()


# ---------------------------------------------------------------------------
# Task 9: o limiar de descartes por distancia. RN-10.4, D11-D14.
# ---------------------------------------------------------------------------


def test_o_limiar_e_dois() -> None:
    """Constante nomeada e nao literal espalhado -- o valor da RN-10.4."""
    assert LIMIAR_DE_DESCARTES == 2


def test_um_descarte_por_distancia_nao_exclui() -> None:
    """Um descarte pode ser sobre a foto, o andar ou o condominio -- so dois
    na mesma direcao viram sinal."""
    descartes = (DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.DISTANCIA),)

    assert bairros_a_excluir(descartes) == ()


def test_dois_descartes_por_distancia_excluem() -> None:
    descartes = (
        DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.DISTANCIA),
        DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.DISTANCIA),
    )

    assert bairros_a_excluir(descartes) == ("centro",)


def test_dois_descartes_de_categorias_diferentes_nao_excluem() -> None:
    """So DISTANCIA conta -- um descarte por preco nao diz nada sobre o
    bairro, e conta-lo estreitaria a busca por um motivo que o lead nunca
    deu."""
    descartes = (
        DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.DISTANCIA),
        DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.PRECO),
    )

    assert bairros_a_excluir(descartes) == ()


def test_descarte_com_categoria_ausente_nao_conta() -> None:
    """Sem motivo registrado nao ha como saber que foi sobre distancia --
    contar mesmo assim estreitaria a busca pelo motivo errado."""
    descartes = (
        DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.DISTANCIA),
        DescartePorBairro(bairro="centro", categoria=None),
    )

    assert bairros_a_excluir(descartes) == ()


def test_bairros_diferentes_nao_se_somam() -> None:
    """Dois descartes por distancia em bairros DIFERENTES nao excluem
    nenhum dos dois -- o sinal e por bairro."""
    descartes = (
        DescartePorBairro(bairro="centro", categoria=CategoriaDescarte.DISTANCIA),
        DescartePorBairro(bairro="trindade", categoria=CategoriaDescarte.DISTANCIA),
    )

    assert bairros_a_excluir(descartes) == ()

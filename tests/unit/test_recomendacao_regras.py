"""As regras puras da recomendacao e da reacao.

TEC-163. Sem banco, sem I/O. Basename distinto de tudo em
`tests/integration/`.
"""

import uuid

import pytest

from mobia.domain.agente.recomendacao import (
    LIMIAR_DE_DESCARTES,
    DescartePorBairro,
    bairros_a_excluir,
    motivo_do_match,
    resolver_ordinais,
)
from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoDoImovel, ReacaoLead
from mobia.domain.agente.turno import aviso_de_ajuste

PRIMEIRO = uuid.uuid4()
SEGUNDO = uuid.uuid4()
TERCEIRO = uuid.uuid4()


def _motivo(criterios: list[str], **relaxamento: bool) -> str:
    """`motivo_do_match` com as duas dimensoes em False por default.

    As duas sao obrigatorias na funcao de proposito (ver o docstring dela): um
    default la deixaria um chamador novo gravar "nao houve ampliacao" sem ter
    decidido nada. Aqui, num arquivo cujo assunto e a FRASE, repetir
    `relaxou_preco=False, relaxou_bairro=False` em todo teste esconderia o
    unico argumento que cada um esta exercitando.
    """
    return motivo_do_match(
        criterios,
        relaxou_preco=relaxamento.get("relaxou_preco", False),
        relaxou_bairro=relaxamento.get("relaxou_bairro", False),
    )


def test_o_motivo_lista_os_criterios_que_casaram() -> None:
    """D5: derivado do que a busca sabe, nunca escrito pelo modelo."""
    assert _motivo(["3 quartos", "Trindade", "ate R$ 400 mil"]) == (
        "3 quartos, Trindade, ate R$ 400 mil"
    )


def test_um_criterio_so_nao_ganha_virgula() -> None:
    assert _motivo(["Trindade"]) == "Trindade"


def test_busca_sem_criterio_diz_isso_em_vez_de_ficar_vazia() -> None:
    """`motivo_match` e NOT NULL, e string vazia num campo de explicabilidade
    e pior que uma frase honesta: quem le a linha meses depois precisa saber
    que nao houve filtro, nao ficar sem saber o que aconteceu."""
    assert _motivo([]) == "sem filtro: o lead nao restringiu a busca"


def test_o_motivo_e_ascii() -> None:
    """Vai para o banco (coluna `motivo_match`) e pode ser lido em relatorio;
    segue a disciplina do repo para texto que nao e prosa de docs. Fora da
    fronteira da TEC-267 (texto que o LEAD le): isto e explicabilidade da
    RN-10.3 para quem le o banco, nao mensagem de turno, e por isso continua
    sem acento mesmo depois daquela task."""
    assert _motivo(["3 quartos", "Trindade"]).isascii()
    assert _motivo(["ate R$ 400.000"], relaxou_preco=True).isascii()


def test_o_motivo_do_passe_relaxado_diz_que_o_criterio_foi_ampliado() -> None:
    """D5 pede a frase montada de "quais filtros bateram, E se houve
    relaxamento" -- e a segunda metade e o que separa um motivo verdadeiro de
    um inventado.

    `criterios` vem do filtro do PRIMEIRO passe (`_criterios_de` em
    `ferramenta_de_busca.py`): um imovel de R$ 430.000 achado so porque o teto
    cedeu 10% seria gravado com "ate R$ 400.000", criterio que ele nao
    satisfaz. Quem lesse a linha depois leria como fato uma frase falsa -- o
    dano exato que a D5 existe para impedir.
    """
    assert _motivo(["3 quartos", "ate R$ 400.000"], relaxou_preco=True) == (
        "3 quartos, ate R$ 400.000 (criterio ampliado: preco)"
    )


def test_o_motivo_nomeia_a_dimensao_ampliada() -> None:
    """As tres variantes da RN-09.3, as mesmas que `aviso_de_ampliacao`
    distingue -- o lead ouve qual criterio cedeu, e a linha do banco diz o
    mesmo em vez de um "relaxado" generico."""
    assert _motivo(["Trindade"], relaxou_bairro=True) == "Trindade (criterio ampliado: bairro)"
    assert _motivo(["Trindade"], relaxou_preco=True, relaxou_bairro=True) == (
        "Trindade (criterio ampliado: preco e bairro)"
    )


def test_busca_sem_relaxamento_nao_ganha_sufixo_nenhum() -> None:
    """~99% dos turnos. O controle dos dois testes acima: sem isto, um sufixo
    colado sempre passaria neles e mentiria em todo o resto."""
    assert _motivo(["Trindade"], relaxou_preco=False, relaxou_bairro=False) == "Trindade"


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


# ---------------------------------------------------------------------------
# Task 10: o aviso de ajuste. RN-10.4, D15. `aviso_de_ajuste` mora em
# `turno.py` -- e nao neste modulo -- pelo mesmo molde de `aviso_de_ampliacao`
# (tambem em `turno.py`, testada em `tests/unit/test_relaxamento_alargar.py`):
# a funcao pura que monta o texto do aviso fica ao lado de onde ele e enviado,
# e o teste dela mora aqui, no arquivo tematico, importando de onde ela vive.
# ---------------------------------------------------------------------------


def test_o_aviso_nomeia_um_bairro_so() -> None:
    """D15: diverge de proposito do aviso de ampliacao, que nunca nomeia."""
    assert aviso_de_ajuste(("campeche",)) == "Tirei Campeche da busca, que você já descartou."


def test_o_aviso_nomeia_dois_bairros() -> None:
    assert (
        aviso_de_ajuste(("campeche", "trindade"))
        == "Tirei Campeche e Trindade da busca, que você já descartou."
    )


def test_o_aviso_nomeia_tres_bairros() -> None:
    assert (
        aviso_de_ajuste(("campeche", "trindade", "itacorubi"))
        == "Tirei Campeche, Trindade e Itacorubi da busca, que você já descartou."
    )


def test_o_aviso_recompoe_o_bairro_dobrado_em_nome_legivel() -> None:
    """`bairros_a_excluir` devolve a forma dobrada (`texto.dobrar`) -- minuscula
    e sem acento. `.title()` e o bastante para o lead reconhecer o nome; nao ha
    acento para recuperar porque a forma dobrada nunca teve nenhum."""
    assert aviso_de_ajuste(("corrego grande",)) == (
        "Tirei Corrego Grande da busca, que você já descartou."
    )


def test_o_aviso_sem_bairro_nenhum_levanta() -> None:
    """Guarda contra o par impossivel: o chamador (`executar_turno`) so invoca
    isto quando o conjunto excluido mudou desde antes do turno -- ver o
    docstring de `aviso_de_ajuste`."""
    with pytest.raises(ValueError, match="aviso_de_ajuste"):
        aviso_de_ajuste(())

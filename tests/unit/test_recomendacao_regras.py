"""As regras puras da recomendacao e da reacao.

TEC-163. Sem banco, sem I/O. Basename distinto de tudo em
`tests/integration/`.
"""

import uuid

from mobia.domain.agente.recomendacao import motivo_do_match, resolver_ordinais
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

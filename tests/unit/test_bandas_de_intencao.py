"""Quais trocas de intencao invalidam o orcamento ja declarado. TEC-136.

Puro: nao toca banco nem modelo. O que se testa e a REGRA -- quais pares de
intencao mudam a banda de valor --, e nao o efeito dela no estado.
"""

import pytest

from mobia.domain.agente.dinheiro import mudou_de_banda
from mobia.domain.agente.schemas import Intencao


@pytest.mark.parametrize(
    ("antiga", "nova"),
    [
        (Intencao.ALUGUEL, Intencao.COMPRA),
        (Intencao.COMPRA, Intencao.ALUGUEL),
        (Intencao.ALUGUEL, Intencao.INVESTIMENTO),
        (Intencao.INVESTIMENTO, Intencao.ALUGUEL),
    ],
)
def test_trocar_entre_aluguel_e_venda_muda_a_banda(antiga: Intencao, nova: Intencao) -> None:
    """O caso da card, nos dois sentidos e pelas duas intencoes de compra.

    `_BANDA_DE_ALUGUEL` vai de R$ 300 a R$ 200 mil e `_BANDA_DE_COMPRA` de
    R$ 30 mil a R$ 1 bilhao: um numero admitido sob uma nao significa o mesmo
    sob a outra, e e por isso que o orcamento nao atravessa a troca.
    """
    assert mudou_de_banda(antiga, nova) is True


@pytest.mark.parametrize(
    ("antiga", "nova"),
    [
        (Intencao.COMPRA, Intencao.INVESTIMENTO),
        (Intencao.INVESTIMENTO, Intencao.COMPRA),
        (Intencao.COMPRA, Intencao.VENDER_IMOVEL),
        (Intencao.COMPRA, Intencao.COMPRA),
        (Intencao.ALUGUEL, Intencao.ALUGUEL),
    ],
)
def test_mesma_banda_nao_invalida_o_orcamento(antiga: Intencao, nova: Intencao) -> None:
    """A contraprova, e ela e a que impede o descarte incondicional.

    COMPRA, INVESTIMENTO e VENDER_IMOVEL partilham `_BANDA_DE_COMPRA`. Um lead
    que decide investir em vez de morar continua com o mesmo orcamento
    significando a mesma coisa -- apagar ali seria reperguntar por nada.
    """
    assert mudou_de_banda(antiga, nova) is False


def test_sem_intencao_anterior_a_banda_muda() -> None:
    """A segunda porta do defeito, a que o Gherkin da card nao menciona.

    Faixa gravada com a intencao acumulada ainda nula quer dizer que o numero
    foi admitido sob `_BANDA_FROUXA`, a uniao das duas. O comentario de
    `piso_do_numero_nu` descreve o estrago: "o valor admitido enquanto a
    intencao era INDEFINIDA sobrevive para dentro de uma conversa depois
    classificada COMPRA e vira o filtro da busca la".
    """
    assert mudou_de_banda(None, Intencao.COMPRA) is True
    assert mudou_de_banda(None, Intencao.ALUGUEL) is True


@pytest.mark.parametrize("nova", [Intencao.SUPORTE_CONTRATO, Intencao.INDEFINIDA])
def test_intencao_sem_banda_propria_nao_descarta(nova: Intencao) -> None:
    """Quem nao esta em `_BANDAS` cai na banda frouxa, e frouxa nao invalida.

    Este e o sentido `nova`: nao ha faixa nova para o numero guardado violar. O
    sentido `antiga` devolve False por outra razao e tem teste proprio logo
    abaixo (`test_intencao_antiga_sem_banda_nao_descarta`).

    Nao ha caminho que chame isto com INDEFINIDA -- `campos_a_gravar` nunca a
    grava --, e a guarda existe para que a regra seja total em vez de depender
    do chamador. SUPORTE_CONTRATO chega: e intencao gravavel e nao tem banda.
    """
    assert mudou_de_banda(Intencao.COMPRA, nova) is False


@pytest.mark.parametrize(
    ("antiga", "nova"),
    [
        (Intencao.SUPORTE_CONTRATO, Intencao.COMPRA),
        (Intencao.SUPORTE_CONTRATO, Intencao.ALUGUEL),
        (Intencao.SUPORTE_CONTRATO, Intencao.INVESTIMENTO),
        (Intencao.SUPORTE_CONTRATO, Intencao.VENDER_IMOVEL),
        (Intencao.FORA_DE_ESCOPO, Intencao.COMPRA),
        (Intencao.INDEFINIDA, Intencao.ALUGUEL),
    ],
)
def test_intencao_antiga_sem_banda_nao_descarta(antiga: Intencao, nova: Intencao) -> None:
    """O outro sentido, que ate a fix wave desta card ninguem parametrizava.

    `antiga` fora de `_BANDAS` nao diz NADA sobre o numero guardado -- ele foi
    admitido sob a banda de alguma intencao anterior, e nao sob a que o turno
    de suporte carimbou de passagem. Tratar isso como troca de banda destroi
    orcamento valido: a versao antiga comparava `_BANDAS.get(antiga)`, que da
    `None` para toda intencao fora da tabela e portanto "difere" de qualquer
    banda real.
    """
    assert mudou_de_banda(antiga, nova) is False


def test_o_desvio_pelo_suporte_nao_apaga_o_orcamento_de_compra() -> None:
    """A ida e volta que a `.get` transformava em perda de dado.

    Turno A classifica COMPRA e o lead diz R$ 800 mil. Turno B e "qual o prazo
    de rescisao do contrato?", que classifica SUPORTE_CONTRATO -- intencao
    gravavel, entao a coluna passa a valer isso, sem descarte (a ida ja
    devolvia False). Turno C volta ao assunto e classifica COMPRA de novo, e a
    volta e que apagava os R$ 800 mil, com as marcas junto.

    E o defeito da propria card ao contrario: o descarte existe para impedir
    que um numero de uma banda vire filtro de outra, e aqui as duas pontas sao
    a MESMA banda.
    """
    assert mudou_de_banda(Intencao.COMPRA, Intencao.SUPORTE_CONTRATO) is False
    assert mudou_de_banda(Intencao.SUPORTE_CONTRATO, Intencao.COMPRA) is False

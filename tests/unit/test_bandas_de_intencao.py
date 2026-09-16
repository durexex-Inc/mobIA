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

    Nao ha caminho que chame isto com INDEFINIDA -- `campos_a_gravar` nunca a
    grava --, e a guarda existe para que a regra seja total em vez de depender
    do chamador. SUPORTE_CONTRATO chega: e intencao gravavel e nao tem banda.
    """
    assert mudou_de_banda(Intencao.COMPRA, nova) is False

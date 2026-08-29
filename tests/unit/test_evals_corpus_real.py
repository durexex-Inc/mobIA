from dataclasses import fields
from pathlib import Path

import pytest

from mobia.domain.agente.schemas import (
    Extracao,
    FormaPagamento,
    Intencao,
    TipoImovel,
    Urgencia,
)
from mobia.evals.corpus import ConversaAnotada, carregar, total_de_turnos
from mobia.evals.metricas import PISO_DE_TURNOS, PISO_DE_TURNOS_ANOTADOS

_VOCABULARIO = {
    "tipo_imovel": TipoImovel,
    "urgencia": Urgencia,
    "forma_pagamento": FormaPagamento,
}

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"


@pytest.fixture(scope="module")
def conversas() -> list[ConversaAnotada]:
    return carregar(CORPUS)


def test_o_corpus_tem_as_cinquenta_conversas_do_card(
    conversas: list[ConversaAnotada],
) -> None:
    assert len(conversas) == 50


def test_o_corpus_passa_do_piso_de_turnos(conversas: list[ConversaAnotada]) -> None:
    """Abaixo do piso, um unico turno vale mais de 0,8% e a faixa amarela
    deixa de absorver o ruido entre execucoes."""
    assert total_de_turnos(conversas) >= PISO_DE_TURNOS


def test_toda_intencao_do_enum_aparece(conversas: list[ConversaAnotada]) -> None:
    """Uma intencao ausente do corpus e uma intencao cuja regressao o gate
    nao pega."""
    vistas = {turno.intencao for conversa in conversas for turno in conversa.turnos}

    assert vistas == set(Intencao)


def test_ha_conversas_com_mudanca_de_intencao_no_meio(
    conversas: list[ConversaAnotada],
) -> None:
    """Caso de borda exigido pelo card, e o unico que so faz sentido medido
    por turno."""
    mudam = [c for c in conversas if len({t.intencao for t in c.turnos}) > 1]

    assert len(mudam) >= 5


@pytest.mark.parametrize(
    ("intencao", "minimo"),
    [(Intencao.FORA_DE_ESCOPO, 3), (Intencao.INDEFINIDA, 3)],
)
def test_casos_de_borda_tem_massa_suficiente(
    conversas: list[ConversaAnotada], intencao: Intencao, minimo: int
) -> None:
    """Pedido fora de escopo e lead evasivo sao exigidos pelo card. Com um
    exemplo so, a metrica daquele caso e ruido."""
    quantos = sum(1 for c in conversas for t in c.turnos if t.intencao is intencao)

    assert quantos >= minimo


def test_ha_tentativas_de_injecao_marcadas(conversas: list[ConversaAnotada]) -> None:
    """Exigido pelo card. A convencao e o prefixo do id, porque nao ha campo
    proprio -- e nao vale a pena criar um so para isto."""
    injecoes = [c for c in conversas if c.id.startswith("borda-injecao")]

    assert len(injecoes) >= 2


def test_todo_id_e_prefixado_pela_categoria(conversas: list[ConversaAnotada]) -> None:
    prefixos = ("compra-", "aluguel-", "investimento-", "follow-up-", "borda-")

    for conversa in conversas:
        assert conversa.id.startswith(prefixos), conversa.id


def test_corpus_tem_turnos_anotados_suficientes(conversas: list[ConversaAnotada]) -> None:
    """Piso proprio: sem ele, anotar tres turnos faceis daria 100% de precisao
    num corpus que nao mede nada."""
    anotados = sum(1 for c in conversas for t in c.turnos if t.campos is not None)
    assert anotados >= PISO_DE_TURNOS_ANOTADOS


def test_todo_campo_de_extracao_tem_anotacao(conversas: list[ConversaAnotada]) -> None:
    """Campo sem anotacao nenhuma so pode subtrair da precisao da extracao.

    O denominador de `precisao_da_extracao` e a uniao do esperado com o obtido
    por turno. Um campo que o corpus nunca anota nao tem como somar acerto --
    nao ha anotacao contra a qual bater -- mas entra no total toda vez que o
    modelo o extrai. O gate passa a premiar quem se recusa a extrair aquele
    campo, que e o oposto do que a TEC-145 existe para medir.

    A lista sai de `fields(Extracao)` e nao de um literal: a proxima card que
    acrescentar campo quebra este teste, em vez de reabrir o buraco em
    silencio.
    """
    anotados = {
        nome
        for conversa in conversas
        for turno in conversa.turnos
        if turno.campos
        for nome in turno.campos
    }
    todos = {campo.name for campo in fields(Extracao)}

    assert todos - anotados == set()


def test_anotacao_nunca_usa_valor_fora_do_vocabulario(conversas: list[ConversaAnotada]) -> None:
    """`carregar` ja levanta nesse caso; este teste guarda o corpus commitado."""
    for conversa in conversas:
        for turno in conversa.turnos:
            for nome, enum in _VOCABULARIO.items():
                if turno.campos and nome in turno.campos:
                    assert turno.campos[nome] in [membro.value for membro in enum]


def test_ha_turno_de_correcao_anotado(conversas: list[ConversaAnotada]) -> None:
    """A sobrescrita pelo mais novo (D4 do spec) precisa de caso no corpus."""
    for conversa in conversas:
        regioes = [
            turno.campos["regiao"]
            for turno in conversa.turnos
            if turno.campos and "regiao" in turno.campos
        ]
        if len(regioes) >= 2 and len(set(regioes)) >= 2:
            return
    pytest.fail("nenhuma conversa anotada troca de regiao: a sobrescrita nao e medida")

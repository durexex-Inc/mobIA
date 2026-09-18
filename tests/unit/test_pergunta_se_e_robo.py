"""A faixa do detector da pergunta "voce e um robo?" (TEC-272).

**A afirmacao forte deste arquivo e a NEGATIVA, e a razao esta na D3 do
desenho.** Nao existe fala real deste eixo em `evals/corpus/` -- zero
ocorrencias nos cinco arquivos --, entao todo termo do detector e invencao, e
medi-lo contra as frasagens que ele foi escrito para pegar seria medi-lo
contra o proprio vocabulario. O que da para provar e que ele nao dispara em
nenhum dos mil e tantos turnos de fala real que o corpus tem, e e isso que
`test_nao_dispara_em_nenhum_turno_do_corpus` faz.

A assimetria que justifica a faixa estrita e a de `gatilhos.py`, nao a do
opt-out: falso negativo devolve o comportamento de hoje, falso positivo gruda
uma oferta de corretor numa fala que nao pediu -- que e literalmente o segundo
criterio de aceite desta card.
"""

from pathlib import Path

import pytest

from mobia.domain.agente.identificacao import perguntou_se_e_robo
from mobia.evals.corpus import carregar

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"


@pytest.mark.parametrize(
    "texto",
    [
        "vc e um robo?",
        "você é um robô?",
        "to falando com uma pessoa?",
        "isso e automatico ou tem alguem ai?",
        "voce e humano ou maquina?",
        "isso aqui é um bot?",
        "tem alguém aí ou é tudo automático?",
    ],
)
def test_a_pergunta_dispara(texto: str) -> None:
    """As frasagens que a TEC-139 sondou, mais as variantes acentuadas.

    Nenhuma delas e fala real observada -- ver a docstring do modulo. Elas
    fixam a faixa, nao a validam.
    """
    assert perguntou_se_e_robo(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        "quero um apartamento automatico de 2 quartos",
        "o portao e automatico?",
        "tem maquina de lavar no apartamento?",
        "o predio tem elevador automatico?",
        "somos em cinco pessoas",
        "preciso falar com uma pessoa sobre o contrato",
    ],
)
def test_fala_vizinha_nao_dispara(texto: str) -> None:
    """O objeto sozinho nunca basta.

    "automatico" qualificando portao ou elevador, "maquina" de lavar e
    "pessoa" como sujeito sao fala corrente de quem procura imovel. Um
    detector que casasse o substantivo solto grudaria oferta de corretor em
    cada um deles.
    """
    assert perguntou_se_e_robo(texto) is False


def test_texto_vazio_nao_levanta() -> None:
    """Mesma garantia de `gatilhos_de`: texto sem letra nenhuma devolve False."""
    assert perguntou_se_e_robo("") is False
    assert perguntou_se_e_robo("!!! 123 ???") is False


def test_nao_dispara_em_nenhum_turno_do_corpus() -> None:
    """A unica afirmacao forte disponivel sobre a faixa (D3 do desenho).

    Mil e tantos turnos de fala de lead, e nenhum deles e esta pergunta --
    conferido por grep antes de escrever o detector. Se um deles passar a
    disparar, ou o corpus ganhou um caso deste eixo (e ai o teste conta uma
    novidade boa) ou a faixa ficou larga demais (e ai ele pegou o defeito que
    o corpus inventado nunca pegaria).

    Sem chamada paga: `carregar` so le YAML.
    """
    disparam = [
        turno.lead
        for conversa in carregar(CORPUS)
        for turno in conversa.turnos
        if perguntou_se_e_robo(turno.lead)
    ]

    assert disparam == []

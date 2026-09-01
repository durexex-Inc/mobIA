"""Trava o proxy de repergunta contra os seis casos que motivaram o aperto.

`_reperguntou` e `MARCADORES_DE_REPERGUNTA` vivem em
`evals/test_acuracia_de_intencao.py`, nao em `src/`, porque sao parte do
runner pago -- mas nada aqui chama o modelo: e funcao pura de string, e o
import do modulo nao dispara chamada nenhuma (a chamada so acontece dentro do
teste `async def test_acuracia_de_intencao_no_corpus`, nunca na importacao).
Antes deste arquivo, `_reperguntou` nao tinha teste nenhum -- foi por isso que
o substring cru sem fronteira de palavra e sem exigir `?` passou despercebido.
"""

from evals.test_acuracia_de_intencao import _campos_conhecidos, _reperguntou

CAMPOS = ("regiao", "quartos", "vagas", "tipo_imovel", "faixa_preco_max_centavos")


def test_reperguntou_nao_conta_recusa_com_onde_embutido() -> None:
    """ "responder" contem "onde" como substring, mas nao como palavra."""
    assert _reperguntou("Nao consigo responder isso agora", CAMPOS) == []


def test_reperguntou_nao_conta_o_agente_descrevendo_um_imovel() -> None:
    """Descrever quartos e vaga e o trabalho do agente, nao repergunta -- e
    a frase nem tem `?`."""
    assert _reperguntou("Esse apartamento tem 2 quartos e 1 vaga de garagem", CAMPOS) == []


def test_reperguntou_nao_conta_valor_informado() -> None:
    """ "valor" saiu da lista de marcadores por ser ambiguo demais (aparece
    tanto perguntando quanto respondendo o preco)."""
    assert _reperguntou("O valor do condominio e R$ 650", CAMPOS) == []


def test_reperguntou_nao_conta_casa_em_casamento() -> None:
    """ "casa" e substring de "casamento"; tambem saiu da lista de marcadores
    por ser ambiguo demais mesmo como palavra inteira."""
    assert _reperguntou("Parabens pelo casamento!", CAMPOS) == []


def test_reperguntou_conta_pergunta_real_de_regiao() -> None:
    assert _reperguntou("Em qual bairro voce esta procurando?", CAMPOS) == ["regiao"]


def test_reperguntou_conta_pergunta_real_de_quartos() -> None:
    assert _reperguntou("Quantos quartos voce precisa?", CAMPOS) == ["quartos"]


def test_conhecidos_antes_nao_conta_a_chave_da_marca() -> None:
    """A armadilha nomeada no spec (D10).

    `conhecidos_antes` e `set(estado_acumulado)`. Com a marca virando mais
    uma chave do dict, a string "perguntados_sem_resposta" entraria como se
    fosse um campo conhecido e contaminaria os dois proxies -- `_reperguntou`
    e o `- conhecidos_antes` de `campos_perguntados`.
    """
    estado = {
        "intencao": "COMPRA",
        "quartos": 2,
        "perguntados_sem_resposta": ["regiao"],
    }
    assert _campos_conhecidos(estado) == {"intencao", "quartos"}

"""A guarda que manda o lead para uma pessoa, testada.

TEC-143. Pura: nao toca banco, nao toca modelo. A decisao de transferir nao
pode depender de um provedor estar de pe, pelo mesmo motivo que a de opt-out
nao pode -- ver `domain/optout/deteccao.py`.
"""

import pytest

from mobia.domain.humano.deteccao import pediu_humano


@pytest.mark.parametrize(
    "texto",
    [
        "quero falar com uma pessoa",
        "Quero Falar Com Uma Pessoa!",
        "me passa pra um atendente por favor",
        "prefiro falar com um humano",
        "queria falar com atendente",
        "quero atendimento humano",
        "cansei de robo, quero uma pessoa",
    ],
)
def test_pedido_explicito_dispara(texto: str) -> None:
    assert pediu_humano(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        # Os dois casos reais do corpus de evals, ambos sobre assinar a
        # distancia. Medido na TEC-143: "pessoa" aparece 2 vezes nas 147
        # mensagens do corpus, as duas dentro de "pessoalmente".
        "consigo fechar tudo a distancia, sem vir pessoalmente antes?",
        "precisa vir pessoalmente pra assinar ou consigo por procuracao?",
        # O corretor como ASSUNTO, nao como pedido de transferencia.
        "o corretor falou que tem vaga dupla",
        "depois eu falo com o corretor sobre o financiamento",
        # Qualificacao normal.
        "quero um apartamento de dois quartos em Pinheiros",
        "",
    ],
)
def test_conversa_normal_nao_dispara(texto: str) -> None:
    assert pediu_humano(texto) is False


def test_pessoa_sozinha_nao_e_pedido() -> None:
    """A armadilha analoga a do opt-out, e a razao de nenhum termo ser palavra solta.

    `domain/optout/deteccao.py` registra que "nao quero mais receber nada" saiu
    dos inequivocos porque "nada" aceita complemento partitivo. Aqui o termo
    perigoso e "pessoa": casado por substring ele pega "pessoalmente", que no
    corpus aparece so em pergunta sobre procuracao. Todo termo desta lista
    carrega o verbo ou a preposicao que o torna um pedido.
    """
    assert pediu_humano("pessoa") is False
    assert pediu_humano("vou pessoalmente ver o imovel") is False


@pytest.mark.parametrize("texto", ["atendente", "Atendente?", "humano"])
def test_termo_ambiguo_so_casa_a_mensagem_inteira(texto: str) -> None:
    """Mesma faixa estrita do opt-out: sozinho e pedido, no meio de frase nao.

    Um lead que escreve so "atendente" esta pedindo. O mesmo substantivo dentro
    de "o atendente anterior me falou outro valor" e assunto.
    """
    assert pediu_humano(texto) is True
    assert pediu_humano("o atendente anterior me falou outro valor") is False

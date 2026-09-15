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


@pytest.mark.parametrize(
    "texto",
    [
        # Pessoa fisica vs juridica e vocabulario de contrato imobiliario, nao
        # pedido de transferencia. Foi o que tirou "quero uma pessoa" da lista.
        "quero uma pessoa fisica no contrato, nao pessoa juridica",
        "pode ser em nome de pessoa juridica? quero uma pessoa juridica",
        # Comentario sobre o atendimento de OUTRA empresa. Foi o que tirou
        # "atendimento humano" bare.
        "o atendimento humano la na outra imobiliaria era horrivel",
        # Verbo sem objeto, numa conversa sobre pagamento.
        "me transfere o comprovante do pix por favor",
        # A terceira porta da mesma colisao, achada na re-revisao: o objeto
        # existia ("uma pessoa") mas estava nu. Transferir titularidade para
        # uma PJ e assunto de contrato, nao pedido de atendimento.
        "pode me transfere pra uma pessoa juridica, quero mudar o titular",
    ],
)
def test_vocabulario_de_contrato_e_de_pagamento_nao_dispara(texto: str) -> None:
    """Os falsos positivos que as revisoes da TEC-143 acharam, fixados.

    A colisao com "pessoa" tem multiplas portas: "quero uma pessoa" (round 1),
    "me transfere pra uma pessoa" (round 2), resolvidas pelo invariante: quando
    pessoa/humano ocupam papel de DESTINO, carregam qualificador (pessoa fisica/
    juridica e vocabulario de contrato). Quando ocupam papel de INTERLOCUTOR ou
    ATRIBUTO, nao carregam. O modulo de opt-out registra a mesma licao com
    "nada" -- termo curto demais casa dentro de frase que nao e pedido.
    """
    assert pediu_humano(texto) is False


def test_a_forma_com_objeto_continua_disparando() -> None:
    assert pediu_humano("quero uma pessoa de verdade, nao um robo") is True
    assert pediu_humano("me transfere pra um atendente") is True
    assert pediu_humano("quero atendimento humano") is True


def test_falar_com_uma_pessoa_juridica_dispara_e_isso_e_aceito() -> None:
    """O residual que o invariante deixa de pe, declarado em vez de escondido.

    "pessoa" como INTERLOCUTOR nao leva qualificador, porque "falar com" ja a
    desambigua -- e sem isso "quero falar com uma pessoa", a frase do criterio
    de aceite da card, deixaria de disparar. O preco e este caso: quem pergunta
    sobre PJ usando "falar com" vai para um humano. Erra na direcao barata,
    porque quem pergunta assim provavelmente quer mesmo falar com alguem.
    """
    assert pediu_humano("posso falar com uma pessoa juridica sobre esse contrato?") is True

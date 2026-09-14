"""O que conta como pergunta para o teto da RN-05.5. TEC-149, D3."""

from mobia.domain.context.repositorio import perguntas_contaveis


def test_campo_conhecido_conta_uma_vez() -> None:
    assert len(perguntas_contaveis(("urgencia",))) == 1


def test_os_dois_extremos_do_orcamento_sao_uma_pergunta_so() -> None:
    """Perguntar "de quanto ate quanto" e UMA pergunta, e o modelo declara os
    dois nomes. `_marca_de` ja colapsa os dois no mesmo nome logico; contar
    cru gastaria dois do orcamento de oito por uma frase."""
    assert len(perguntas_contaveis(("faixa_preco_min", "faixa_preco_max"))) == 1


def test_nome_desconhecido_nao_conta() -> None:
    """O modelo as vezes devolve o TEXTO da pergunta em vez do nome do campo.
    Contar isso puniria o lead por um defeito nosso."""
    assert perguntas_contaveis(("qual o seu prazo?",)) == frozenset()


def test_entrada_vazia_e_conjunto_vazio() -> None:
    assert perguntas_contaveis(()) == frozenset()

import pytest

from mobia.domain.optout.deteccao import pediu_optout


@pytest.mark.parametrize(
    "texto",
    [
        "descadastrar",
        "quero descadastrar meu numero por favor",
        "pare de me mandar mensagem",
        "por gentileza, me tira da lista",
        "nao quero mais receber nada de voces",
        "nao me mande mais mensagens",
    ],
)
def test_termo_inequivoco_dispara_em_qualquer_posicao(texto: str) -> None:
    """Nenhum destes aparece em fala de quem procura imovel.

    Por isso a faixa inequivoca casa em qualquer posicao: o risco de falso
    positivo e desprezivel e deixar de detectar e violacao de LGPD.
    """
    assert pediu_optout(texto) is True


@pytest.mark.parametrize("texto", ["parar", "PARAR", "Parar!", "  sair  ", "stop", "cancelar"])
def test_termo_ambiguo_dispara_quando_e_a_mensagem_inteira(texto: str) -> None:
    """A mensagem de uma palavra so e o padrao real de quem quer sair.

    A normalizacao cobre caixa, acento, pontuacao e espaco nas bordas.
    """
    assert pediu_optout(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        "podemos parar por aqui hoje?",
        "quero sair do aluguel e comprar",
        "da pra cancelar a visita de quinta?",
        "tem como parar de me mostrar apartamento sem vaga?",
    ],
)
def test_termo_ambiguo_dentro_de_frase_nao_dispara(texto: str) -> None:
    """O caso que a faixa estrita existe para proteger.

    Um falso positivo aqui silencia lead legitimo para sempre, e o erro e
    invisivel: ele so ve o silencio.
    """
    assert pediu_optout(texto) is False


def test_texto_vazio_nao_dispara() -> None:
    assert pediu_optout("") is False

import pytest

from mobia.domain.optout.deteccao import pediu_optout


@pytest.mark.parametrize(
    "texto",
    [
        "descadastrar",
        "quero descadastrar meu numero por favor",
        "pare de me mandar mensagem",
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


@pytest.mark.parametrize(
    "texto", ["parar", "PARAR", "Parar!", "  sair  ", "stop", "cancelar", "me tira da lista"]
)
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


def test_refinamento_de_busca_nao_e_optout() -> None:
    """Casos que uma revisao achou silenciando lead legitimo com a lista antiga.

    A lista tinha "pare de mandar" e "nao quero mais receber" truncados.
    Estes vieram de review e nao devem disparar com a lista consertada, que
    exige o objeto de mensageria completo.
    """
    casos = [
        "pare de mandar apartamento sem vaga, so quero com vaga",
        "nao me mande mais casa, so apartamento",
        "nao quero mais receber apartamento sem vaga",
        "por favor, me tire da lista de interessados desse imovel",
    ]
    for texto in casos:
        assert pediu_optout(texto) is False


def test_texto_vazio_nao_dispara() -> None:
    assert pediu_optout("") is False

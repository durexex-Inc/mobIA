import pytest

from mobia.domain.optout.deteccao import pediu_optout


@pytest.mark.parametrize(
    "texto",
    [
        "descadastrar",
        "quero descadastrar meu numero por favor",
        "pare de me mandar mensagem",
        "nao quero mais receber mensagens de voces",
        "nao me mande mais mensagens",
    ],
)
def test_termo_inequivoco_dispara_em_qualquer_posicao(texto: str) -> None:
    """Cada termo carrega o OBJETO DE MENSAGERIA, e e o objeto que fecha a colisao.

    A versao original deste docstring dizia "nenhum destes aparece em fala de
    quem procura imovel", e isso era falso: "pare de mandar" e "nao quero mais
    receber" aparecem, e aparecem muito -- e o lead refinando a busca. O que
    torna a faixa segura em qualquer posicao nao e a raridade da frase, e sim
    o complemento: "mensagens", "mensagem", "meu contato". "pare de me mandar
    mensagens" nao casa com "pare de mandar apartamento sem vaga".

    Por isso a posicao nao importa nesta faixa: com o objeto exigido, o risco
    de falso positivo e desprezivel e deixar de detectar e violacao de LGPD.
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
        # Segunda leva, de uma revisao posterior: "nao quero mais receber
        # nada" ainda estava na faixa inequivoca e silenciava os tres. "nada"
        # e quantificador universal e aceita complemento partitivo -- nao e
        # objeto de mensageria, e por isso escapou do conserto anterior, que
        # so exigiu o objeto nos termos que ja o tinham.
        "nao quero mais receber nada sem vaga",
        "nao quero mais receber nada acima de 500 mil",
        "nao quero mais receber nada nessa regiao",
    ]
    for texto in casos:
        assert pediu_optout(texto) is False


def test_texto_vazio_nao_dispara() -> None:
    assert pediu_optout("") is False

import pytest

from mobia.domain.optout.deteccao import pediu_optout
from mobia.domain.titular.deteccao import pedido_de_titular
from mobia.domain.titular.vocabulario import TipoDeSolicitacao


@pytest.mark.parametrize(
    "texto",
    [
        "quero apagar meus dados",
        "Apague meus dados, por favor",
        "excluir meus dados",
        "deletem os meus dados",
        "podem esquecer meus dados?",
        "quero que apaguem todos os meus dados pessoais",
        # Achado da segunda revisao: o veto de qualificador de imovel e SO por
        # colagem ao objeto, entao um imovel/apartamento mencionado em outra
        # parte da mesma mensagem nao apaga um pedido explicito de eliminacao.
        "apaguem meus dados e parem de mandar imóveis",
        "quero apagar meus dados, não quero mais apartamento",
    ],
)
def test_pedido_de_eliminacao(texto: str) -> None:
    assert pedido_de_titular(texto) is TipoDeSolicitacao.ELIMINACAO


@pytest.mark.parametrize(
    "texto",
    [
        "quero meus dados",
        "quais dados vocês têm de mim?",
        "quero ver os meus dados",
        "me mandem uma cópia dos meus dados",
        # Mesmo achado do teste de eliminacao acima, do lado do acesso: o
        # apartamento nao esta colado ao objeto de dados, entao nao veta.
        "quero meus dados, e também ver o apartamento",
    ],
)
def test_pedido_de_acesso(texto: str) -> None:
    assert pedido_de_titular(texto) is TipoDeSolicitacao.ACESSO


@pytest.mark.parametrize(
    "texto",
    [
        "remover meu contato",
        "parar",
        "quero um apartamento",
        "os dados do imóvel estão errados",
        "vocês têm os dados do condomínio?",
        "não quero apagar meus dados",
        "",
    ],
)
def test_nao_e_pedido_de_titular(texto: str) -> None:
    assert pedido_de_titular(texto) is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (
            "quero uma cópia dos meus dados, exclusivamente por e-mail",
            TipoDeSolicitacao.ACESSO,
        ),
        ("esqueci de mandar meus dados pessoais", None),
        ("quero ver meus dados, o anuncio foi removido?", TipoDeSolicitacao.ACESSO),
        ("quero ver meus dados, é exclusivo?", TipoDeSolicitacao.ACESSO),
        ("meus dados foram apagados?", None),
    ],
)
def test_radical_dentro_de_outra_palavra_nao_e_eliminacao(
    texto: str, esperado: TipoDeSolicitacao | None
) -> None:
    """A primeira versao casava `exclu`, `esquec` e `remov` soltos, e as tres
    primeiras frases viravam ELIMINACAO -- opt-out, conversa encerrada e, sem
    recusa do ADMIN, o lead anonimizado sem volta."""
    assert pedido_de_titular(texto) is esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("vocês excluem meus dados pessoais depois de quanto tempo?", None),
        ("vocês apagam meus dados?", None),
        ("quero meus dados. vocês removem o apto da lista?", TipoDeSolicitacao.ACESSO),
    ],
)
def test_indicativo_plural_e_pergunta_nao_pedido(
    texto: str, esperado: TipoDeSolicitacao | None
) -> None:
    """O presente do indicativo no plural pergunta o que o sistema faz, nao
    pede que faca. So o subjuntivo ("apaguem", "excluam") e pedido."""
    assert pedido_de_titular(texto) is esperado


@pytest.mark.parametrize(
    "texto",
    [
        "apaga meus dados",
        "exclui meus dados",
        "remove meus dados",
        "remova meus dados pessoais",
        "esqueçam meus dados",
        "eliminem meus dados",
        "quero que vocês deletem meus dados",
        "peço para vocês apagarem meus dados",
    ],
)
def test_formas_conjugadas_de_pedir_continuam_eliminacao(texto: str) -> None:
    assert pedido_de_titular(texto) is TipoDeSolicitacao.ELIMINACAO


@pytest.mark.parametrize(
    "texto",
    [
        # Achado de revisao: "dados que voces tem" e substring livre e casava
        # sem exigir que os dados fossem do PROPRIO lead.
        "quais dados que vocês têm do condomínio?",
        "quais dados que vocês têm a respeito do imóvel anunciado?",
        # "meus" nao resgata: o qualificador de imovel/anuncio pesa mais, e o
        # "meus" ali e posse gramatical ("os dados que EU tenho do imovel"),
        # nao o titular pedindo os proprios dados pessoais.
        "quero meus dados do imóvel",
        # Achado da terceira revisao: "sobre" nao contrai com o artigo --
        # "sobre o imovel", nao "sobreimovel" -- e sem o artigo opcional entre
        # a preposicao e o substantivo estas quatro escapavam do veto.
        "apague meus dados sobre o imóvel",
        "quero meus dados sobre o imóvel",
        "quero ver meus dados sobre o apartamento",
        "me mandem uma cópia dos meus dados sobre a casa",
    ],
)
def test_qualificador_de_imovel_derruba_o_casamento(texto: str) -> None:
    assert pedido_de_titular(texto) is None


@pytest.mark.parametrize(
    "texto",
    [
        "quero apagar meus dados",
        "Apague meus dados, por favor",
        "excluir meus dados",
        "deletem os meus dados",
        "podem esquecer meus dados?",
        "quero que apaguem todos os meus dados pessoais",
        "quero meus dados",
        "quais dados vocês têm de mim?",
        "quero ver os meus dados",
        "me mandem uma cópia dos meus dados",
    ],
)
def test_pedido_de_titular_nao_depende_do_resultado_do_optout(texto: str) -> None:
    """A precedencia e sobre o QUE o turno faz, nao sobre os dois detectores
    concordarem. `pediu_optout` pode devolver qualquer coisa para estas frases --
    o unico contrato aqui e o de `pedido_de_titular`.
    """
    pedido_de_titular(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Quero agendar uma visita, meus dados: Joao, 11 99999-0000",
        "Ja mandei meus dados, quero ver o apartamento",
        "Quais dados pessoais voces precisam pra visita?",
        "quero corrigir meus dados",
        "Quero falar com um corretor, ele ja tem meus dados?",
    ],
)
def test_frase_de_venda_com_meus_dados_nao_vira_acesso(texto: str) -> None:
    """A regressao principal da revisao final: "quero", "ver" e "quais" eram
    sinais soltos, e bastava a mensagem conter "meus dados" em qualquer ponto
    para uma frase de venda virar pedido de ACESSO -- o turno registrava a
    solicitacao, respondia com o texto fixo e nunca chamava o modelo. O verbo
    de acesso tem de estar ligado ao objeto."""
    assert pedido_de_titular(texto) is None


def test_remover_contato_e_optout_mas_nao_pedido_de_titular() -> None:
    """A colisao nomeada no desenho D3: fala de CONTATO e opt-out, fala de
    DADOS e pedido de titular. "remover meu contato" e so o primeiro.
    """
    assert pedido_de_titular("remover meu contato") is None
    assert pediu_optout("remover meu contato") is True


def test_ambiguidade_aceita_do_indicativo_singular() -> None:
    """O imperativo singular ("apaga meus dados") e o indicativo de terceira
    pessoa sao a mesma palavra. Manter o pedido mais comum custa este falso
    positivo, declarado no comentario de `_TERMINACOES_DE_PEDIDO` -- o teste
    prende a escolha, para que muda-la seja deliberado."""
    assert pedido_de_titular("o sistema apaga meus dados depois?") is (TipoDeSolicitacao.ELIMINACAO)

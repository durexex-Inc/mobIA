"""TEC-380: o dado sensivel sai antes de gravar, e o pedido de imovel fica."""

import pytest

from mobia.domain.privacidade.redacao import (
    MARCADOR_DE_ACESSIBILIDADE,
    MARCADOR_DE_DADO_SENSIVEL,
    redigir,
    redigir_payload,
)

S = MARCADOR_DE_DADO_SENSIVEL
A = MARCADOR_DE_ACESSIBILIDADE


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # Saude, em qualquer posicao -- inclusive de terceiro.
        ("tenho diabetes e quero térreo", f"tenho {S} e quero térreo"),
        ("Minha mãe tem Alzheimer", f"Minha mãe tem {S}"),
        (
            "meu filho é autista, precisa de quarto só dele",
            f"meu filho é {S}, precisa de quarto só dele",
        ),
        ("estou em tratamento de câncer", f"estou em tratamento de {S}"),
        ("sou HIV positivo", f"sou {S} positivo"),
        ("estou grávida de 5 meses", f"estou {S} de 5 meses"),
        ("faço hemodiálise 3x por semana", f"faço {S} 3x por semana"),
        # Filiacao sindical e orientacao sexual inequivoca.
        ("sou sindicalizado", f"sou {S}"),
        ("somos um casal homoafetivo", f"somos um casal {S}"),
        # Identitarios, so em primeira pessoa.
        ("sou evangélica e quero perto da igreja", f"sou {S} e quero perto da igreja"),
        ("Eu sou muito católico", f"Eu sou muito {S}"),
        ("somos de esquerda", f"somos {S}"),
        ("sou negra", f"sou {S}"),
        ("sou gay e moro sozinho", f"sou {S} e moro sozinho"),
    ],
)
def test_o_trecho_sensivel_vira_o_marcador(texto: str, esperado: str) -> None:
    assert redigir(texto).texto == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("sou cadeirante, preciso de térreo", f"sou {A}, preciso de térreo"),
        ("meu pai usa cadeira de rodas", f"meu pai usa {A}"),
        ("tenho mobilidade reduzida", f"tenho {A}"),
        ("minha filha é deficiente visual", f"minha filha é {A}"),
        ("Tem vaga PCD?", f"Tem vaga {A}?"),
    ],
)
def test_a_acessibilidade_vira_o_requisito_sem_a_condicao(texto: str, esperado: str) -> None:
    """Decisao do Eduardo (D2): o agente continua sabendo que precisa de
    terreo ou elevador, e a condicao nao e gravada."""
    assert redigir(texto).texto == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "procuro apartamento de 2 quartos no Centro até 500 mil",
        "quero perto da Católica",
        "perto da igreja matriz",
        "rua Evangelista de Souza",
        "a portaria tem biometria?",
        "prédio branco com varanda",
        "gosto da vista da direita",
        "o bairro é bem tranquilo",
        "quero um imóvel de esquina",
        "que transtorno essa obra",
    ],
)
def test_conversa_de_imovel_passa_inteira(texto: str) -> None:
    redacao = redigir(texto)
    assert redacao.texto == texto
    assert redacao.trechos == 0


def test_caixa_e_acento_nao_escapam() -> None:
    assert redigir("DIABÉTICA").texto == S
    assert redigir("depressao").texto == S


def test_o_resto_do_texto_fica_com_acento_e_caixa() -> None:
    assert redigir("Olá! Tenho ASMA, então nada de mofo.").texto == (
        f"Olá! Tenho {S}, então nada de mofo."
    )


def test_quebra_de_linha_no_meio_da_locucao() -> None:
    assert redigir("uso cadeira\nde rodas").texto == f"uso {A}"


def test_conta_os_trechos() -> None:
    assert redigir("tenho asma e diabetes").trechos == 2


@pytest.mark.parametrize("texto", [S, A, f"tenho {S} e sou {A}"])
def test_redigir_de_novo_nao_muda_nada(texto: str) -> None:
    """A reentrega e a retentativa passam pelo mesmo caminho: o marcador nao
    pode casar com a propria regra."""
    assert redigir(texto) == (texto, 0)


def test_texto_vazio() -> None:
    assert redigir("") == ("", 0)


def test_o_envelope_e_redigido_em_toda_string_e_so_nas_strings() -> None:
    envelope = {
        "id": "wamid.X",
        "type": "text",
        "text": {"body": "tenho diabetes"},
        "image": {"caption": "sou cadeirante", "id": "m1"},
        "lista": ["sou católica", 3],
        "numero": 7,
    }

    redigido, trechos = redigir_payload(envelope)

    assert trechos == 3
    assert redigido == {
        "id": "wamid.X",
        "type": "text",
        "text": {"body": f"tenho {S}"},
        "image": {"caption": f"sou {A}", "id": "m1"},
        "lista": [f"sou {S}", 3],
        "numero": 7,
    }
    # O original nao e alterado no lugar: a ingestao ainda precisa dele.
    assert envelope["text"] == {"body": "tenho diabetes"}

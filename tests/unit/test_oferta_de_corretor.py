"""A regra que decide se a oferta de corretor e anexada (TEC-272).

Exercita `texto_com_oferta`, que e a funcao que o `turno.py` chama -- e nao
uma copia da condicao. A diferenca importa: um teste que replicasse a regra
seguiria verde depois de a producao mudar.
"""

import pytest

from mobia.domain.agente.identificacao import (
    TEXTO_DA_IDENTIFICACAO,
    TEXTO_DA_OFERTA_DE_CORRETOR,
    texto_com_oferta,
)


def test_pergunta_neutra_recebe_a_oferta() -> None:
    """O primeiro criterio de aceite da card."""
    resposta = "Sim, sou um assistente virtual da imobiliária."

    final = texto_com_oferta("vc e um robo?", resposta)

    assert final == f"{resposta}\n\n{TEXTO_DA_OFERTA_DE_CORRETOR}"


def test_quem_nao_perguntou_nada_nao_recebe_oferta() -> None:
    """O segundo criterio de aceite: a oferta nao vira assinatura de rodape."""
    resposta = "Temos três apartamentos de 2 quartos na zona sul."

    assert texto_com_oferta("quero um apto de 2 quartos", resposta) == resposta


def test_nao_duplica_quando_o_modelo_ja_ofereceu() -> None:
    """Os casos 3 e 4 da sondagem da TEC-139, em que o modelo oferece sozinho."""
    resposta = (
        "Sou um assistente virtual. Se preferir falar direto com um corretor, "
        "é só me dizer que eu já providencio esse contato."
    )

    assert texto_com_oferta("isso e automatico ou tem alguem ai?", resposta) == resposta


def test_nao_duplica_quando_a_conversa_e_nova() -> None:
    """A identificacao proativa ja ofereceu no prefixo, e o append se cala.

    E a razao de a guarda olhar o texto FINAL e nao a resposta crua do modelo:
    sem isso, este caso precisaria de regra propria.
    """
    resposta = "Sim, sou um assistente virtual."
    com_identificacao = f"{TEXTO_DA_IDENTIFICACAO}\n\n{resposta}"

    assert texto_com_oferta("vc e um robo?", com_identificacao) == com_identificacao


def test_corpo_ausente_nao_levanta() -> None:
    """`corpo` e `str | None` em `executar_turno`, como `pediu_optout` ja trata la."""
    assert texto_com_oferta(None, "qualquer resposta") == "qualquer resposta"
    assert texto_com_oferta("", "qualquer resposta") == "qualquer resposta"


@pytest.mark.parametrize(
    "texto_deterministico",
    [
        "Deixa eu confirmar algumas coisas com um corretor para não te passar informação errada.",
        "Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui.",
    ],
)
def test_nao_duplica_nas_trilhas_deterministicas(texto_deterministico: str) -> None:
    """Quando o turno respondeu por uma trilha que ja oferece, o append se cala.

    Os textos aqui sao excertos verbatim, nao parafrase: o primeiro e a
    primeira frase de `TEXTO_DA_BUSCA_INCONCLUSIVA` e o segundo e a frase do
    meio de `TEXTO_DO_LIMITE_DE_PERGUNTAS` (`turno.py`), cada um recortado ate
    onde basta para exercitar a palavra "corretor". Fica assim, e nao
    parafraseado, porque quem guarda as constantes de verdade e
    `test_todo_texto_deterministico_com_corretor_e_reconhecido`, que as deriva
    por importacao -- transcreve-las por extenso aqui criaria uma segunda copia
    para envelhecer.
    """
    assert texto_com_oferta("vc e um robo?", texto_deterministico) == texto_deterministico

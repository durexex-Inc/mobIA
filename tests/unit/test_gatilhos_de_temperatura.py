"""Os tres gatilhos que forcam QUENTE, detectados na fala do lead.

TEC-151, RN-06.3. Sem banco e sem chamada paga: a funcao e pura.

**A assimetria de erro e o INVERSO do opt-out**, e e por isso que este
arquivo tem mais teste negativo que positivo. No opt-out, deixar de detectar
e violacao de LGPD e a faixa inequivoca e generosa. Aqui o falso positivo
forca QUENTE PERMANENTEMENTE (a RN-06.3 diz "ate intervencao humana") e toca
o telefone do corretor, e nao existe tela para desfazer -- a TEC-192 nao
existe. Permanente e sem desfazer vence recuperavel: faixa estrita.
"""

import pytest

from mobia.domain.context.gatilhos import (
    MOTIVO_CORRETOR,
    MOTIVO_PROPOSTA,
    MOTIVO_VISITA,
    gatilhos_de,
)


@pytest.mark.parametrize(
    "texto",
    [
        "oi bom dia, sou eu de novo. fechei financiamento e quero agendar visita no apartamento",
        "da pra remarcar uma visita pra essa semana?",
        "queria marcar uma visita",
        "podemos agendar a visita pra sabado?",
    ],
)
def test_pedido_de_visita_dispara(texto: str) -> None:
    """Os dois primeiros sao falas reais do corpus -- `compra.yaml:139` e
    `follow_up.yaml:18`."""
    assert gatilhos_de(texto) == (MOTIVO_VISITA,)


@pytest.mark.parametrize(
    "texto",
    [
        "quero falar com um corretor",
        "tem como falar com o corretor?",
        "prefiro falar com uma pessoa",
        "quero falar com atendente",
    ],
)
def test_pedido_de_corretor_dispara(texto: str) -> None:
    assert gatilhos_de(texto) == (MOTIVO_CORRETOR,)


@pytest.mark.parametrize(
    "texto",
    [
        "quero fazer uma proposta",
        "posso enviar uma proposta hoje?",
        "quando posso assinar o contrato?",
        "vamos fechar negocio",
    ],
)
def test_mencao_a_proposta_ou_contrato_dispara(texto: str) -> None:
    assert gatilhos_de(texto) == (MOTIVO_PROPOSTA,)


def test_plantao_de_visita_nao_dispara() -> None:
    """O caso real do corpus que a estritez existe para proteger.

    `evals/corpus/compra.yaml:318` -- "voces tem plantao de visita no fim de
    semana?". E pergunta sobre horario de funcionamento, nao pedido de visita.
    Um detector que casasse `visita` em qualquer posicao marcaria este lead
    QUENTE para sempre, e ninguem teria como desfazer.
    """
    assert gatilhos_de("voces tem plantao de visita no fim de semana?") == ()


@pytest.mark.parametrize(
    "texto",
    [
        "quanto custa uma visita?",
        "a visita foi otima, obrigado",
        "o corretor de outra imobiliaria falou 500 mil",
        "recebi uma proposta de outra empresa e queria comparar",
        "o contrato de aluguel atual vence em marco",
    ],
)
def test_o_objeto_sem_o_verbo_de_acao_nao_dispara(texto: str) -> None:
    """O criterio da faixa e o VERBO junto do objeto, e nao o objeto sozinho.

    Mesma forma que fecha a colisao no opt-out, onde e o objeto de mensageria
    que faz "pare de me mandar mensagens" nao casar com "pare de mandar
    apartamento sem vaga".
    """
    assert gatilhos_de(texto) == ()


def test_dois_motivos_no_mesmo_turno() -> None:
    """Tupla e nao motivo unico: precedencia aqui descartaria informacao real.

    A ordem de saida e a de `_TERMOS_POR_MOTIVO`, entao o teste pode comparar
    por igualdade em vez de por conjunto -- mesma escolha de
    `causas_do_recalculo`.
    """
    assert gatilhos_de("quero fazer uma proposta e agendar visita") == (
        MOTIVO_VISITA,
        MOTIVO_PROPOSTA,
    )


@pytest.mark.parametrize(
    "texto",
    ["QUERO AGENDAR VISITA", "Quero agendar visita!!!", "  quero   agendar  visita  "],
)
def test_a_normalizacao_cobre_caixa_pontuacao_e_espaco(texto: str) -> None:
    assert gatilhos_de(texto) == (MOTIVO_VISITA,)


def test_o_acento_nao_impede_a_deteccao() -> None:
    """Lead digita acento, e a normalizacao dobra antes de comparar."""
    assert gatilhos_de("vamos fechar negócio então") == (MOTIVO_PROPOSTA,)


@pytest.mark.parametrize("texto", ["", "   ", "!!!", "123"])
def test_texto_sem_letra_devolve_vazio(texto: str) -> None:
    assert gatilhos_de(texto) == ()

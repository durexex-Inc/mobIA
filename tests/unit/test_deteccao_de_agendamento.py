"""O pedido de visita, o assentimento e a recusa. TEC-371, D2.

A faixa aqui e mais larga que a de `context/gatilhos.py` de proposito, e os
casos que separam as duas estao nos testes: "posso ver o apartamento amanha?"
dispara aqui e NAO dispara la, porque as assimetrias de erro sao inversas.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.agendamento.deteccao import (
    RespostaAoLembrete,
    confirmou,
    quer_agendar,
    recusou,
    respondeu_ao_lembrete,
)
from mobia.domain.context.gatilhos import gatilhos_de

SP = ZoneInfo("America/Sao_Paulo")
# Uma terca-feira as 10h: ha "quinta" e "amanha" a frente dentro do horizonte.
AGORA = datetime(2026, 9, 29, 10, 0, tzinfo=SP)


@pytest.mark.parametrize(
    "fala",
    [
        "quero agendar uma visita",
        "podemos marcar visita?",
        "gostaria de visitar",
        "posso ver o apartamento amanha?",
        "da pra conhecer o imovel?",
        "queria fazer uma visita ao imovel",
        "bom dia, queria agendar horario",
        "quero conhecer a casa pessoalmente",
    ],
)
def test_o_pedido_explicito_dispara(fala: str) -> None:
    assert quer_agendar(fala, agora=AGORA) is True


@pytest.mark.parametrize(
    "fala",
    [
        # A TEC-372 e a TEC-172 sao donas destes, e oferecer horario novo a
        # quem quis desmarcar e o oposto do que a fala diz.
        "quero desmarcar a visita",
        "preciso remarcar",
        "vamos cancelar a visita de quinta",
        # Negacao.
        "nao quero marcar visita",
        "nao posso visitar essa semana",
        # A fala real do corpus que a `gatilhos.py` nomeia: pergunta sobre
        # horario de funcionamento, nao pedido de visita.
        "voces tem plantao no fim de semana?",
        # Enquadramento sem data.
        "pode ser mais barato?",
        # Data sem enquadramento.
        "meu contrato vence dia 15",
        "recebo o fgts dia 10",
        # Nada.
        "quanto e o condominio?",
        "",
        "!!!",
    ],
)
def test_o_que_nao_e_pedido_nao_dispara(fala: str) -> None:
    assert quer_agendar(fala, agora=AGORA) is False


def test_a_data_proposta_dispara_sem_a_palavra_visita() -> None:
    """O primeiro cenario do Gherkin da card, e a razao da segunda via."""
    assert quer_agendar("pode ser quinta de manha?", agora=AGORA) is True
    assert quer_agendar("que tal amanha a tarde?", agora=AGORA) is True


def test_a_pausa_depois_do_nao_deixa_o_pedido_valer() -> None:
    assert quer_agendar("nao, quero marcar visita sim", agora=AGORA) is True


def test_uma_ocorrencia_limpa_basta() -> None:
    fala = "nao quero marcar visita hoje, mas semana que vem quero marcar visita"
    assert quer_agendar(fala, agora=AGORA) is True


def test_a_faixa_e_mais_larga_que_a_dos_gatilhos() -> None:
    """O caso que a docstring de `gatilhos.py` nomeia como custo de recall dela.

    Se um dia os dois detectores concordarem sobre esta fala, alguem juntou
    as duas listas sem reabrir as duas assimetrias -- que e exatamente o que
    a docstring deste modulo pede que nao se faca.
    """
    fala = "posso ver o apartamento amanha?"
    assert quer_agendar(fala, agora=AGORA) is True
    assert gatilhos_de(fala) == ()


@pytest.mark.parametrize(
    "fala",
    ["sim", "isso mesmo", "pode marcar", "fechado", "ok", "perfeito", "ta bom", "confirmo"],
)
def test_o_assentimento_dispara(fala: str) -> None:
    assert confirmou(fala) is True


@pytest.mark.parametrize("fala", ["nao pode ser", "nao, obrigado", "assim nao", "simples assim"])
def test_o_que_nao_e_assentimento_nao_dispara(fala: str) -> None:
    assert confirmou(fala) is False


def test_a_correcao_com_pausa_conta_como_assentimento() -> None:
    """ "nao, pode ser" e o lead se corrigindo, e por isso `confirmou` vem antes."""
    assert confirmou("nao, pode ser") is True


@pytest.mark.parametrize(
    "fala", ["nao", "nao posso nesse horario", "nenhum deles", "prefiro outro dia", "impossivel"]
)
def test_a_recusa_dispara(fala: str) -> None:
    assert recusou(fala) is True


@pytest.mark.parametrize("fala", ["sim", "pode marcar", "", "???"])
def test_o_que_nao_e_recusa_nao_dispara(fala: str) -> None:
    assert recusou(fala) is False


@pytest.mark.parametrize("fala", ["", "   ", "!!!", "123 456"])
def test_texto_sem_letra_nao_levanta(fala: str) -> None:
    assert quer_agendar(fala, agora=AGORA) is False
    assert confirmou(fala) is False
    assert recusou(fala) is False


# --- TEC-372: a resposta ao lembrete de 24 horas -----------------------------


@pytest.mark.parametrize(
    "fala", ["sim", "confirmo", "estarei la", "pode contar comigo", "tudo certo"]
)
def test_a_presenca_confirmada_dispara(fala: str) -> None:
    assert respondeu_ao_lembrete(fala) is RespostaAoLembrete.CONFIRMA


@pytest.mark.parametrize(
    "fala",
    ["remarcar", "podemos mudar o horario?", "da pra adiar?", "prefiro outro dia", "reagenda"],
)
def test_a_remarcacao_dispara(fala: str) -> None:
    assert respondeu_ao_lembrete(fala) is RespostaAoLembrete.REMARCAR


@pytest.mark.parametrize(
    "fala",
    ["cancelar", "desmarcar", "nao vou poder ir", "nao vou conseguir ir", "desisti"],
)
def test_o_cancelamento_dispara(fala: str) -> None:
    assert respondeu_ao_lembrete(fala) is RespostaAoLembrete.CANCELAR


@pytest.mark.parametrize(
    "fala",
    [
        # **O caso central da assimetria.** "nao" sozinho e ambiguo entre "nao
        # vou" e "nao nesse horario", e as duas leituras tem desfechos
        # opostos. Afrouxar isto reabre a assimetria sem ninguem decidir --
        # ver a docstring do detector.
        "nao",
        "nao sei",
        "talvez",
        "quanto custa o condominio?",
        "obrigado",
        "",
        "!!!",
    ],
)
def test_o_que_nao_e_resposta_fica_em_silencio(fala: str) -> None:
    assert respondeu_ao_lembrete(fala) is None


def test_remarcar_vence_cancelar_quando_os_dois_casam() -> None:
    """O caminho reversivel ganha: remarcar oferece janelas e o original fica de pe."""
    assert respondeu_ao_lembrete("nao vou poder ir, remarca?") is RespostaAoLembrete.REMARCAR


def test_a_negacao_do_cancelamento_nao_cancela() -> None:
    """ "nao quero cancelar" e o oposto de cancelar, e a guarda de pausa le isso."""
    assert respondeu_ao_lembrete("nao quero cancelar") is None


def test_a_pausa_depois_do_nao_deixa_o_cancelamento_valer() -> None:
    assert respondeu_ao_lembrete("nao, cancela por favor") is RespostaAoLembrete.CANCELAR

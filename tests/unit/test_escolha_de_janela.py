"""Qual das janelas o lead escolheu. TEC-371, D5.

As tres janelas destes testes sao sempre as mesmas -- quinta as 9h, quinta as
11h e sexta as 11h --, escolhidas para exercitar os dois casos que separam
uma escolha de um chute: a hora que se repete em dois dias e o dia que tem
duas janelas.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mobia.domain.agendamento.escolha import Escolhida, NaoEscolheu, escolher
from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.propostas import Proposta
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao

SP = ZoneInfo("America/Sao_Paulo")
# Terca-feira, 29 de setembro de 2026, as 10h.
AGORA = datetime(2026, 9, 29, 10, 0, tzinfo=SP)
CORRETOR = uuid.uuid4()


def _proposta(ordinal: int, quando: datetime) -> Proposta:
    return Proposta(
        ordinal=ordinal,
        janela=Intervalo(quando, quando + timedelta(hours=1)),
        corretor_id=CORRETOR,
        imovel_id=None,
        tipo=TipoDeCompromisso.VISITA_PRESENCIAL,
        motivo=MotivoDaAlocacao.MATCH_EXATO,
    )


QUINTA_9H = datetime(2026, 10, 1, 9, 0, tzinfo=SP)
QUINTA_11H = datetime(2026, 10, 1, 11, 0, tzinfo=SP)
SEXTA_11H = datetime(2026, 10, 2, 11, 0, tzinfo=SP)

TRES = [_proposta(1, QUINTA_9H), _proposta(2, QUINTA_11H), _proposta(3, SEXTA_11H)]


def _escolhida(texto: str, propostas: list[Proposta] | None = None) -> Proposta:
    resultado = escolher(texto, propostas if propostas is not None else TRES, agora=AGORA)
    assert isinstance(resultado, Escolhida)
    return resultado.proposta


@pytest.mark.parametrize(
    ("fala", "ordinal"),
    [
        ("a primeira", 1),
        ("a segunda", 2),
        ("a terceira", 3),
        ("o primeiro", 1),
        ("a ultima", 3),
        ("1", 1),
        ("2", 2),
        ("a 3", 3),
        ("opcao 2", 2),
    ],
)
def test_o_ordinal_escolhe_pela_posicao(fala: str, ordinal: int) -> None:
    assert _escolhida(fala).ordinal == ordinal


def test_ordinal_fora_da_faixa_nao_escolhe() -> None:
    duas = TRES[:2]
    assert isinstance(escolher("a terceira", duas, agora=AGORA), NaoEscolheu)


def test_o_ordinal_vence_o_dia_da_semana() -> None:
    """O custo declarado da D5, num teste que o documenta em vez de esconder.

    Quem responde "a segunda" querendo segunda-feira recebe a segunda janela
    -- e le a data absoluta na pergunta de confirmacao do turno B, que e a
    protecao da RN-11.3 contra o RT-10.
    """
    assert _escolhida("a segunda").ordinal == 2


def test_segunda_feira_por_extenso_nao_e_ordinal() -> None:
    """Escrito por extenso o lead nomeou o dia, e nenhuma proposta cai nele."""
    assert isinstance(escolher("segunda-feira", TRES, agora=AGORA), NaoEscolheu)


def test_a_hora_unica_escolhe() -> None:
    assert _escolhida("as 9h").ordinal == 1


def test_a_hora_repetida_em_dois_dias_nao_escolhe() -> None:
    """Duas janelas as 11h: "as 11h" nao disse qual, e chutar gravaria a errada."""
    assert isinstance(escolher("as 11h", TRES, agora=AGORA), NaoEscolheu)


def test_o_dia_e_a_hora_juntos_escolhem_a_exata() -> None:
    assert _escolhida("quinta as 11h").ordinal == 2
    assert _escolhida("sexta as 11h").ordinal == 3


def test_o_dia_com_uma_janela_so_escolhe() -> None:
    assert _escolhida("sexta").ordinal == 3


def test_o_dia_com_duas_janelas_nao_escolhe() -> None:
    assert isinstance(escolher("quinta", TRES, agora=AGORA), NaoEscolheu)


def test_o_periodo_com_uma_janela_so_escolhe() -> None:
    """Sexta de manha tem so a das 11h. Quinta de manha tem duas (9h e 11h),
    e e por isso que o periodo nao serve para escolher naquele dia."""
    assert _escolhida("sexta de manha").ordinal == 3


def test_o_periodo_com_duas_janelas_nao_escolhe() -> None:
    assert isinstance(escolher("quinta de manha", TRES, agora=AGORA), NaoEscolheu)


def test_o_periodo_sem_janela_nenhuma_nao_escolhe() -> None:
    assert isinstance(escolher("quinta a tarde", TRES, agora=AGORA), NaoEscolheu)


@pytest.mark.parametrize(
    "fala",
    [
        "quanto e o condominio?",
        "tem vaga de garagem?",
        "",
        "!!!",
        "obrigado",
    ],
)
def test_o_que_nao_e_escolha_nao_escolhe(fala: str) -> None:
    assert isinstance(escolher(fala, TRES, agora=AGORA), NaoEscolheu)


def test_sem_proposta_nenhuma_nao_escolhe() -> None:
    assert isinstance(escolher("a primeira", [], agora=AGORA), NaoEscolheu)


def test_nao_levanta_para_texto_nenhum() -> None:
    for fala in ("", "   ", "\x00", "a" * 5000, "31/02", "99h"):
        assert escolher(fala, TRES, agora=AGORA) is not None

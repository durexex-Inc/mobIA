"""O teto de 8 perguntas da RN-05.5. TEC-149, D3 e D4."""

from mobia.domain.context.qualificacao import TETO_DE_PERGUNTAS, excedeu_o_teto


def test_o_teto_e_oito() -> None:
    """Pinado: e o numero da RN-05.5, e mudar sem mudar a regra e defeito."""
    assert TETO_DE_PERGUNTAS == 8


def test_conversa_nova_nao_excede() -> None:
    assert excedeu_o_teto(0, 1) is False


def test_a_oitava_pergunta_ainda_passa() -> None:
    """Sete gastas mais uma sao oito, e a regra diz "nao mais de 8"."""
    assert excedeu_o_teto(7, 1) is False


def test_a_nona_nao_passa() -> None:
    assert excedeu_o_teto(8, 1) is True


def test_duas_perguntas_sobre_sete_gastas_suprimem_o_turno_inteiro() -> None:
    """A consequencia declarada da D4: com duas perguntas num turno o teto
    morde entre 7 e 8, e a oitava nunca e feita. A alternativa seria entregar
    meia pergunta, e a prosa e um texto so."""
    assert excedeu_o_teto(7, 2) is True


def test_turno_que_nao_pergunta_nunca_excede() -> None:
    """Depois do teto o agente continua respondendo duvida e mostrando
    imovel: "nao faz mais perguntas" nao e "para de conversar"."""
    assert excedeu_o_teto(99, 0) is False

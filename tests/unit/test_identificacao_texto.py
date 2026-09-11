from mobia.domain.agente.identificacao import (
    SEPARADOR_DA_IDENTIFICACAO,
    TEXTO_DA_IDENTIFICACAO,
)


def test_o_texto_se_identifica_como_assistente_virtual() -> None:
    """A RN-04.1 em letra: o agente diz que e assistente virtual. Nao basta o
    prompt saber -- o lead precisa ler.
    """
    baixo = TEXTO_DA_IDENTIFICACAO.lower()
    assert "assistente virtual" in baixo


def test_o_texto_oferece_o_corretor() -> None:
    """A terceira regra de negocio da card, no caminho proativo. Sem isso a
    transparencia vira aviso, e a RN-B01 pede saida para humano disponivel.
    """
    assert "corretor" in TEXTO_DA_IDENTIFICACAO.lower()


def test_o_texto_nao_finge_ser_pessoa() -> None:
    """A RN-04.1 proibe fingir ser pessoa fisica.

    A lista proibida encoda a regra e nao a forma: "sou o assistente virtual"
    e o CUMPRIMENTO da regra, nao a violacao dela -- proibir a construcao
    "sou o" reprovaria justamente o texto certo. O que nao pode aparecer e a
    alegacao de ser gente.
    """
    baixo = TEXTO_DA_IDENTIFICACAO.lower()
    for proibido in (
        "sou uma pessoa",
        "sou humano",
        "sou humana",
        "nao sou um robo",
        "nao sou uma maquina",
    ):
        assert proibido not in baixo
    assert "assistente virtual" in baixo


def test_o_texto_e_curto_o_bastante_para_preceder_uma_resposta() -> None:
    """Ele vai na FRENTE de outra mensagem em quatro das cinco trilhas. Longo,
    empurra a resposta para baixo e vira parede de texto -- exatamente o que o
    teto de 600 caracteres da RN-04.2 existe para evitar.
    """
    assert 0 < len(TEXTO_DA_IDENTIFICACAO) <= 160


def test_o_separador_nao_cola_as_duas_mensagens() -> None:
    assert SEPARADOR_DA_IDENTIFICACAO.strip() == ""
    assert "\n" in SEPARADOR_DA_IDENTIFICACAO

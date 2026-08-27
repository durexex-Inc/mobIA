from mobia.domain.context.montagem import montar_prompt
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico, mensagem_transiente


def test_mensagem_transiente_nao_precisa_de_sessao() -> None:
    """O eval nao pode depender de Postgres. O corpo e cifrado com AAD ligado
    ao id da linha, entao a linha precisa de um id proprio mesmo sem INSERT.
    """
    linha = mensagem_transiente("quero comprar um apartamento", papel=MessageRole.LEAD)

    assert linha.id is not None
    assert linha.text_body is not None
    assert linha.role == MessageRole.LEAD


def test_o_texto_original_chega_ao_prompt() -> None:
    """O id gerado antes da cifra deve coincidir com o id da linha.

    Se cifrado com AAD errado, decrypt levanta DecryptionError e aborta a
    montagem do prompt. O teste garante que o id passado para encrypt eh o
    mesmo que sera usado em decrypt durante montar_prompt.
    """
    contexto = contexto_do_historico(
        [
            (MessageRole.LEAD, "quero comprar um apartamento"),
            (MessageRole.AGENTE, "que bairro voce procura?"),
            (MessageRole.LEAD, "na verdade quero alugar"),
        ],
        sistema="sistema de teste",
    )

    prompt = montar_prompt(contexto, omitir_sistema=True)

    assert "quero comprar um apartamento" in prompt
    assert "que bairro voce procura?" in prompt
    assert "na verdade quero alugar" in prompt
    assert "(mensagem sem texto)" not in prompt


def test_a_ordem_do_historico_e_preservada() -> None:
    contexto = contexto_do_historico(
        [(MessageRole.LEAD, "primeira"), (MessageRole.LEAD, "segunda")],
        sistema="sistema de teste",
    )

    prompt = montar_prompt(contexto, omitir_sistema=True)

    assert prompt.index("primeira") < prompt.index("segunda")

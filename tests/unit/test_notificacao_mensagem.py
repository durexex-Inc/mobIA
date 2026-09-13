from mobia.domain.notificacao.mensagem import TEXTO_SEM_RESUMO, montar

LINK = "https://painel.exemplo/conversas/whatsapp/5511911112222"
RESUMO = "## Quem e o lead\nlead do whatsapp, 12 mensagens"


def test_o_corpo_carrega_o_resumo_e_o_link() -> None:
    _, corpo = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="NORMAL")

    assert RESUMO in corpo
    assert LINK in corpo


def test_o_assunto_carrega_etiqueta_e_prioridade() -> None:
    assunto, _ = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="ALTA")

    assert "lead-quente" in assunto
    assert "ALTA" in assunto


def test_sem_resumo_o_corpo_diz_que_faltou_e_mantem_o_link() -> None:
    """D2: silencio seria pior que resumo faltando."""
    _, corpo = montar(resumo=None, link=LINK, etiqueta="lead-quente", prioridade="NORMAL")

    assert TEXTO_SEM_RESUMO in corpo
    assert LINK in corpo
    assert "None" not in corpo

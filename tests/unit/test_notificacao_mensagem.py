from mobia.domain.notificacao.mensagem import TEXTO_SEM_RESUMO, montar

LINK = "https://painel.exemplo/conversas/whatsapp/5511911112222"
RESUMO = "## Quem e o lead\nlead do whatsapp, 12 mensagens"


def test_o_corpo_carrega_o_resumo_e_o_link() -> None:
    aviso = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="NORMAL")

    assert RESUMO in aviso.corpo
    assert LINK in aviso.corpo


def test_o_assunto_carrega_etiqueta_e_prioridade() -> None:
    aviso = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="ALTA")

    assert "lead-quente" in aviso.assunto
    assert "ALTA" in aviso.assunto


def test_sem_resumo_o_corpo_diz_que_faltou_e_mantem_o_link() -> None:
    """D2: silencio seria pior que resumo faltando."""
    aviso = montar(resumo=None, link=LINK, etiqueta="lead-quente", prioridade="NORMAL")

    assert TEXTO_SEM_RESUMO in aviso.corpo
    assert LINK in aviso.corpo
    assert "None" not in aviso.corpo


def test_os_campos_estruturados_sobrevivem_a_montagem() -> None:
    """TEC-281: o WhatsApp precisa deles SEPARADOS, nao dentro da prosa.

    Ate aquela card `montar` concatenava os tres e devolvia so `(assunto,
    corpo)`. O canal de template teria de extrair o link de volta por regex --
    parsear prosa que nos mesmos acabamos de montar.
    """
    aviso = montar(resumo=RESUMO, link=LINK, etiqueta="lead-quente", prioridade="ALTA")

    assert aviso.etiqueta == "lead-quente"
    assert aviso.prioridade == "ALTA"
    assert aviso.link == LINK


def test_sem_template_dado_o_aviso_nasce_sem_template() -> None:
    """`None` afirma que este aviso nao tem template aprovado -- ver o campo.

    E o caso de `escalar_vencidos`, cuja mensagem ao gerente e outra e nao
    pode sair com o template do aviso de lead pronto.
    """
    assert montar(resumo=RESUMO, link=LINK, etiqueta="e", prioridade="p").template is None
    assert (
        montar(resumo=RESUMO, link=LINK, etiqueta="e", prioridade="p", template="t").template == "t"
    )

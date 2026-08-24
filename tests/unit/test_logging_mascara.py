import logging

import structlog


def test_telefone_em_campo_livre_sai_mascarado(caplog) -> None:
    """Segunda linha de defesa: pega o telefone que escapou para um campo qualquer."""
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", detalhe="retornar para 5511987654321 hoje")

    assert "5511987654321" not in caplog.text
    assert "*********4321" in caplog.text


def test_campos_de_conteudo_sao_redigidos_inteiros(caplog) -> None:
    """`text_body` e `raw_payload` nunca aparecem, com ou sem digito."""
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", text_body="quero apto na zona sul")

    assert "zona sul" not in caplog.text
    assert "<redigido>" in caplog.text


def test_identificador_externo_e_mascarado_pela_chave(caplog) -> None:
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", sender_external_id="5511987654321")

    assert "5511987654321" not in caplog.text


def test_uuid_nao_e_confundido_com_telefone(caplog) -> None:
    """Um UUID tem 12 digitos seguidos no ultimo grupo.

    Sem a excecao, o mascaramento comeria o `message_id` de todo log de
    ingestao e a correlacao entre eventos morreria.
    """
    identificador = "550e8400-e29b-41d4-a716-446655440000"
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", message_id=identificador)

    assert identificador in caplog.text


def test_lista_de_identificadores_sobrevive(caplog) -> None:
    """`message.received` loga `message_ids` como lista."""
    identificadores = ["550e8400-e29b-41d4-a716-446655440000"]
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", message_ids=identificadores)

    assert identificadores[0] in caplog.text

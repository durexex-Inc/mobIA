import hashlib
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


def test_resumo_e_redigido_inteiro(caplog) -> None:
    """O resumo (TEC-127) destila as mesmas frases que `text_body` -- mesma protecao."""
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", resumo="lead procura apto de 2 quartos na zona sul")

    assert "zona sul" not in caplog.text
    assert "<redigido>" in caplog.text


def test_identificador_externo_e_mascarado_pela_chave(caplog) -> None:
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", sender_external_id="5511987654321")

    assert "5511987654321" not in caplog.text
    assert "*********4321" in caplog.text


def test_conversation_key_sem_digito_sai_mascarada(caplog) -> None:
    """O widget web do TEC-124 traz id de sessao, nao telefone.

    A corrida de digitos nao pega isso; so o mascaramento por chave pega. Sem
    ele a garantia seria um acidente do formato de telefone brasileiro.
    """
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", conversation_key="marina.souza@exemplo.com.br")

    assert "marina.souza" not in caplog.text
    assert "@exemplo" not in caplog.text


def test_pii_aninhada_nao_escapa(caplog) -> None:
    """Andar so no nivel de cima deixava passar tudo um nivel abaixo."""
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info(
            "evento.teste",
            contexto={
                "lead": {"telefone": "5511987654321"},
                "text_body": "quero apto na zona sul",
                "tentativas": ("5511987654321",),
            },
        )

    assert "5511987654321" not in caplog.text
    assert "zona sul" not in caplog.text
    assert "<redigido>" in caplog.text


def test_payload_sha256_sobrevive_verbatim(caplog) -> None:
    """Um sha256 tem corrida longa de digitos decimais em ~19% dos casos.

    `payload_sha256` e a unica alca de correlacao de um webhook rejeitado com a
    Meta; mascarado, ele deixa de casar com o payload original justamente no
    caso que alguem depura depois. Este digest -- sha256 de b"13" -- carrega
    quinze digitos seguidos.
    """
    digest = "3fdba35f04dc8c462986c992bcf875546257113072a909c162f7e470e581e278"
    assert hashlib.sha256(b"13").hexdigest() == digest

    log = structlog.get_logger("teste")
    with caplog.at_level(logging.INFO):
        log.info("evento.teste", payload_sha256=digest)

    assert digest in caplog.text


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


def test_telefone_no_traceback_tambem_sai_mascarado(caplog) -> None:
    """`log.exception` sem `format_exc_info` antes do mascarador vaza PII.

    O traceback so entra no dict como chave `exception` gracas ao
    `format_exc_info`; sem ele o texto da excecao nasce depois do
    `JSONRenderer` e o mascarador nunca chega a ve-lo.
    """
    log = structlog.get_logger("teste")
    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("contato do lead: 5511987654321")
        except ValueError:
            log.exception("evento.erro")

    assert "5511987654321" not in caplog.text
    assert "*********4321" in caplog.text
    assert "ValueError" in caplog.text

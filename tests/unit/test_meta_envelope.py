from typing import Any

from mobia.domain.messages.enums import MessageContentType, content_type_da_meta
from mobia.domain.messages.schemas import ParsedMessage, nome_no_envelope, parse_meta_envelope


def envelope(*messages: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "5511999998888",
                                "phone_number_id": "222222222",
                            },
                            "contacts": [{"wa_id": "5511911112222"}],
                            "messages": list(messages),
                        },
                    }
                ],
            }
        ],
    }


MENSAGEM_TEXTO = {
    "from": "5511911112222",
    "id": "wamid.TEXTO",
    "timestamp": "1755900000",
    "type": "text",
    "text": {"body": "Oi, procuro apartamento de 2 quartos"},
}


def test_extrai_mensagem_de_texto() -> None:
    resultado = parse_meta_envelope(envelope(MENSAGEM_TEXTO))
    assert len(resultado) == 1
    msg = resultado[0]
    assert isinstance(msg, ParsedMessage)
    assert msg.provider_message_id == "wamid.TEXTO"
    assert msg.sender_external_id == "5511911112222"
    assert msg.recipient_external_id == "222222222"
    assert msg.content_type is MessageContentType.TEXTO
    assert msg.text_body == "Oi, procuro apartamento de 2 quartos"
    assert msg.raw_payload == MENSAGEM_TEXTO


def test_audio_e_registrado_sem_corpo_de_texto() -> None:
    audio = {
        "from": "5511911112222",
        "id": "wamid.AUDIO",
        "type": "audio",
        "audio": {"id": "media-1", "mime_type": "audio/ogg"},
    }
    resultado = parse_meta_envelope(envelope(audio))
    assert len(resultado) == 1
    assert resultado[0].content_type is MessageContentType.AUDIO
    assert resultado[0].text_body is None


def test_varias_mensagens_no_mesmo_envelope() -> None:
    outra = dict(MENSAGEM_TEXTO, id="wamid.SEGUNDA")
    resultado = parse_meta_envelope(envelope(MENSAGEM_TEXTO, outra))
    assert [m.provider_message_id for m in resultado] == ["wamid.TEXTO", "wamid.SEGUNDA"]


def test_notificacao_de_status_nao_gera_mensagem() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "statuses": [{"id": "wamid.X", "status": "delivered"}],
                        },
                    }
                ],
            }
        ],
    }
    assert parse_meta_envelope(payload) == []


def test_payload_vazio_ou_desconhecido_nao_quebra() -> None:
    assert parse_meta_envelope({}) == []
    assert parse_meta_envelope({"entry": None}) == []
    assert parse_meta_envelope({"entry": [{"changes": None}]}) == []


def test_mensagem_sem_id_ou_remetente_e_ignorada() -> None:
    sem_id = {"from": "5511911112222", "type": "text", "text": {"body": "oi"}}
    sem_remetente = {"id": "wamid.SEM_FROM", "type": "text", "text": {"body": "oi"}}
    assert parse_meta_envelope(envelope(sem_id, sem_remetente)) == []


def test_tipo_ausente_vira_unknown() -> None:
    resultado = parse_meta_envelope(envelope({"from": "5511911112222", "id": "wamid.Z"}))
    assert resultado[0].content_type is MessageContentType.DESCONHECIDO


def envelope_com_tipo(tipo: str) -> dict:
    mensagem: dict = {"id": "wamid.TIPO", "from": "5511911112222", "type": tipo}
    if tipo == "text":
        mensagem["text"] = {"body": "oi"}
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [mensagem],
                        }
                    }
                ]
            }
        ]
    }


def test_mapeia_o_vocabulario_da_meta_para_o_dominio() -> None:
    """A coluna guarda o termo do dominio, nao o da Meta.

    TEC-124 traz o widget web, com vocabulario proprio. Se cada canal gravasse
    o seu, `messages` deixaria de ser um registro canonico legivel.
    """
    assert content_type_da_meta("text") is MessageContentType.TEXTO
    assert content_type_da_meta("audio") is MessageContentType.AUDIO
    assert content_type_da_meta("image") is MessageContentType.IMAGEM
    assert content_type_da_meta("document") is MessageContentType.DOCUMENTO


def test_tipo_ausente_ou_desconhecido_nao_derruba_o_parse() -> None:
    assert content_type_da_meta(None) is MessageContentType.DESCONHECIDO
    assert content_type_da_meta("sticker") is MessageContentType.DESCONHECIDO


def test_parser_devolve_o_tipo_do_dominio() -> None:
    (parsed,) = parse_meta_envelope(envelope_com_tipo("image"))
    assert parsed.content_type is MessageContentType.IMAGEM


# --- TEC-217: o envelope ------------------------------------------------------


def _com(value_extra: dict[str, Any], *messages: dict[str, Any]) -> dict[str, Any]:
    corpo = envelope(*messages)
    corpo["entry"][0]["changes"][0]["value"].update(value_extra)
    return corpo


def test_o_envelope_traz_a_conta_e_nao_as_mensagens() -> None:
    """D2: `entry_id` e `metadata` entram; `messages` fica so no raw de cada
    linha, e `statuses` -- da saida, com telefone de outros -- sai."""
    corpo = _com(
        {"statuses": [{"id": "wamid.SAIDA", "recipient_id": "5511900000000"}]},
        MENSAGEM_TEXTO,
    )

    (mensagem,) = parse_meta_envelope(corpo)

    contexto = mensagem.envelope_context
    assert contexto is not None
    assert contexto["entry_id"] == "111111111"
    assert contexto["value"]["metadata"]["display_phone_number"] == "5511999998888"
    assert "messages" not in contexto["value"]
    assert "statuses" not in contexto["value"]


def test_nome_do_perfil_sobrevive() -> None:
    corpo = _com(
        {"contacts": [{"wa_id": "5511911112222", "profile": {"name": "Marina Souza"}}]},
        MENSAGEM_TEXTO,
    )

    (mensagem,) = parse_meta_envelope(corpo)

    assert nome_no_envelope(mensagem.envelope_context) == "Marina Souza"


def test_cada_linha_so_leva_o_contato_do_proprio_remetente() -> None:
    """D2, a decisao de LGPD: sem o filtro, a linha de um lead guardaria o nome
    do outro, e a anonimizacao do outro nao a alcancaria."""
    outra = {**MENSAGEM_TEXTO, "from": "5511933334444", "id": "wamid.OUTRA"}
    corpo = _com(
        {
            "contacts": [
                {"wa_id": "5511911112222", "profile": {"name": "Marina"}},
                {"wa_id": "5511933334444", "profile": {"name": "Rafael"}},
            ]
        },
        MENSAGEM_TEXTO,
        outra,
    )

    primeira, segunda = parse_meta_envelope(corpo)

    assert primeira.envelope_context is not None
    assert segunda.envelope_context is not None
    assert primeira.envelope_context["value"]["contacts"] == [
        {"wa_id": "5511911112222", "profile": {"name": "Marina"}}
    ]
    assert nome_no_envelope(primeira.envelope_context) == "Marina"
    assert nome_no_envelope(segunda.envelope_context) == "Rafael"


def test_sem_contacts_o_nome_e_nulo() -> None:
    corpo = envelope(MENSAGEM_TEXTO)
    del corpo["entry"][0]["changes"][0]["value"]["contacts"]

    (mensagem,) = parse_meta_envelope(corpo)

    assert mensagem.envelope_context is not None
    assert "contacts" not in mensagem.envelope_context["value"]
    assert nome_no_envelope(mensagem.envelope_context) is None


def test_contato_sem_perfil_da_nome_nulo() -> None:
    # O `envelope()` padrao traz `contacts` so com `wa_id`.
    (mensagem,) = parse_meta_envelope(envelope(MENSAGEM_TEXTO))

    assert nome_no_envelope(mensagem.envelope_context) is None
    assert nome_no_envelope(None) is None


def test_campo_novo_de_value_sobrevive() -> None:
    """D2: tolerar formato novo da Meta e o argumento da coluna unica."""
    corpo = _com({"campo_que_a_meta_ainda_nao_manda": {"x": 1}}, MENSAGEM_TEXTO)

    (mensagem,) = parse_meta_envelope(corpo)

    assert mensagem.envelope_context is not None
    assert mensagem.envelope_context["value"]["campo_que_a_meta_ainda_nao_manda"] == {"x": 1}

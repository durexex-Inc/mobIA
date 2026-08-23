from typing import Any

from mobia.domain.messages.schemas import ParsedMessage, parse_meta_envelope


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
    assert msg.content_type == "text"
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
    assert resultado[0].content_type == "audio"
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
    assert resultado[0].content_type == "unknown"

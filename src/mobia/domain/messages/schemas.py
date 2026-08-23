from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedMessage:
    provider_message_id: str
    sender_external_id: str
    recipient_external_id: str
    content_type: str
    text_body: str | None
    raw_payload: dict[str, Any]


def parse_meta_envelope(payload: dict[str, Any]) -> list[ParsedMessage]:
    """Extrai as mensagens recebidas de um envelope de webhook da Meta.

    Tolera estrutura ausente ou desconhecida devolvendo lista vazia: notificacoes
    de status e payloads que nao contem `messages[]` nao viram linha.
    """
    parsed: list[ParsedMessage] = []

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            recipient = str(metadata.get("phone_number_id") or "")

            for message in value.get("messages") or []:
                provider_message_id = message.get("id")
                sender = message.get("from")
                if not provider_message_id or not sender:
                    continue

                content_type = message.get("type") or "unknown"
                text_body = None
                if content_type == "text":
                    text_body = (message.get("text") or {}).get("body")

                parsed.append(
                    ParsedMessage(
                        provider_message_id=str(provider_message_id),
                        sender_external_id=str(sender),
                        recipient_external_id=recipient,
                        content_type=str(content_type),
                        text_body=text_body,
                        raw_payload=message,
                    )
                )

    return parsed

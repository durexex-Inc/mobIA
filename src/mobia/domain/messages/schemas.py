from dataclasses import dataclass
from typing import Any

from mobia.domain.messages.enums import MessageContentType, content_type_da_meta


@dataclass(frozen=True)
class ParsedMessage:
    provider_message_id: str
    sender_external_id: str
    recipient_external_id: str
    content_type: MessageContentType
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

                content_type = content_type_da_meta(message.get("type"))
                text_body = None
                if content_type is MessageContentType.TEXTO:
                    text_body = (message.get("text") or {}).get("body")
                elif content_type in (MessageContentType.IMAGEM, MessageContentType.DOCUMENTO):
                    # TEC-132, D3. A legenda e o que o lead DISSE junto da
                    # midia -- "esse aqui ta disponivel?" -- e vira texto para
                    # passar por tudo o que texto passa: moderacao, opt-out,
                    # pedido de humano e turno. Legenda so de espacos e o mesmo
                    # que legenda nenhuma.
                    chave = "image" if content_type is MessageContentType.IMAGEM else "document"
                    legenda = ((message.get(chave) or {}).get("caption") or "").strip()
                    text_body = legenda or None

                parsed.append(
                    ParsedMessage(
                        provider_message_id=str(provider_message_id),
                        sender_external_id=str(sender),
                        recipient_external_id=recipient,
                        content_type=content_type,
                        text_body=text_body,
                        raw_payload=message,
                    )
                )

    return parsed

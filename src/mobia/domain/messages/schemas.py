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
    # TEC-217. O que o envelope da Meta diz sobre esta mensagem e que nao esta
    # nela -- ver `_contexto_do_envelope`. Nulo fora do WhatsApp.
    envelope_context: dict[str, Any] | None = None


# TEC-217, D2. Os arrays de `value` que descrevem OUTRAS mensagens: `messages`
# ja vai inteiro, um por linha, em `raw_payload`, e `statuses` e da saida e
# traz o telefone de outros destinatarios.
_ARRAYS_DE_OUTRAS_MENSAGENS = frozenset({"messages", "statuses"})


def _contexto_do_envelope(
    entry: dict[str, Any], value: dict[str, Any], remetente: str
) -> dict[str, Any]:
    """O `change.value` sem as outras mensagens, com o `entry.id`. TEC-217, D2.

    **`contacts` fica so com o do remetente desta linha.** Um envelope pode
    trazer mensagens de dois leads, e sem o filtro a linha de um guardaria o
    nome e o telefone do outro -- que a anonimizacao do outro (TEC-207) nao
    alcancaria, porque ela esvazia as linhas DELE.

    O resto de `value` passa como esta, inclusive campo que a Meta ainda nao
    manda: tolerar formato novo e o argumento da coluna unica contra colunas
    extraidas campo a campo.
    """
    contexto = {
        chave: valor for chave, valor in value.items() if chave not in _ARRAYS_DE_OUTRAS_MENSAGENS
    }
    if "contacts" in contexto:
        contexto["contacts"] = [
            contato
            for contato in contexto["contacts"] or []
            if isinstance(contato, dict) and str(contato.get("wa_id") or "") == remetente
        ]
    return {"entry_id": entry.get("id"), "value": contexto}


def nome_no_envelope(contexto: dict[str, Any] | None) -> str | None:
    """O nome do perfil do WhatsApp do lead, ou `None`. TEC-217, D3.

    `contacts` ja chega filtrado para o remetente da linha, entao o primeiro e
    o dele. Sem contato, sem perfil ou sem nome, `None` -- o terceiro cenario
    da card: envelope sem `contacts` nao e defeito.
    """
    if not contexto:
        return None
    contatos = (contexto.get("value") or {}).get("contacts") or []
    if not contatos:
        return None
    nome = ((contatos[0] or {}).get("profile") or {}).get("name")
    return nome if isinstance(nome, str) and nome else None


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
                        envelope_context=_contexto_do_envelope(entry, value, str(sender)),
                    )
                )

    return parsed

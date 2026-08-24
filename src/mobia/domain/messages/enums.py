from enum import StrEnum


class MessageRole(StrEnum):
    LEAD = "LEAD"
    AGENTE = "AGENTE"
    CORRETOR = "CORRETOR"
    SISTEMA = "SISTEMA"


class MessageDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageContentType(StrEnum):
    TEXTO = "TEXTO"
    AUDIO = "AUDIO"
    IMAGEM = "IMAGEM"
    DOCUMENTO = "DOCUMENTO"
    DESCONHECIDO = "DESCONHECIDO"


# O vocabulario cru da Meta fica confinado aqui. Cada canal novo (TEC-124 web,
# por exemplo) ganha o seu proprio mapeamento e a coluna continua canonica.
_DA_META = {
    "text": MessageContentType.TEXTO,
    "audio": MessageContentType.AUDIO,
    "image": MessageContentType.IMAGEM,
    "document": MessageContentType.DOCUMENTO,
}


def content_type_da_meta(valor: str | None) -> MessageContentType:
    if valor is None:
        return MessageContentType.DESCONHECIDO
    return _DA_META.get(valor, MessageContentType.DESCONHECIDO)

"""O que a midia recebida pode ser, e onde ela mora. TEC-132, D1 e D3.

A allowlist e curta de proposito: o que ela aceita e o que o lead manda para
um corretor de imoveis -- foto de anuncio, PDF de proposta, planilha. Um
executavel ou um zip nao tem por que ser guardado, e guardar o que nao se sabe
o que e so aumenta o que ha para vazar.
"""

import uuid

TIPOS_PERMITIDOS: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


def tipo_permitido(mime: str) -> bool:
    # A Meta pode mandar parametros depois do tipo ("image/jpeg; codecs=...").
    return mime.split(";", 1)[0].strip().lower() in TIPOS_PERMITIDOS


def chave_do_objeto(message_id: uuid.UUID) -> str:
    """So o id: a chave aparece em log e em listagem de bucket (D1)."""
    return f"midias/{message_id}"

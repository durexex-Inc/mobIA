import base64
import json
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mobia.app.config import get_settings

NONCE_BYTES = 12
CHAVE_BYTES = 32


class DecryptionError(Exception):
    """O conteudo nao autentica com esta chave e este AAD."""


def _cifra() -> AESGCM:
    chave = base64.b64decode(get_settings().content_encryption_key)
    if len(chave) != CHAVE_BYTES:
        raise ValueError(
            f"content_encryption_key deve ter {CHAVE_BYTES} bytes apos o base64, tem {len(chave)}"
        )
    return AESGCM(chave)


def aad_de(message_id: uuid.UUID | str, coluna: str) -> str:
    """Amarra o ciphertext a sua propria linha e coluna.

    Sem isso, quem tem UPDATE no banco mas nao a chave pode mover o conteudo de
    um lead para a linha de outro, ou de `text_body` para `raw_payload`, e a
    aplicacao decifra sem reclamar.
    """
    return f"{message_id}:{coluna}"


def encrypt(texto: str | None, aad: str) -> bytes | None:
    if texto is None:
        return None
    # Nonce novo a cada chamada: o mesmo texto cifra diferente toda vez, entao
    # busca por igualdade sobre conteudo deixa de existir. E intencional.
    nonce = os.urandom(NONCE_BYTES)
    return nonce + _cifra().encrypt(nonce, texto.encode(), aad.encode())


def decrypt(blob: bytes | None, aad: str) -> str | None:
    if blob is None:
        return None
    nonce, corpo = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    try:
        return _cifra().decrypt(nonce, corpo, aad.encode()).decode()
    except InvalidTag as exc:
        raise DecryptionError(aad) from exc


def encrypt_json(valor: dict[str, Any] | None, aad: str) -> bytes | None:
    if valor is None:
        return None
    return encrypt(json.dumps(valor, separators=(",", ":"), sort_keys=True), aad)


def decrypt_json(blob: bytes | None, aad: str) -> dict[str, Any] | None:
    texto = decrypt(blob, aad)
    if texto is None:
        return None
    resultado: dict[str, Any] = json.loads(texto)
    return resultado

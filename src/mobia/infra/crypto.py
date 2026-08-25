import base64
import hashlib
import json
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mobia.app.config import get_settings

NONCE_BYTES = 12
TAG_BYTES = 16
CHAVE_BYTES = 32

# Byte de versao a frente do blob. Rotacao de chave continua fora de escopo,
# mas o *formato* e a parte cara de mudar depois que existem linhas gravadas:
# sem ele nao ha como ter duas chaves validas ao mesmo tempo, e rotacionar
# viraria reescrita offline da tabela inteira com o servico parado. Tambem
# libera trocar de algoritmo. Nada foi implantado ainda, entao o custo hoje e
# um byte por linha.
VERSAO_ATUAL = 1

# version(1) || nonce(12) || ciphertext || tag(16). Um blob menor que isso nao
# tem nem cabecalho e tag, quanto mais conteudo.
_TAMANHO_MINIMO = 1 + NONCE_BYTES + TAG_BYTES


class DecryptionError(Exception):
    """O conteudo nao autentica com esta chave e este AAD."""


def _cifra() -> AESGCM:
    chave = base64.b64decode(get_settings().content_encryption_key)
    if len(chave) != CHAVE_BYTES:
        raise ValueError(
            f"content_encryption_key deve ter {CHAVE_BYTES} bytes apos o base64, tem {len(chave)}"
        )
    return AESGCM(chave)


def _marca_do_aad(aad: str) -> str:
    """Identifica o AAD no erro sem carregar o AAD.

    O texto da excecao vaza para o log via `str(exc)` de quem captura, e a
    mascara de PII do projeto so caminha por campos estruturados -- nunca por
    dentro de uma string de excecao. E a mesma razao do `hide_parameters=True`
    em `db.py`. Desde o TEC-127 nem todo AAD e um UUID: `aad_do_resumo` monta a
    identidade a partir de `(channel, conversation_key)`, e `conversation_key` e
    o telefone do lead. O hash curto mantem o valor de diagnostico -- duas
    falhas do mesmo AAD correlacionam -- sem carregar o identificador.
    """
    return hashlib.sha256(aad.encode()).hexdigest()[:12]


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
    return bytes([VERSAO_ATUAL]) + nonce + _cifra().encrypt(nonce, texto.encode(), aad.encode())


def decrypt(blob: bytes | None, aad: str) -> str | None:
    if blob is None:
        return None
    # Sem esta guarda um blob curto sai como ValueError cru do `cryptography`
    # ("Nonce must be between 8 and 128 bytes") e quem captura DecryptionError
    # nao pega. A mensagem nunca carrega o blob.
    if len(blob) < _TAMANHO_MINIMO:
        raise DecryptionError(
            f"blob de {len(blob)} bytes, minimo {_TAMANHO_MINIMO}: aad={_marca_do_aad(aad)}"
        )
    versao = blob[0]
    if versao != VERSAO_ATUAL:
        # Versao desconhecida nao e tentada: parsear com o layout errado
        # produziria InvalidTag e esconderia a causa real.
        raise DecryptionError(f"versao de cifra desconhecida {versao}: aad={_marca_do_aad(aad)}")
    nonce, corpo = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
    try:
        return _cifra().decrypt(nonce, corpo, aad.encode()).decode()
    except InvalidTag as exc:
        raise DecryptionError(f"conteudo nao autentica: aad={_marca_do_aad(aad)}") from exc


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

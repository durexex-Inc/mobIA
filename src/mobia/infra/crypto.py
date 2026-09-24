import base64
import hashlib
import hmac
import json
import os
import uuid
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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


def _chave_da_marca() -> bytes:
    """Subchave HMAC para `marca_do_aad`, derivada da chave de conteudo.

    HKDF com `info` proprio da dois efeitos: a subchave nao e a chave de
    cifragem (dominio separado, entao vazar uma marca nao diz nada sobre a
    outra) e nao entra segredo novo no `config.py` -- nada a provisionar,
    nada a rotacionar por fora.

    **Consequencia aceita:** trocada a `content_encryption_key`, as marcas
    mudam. Elas existem para correlacionar linhas de log dentro de uma janela
    de incidente, nao para identificar uma conversa ao longo de meses, entao
    perder a correlacao atraves de uma rotacao nao custa nada de diagnostico.
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=CHAVE_BYTES,
        salt=None,
        info=b"mobia/marca-do-aad/v1",
    ).derive(base64.b64decode(get_settings().content_encryption_key))


def marca_do_aad(aad: str) -> str:
    """Identifica o AAD no erro sem carregar o AAD.

    O texto da excecao vaza para o log via `str(exc)` de quem captura, e a
    mascara de PII do projeto so caminha por campos estruturados -- nunca por
    dentro de uma string de excecao. E a mesma razao do `hide_parameters=True`
    em `db.py`. Desde o TEC-127 nem todo AAD e um UUID: `aad_do_resumo` monta a
    identidade a partir de `(channel, conversation_key)`, e `conversation_key` e
    o telefone do lead. A marca curta mantem o valor de diagnostico -- duas
    falhas do mesmo AAD correlacionam -- sem carregar o identificador.

    **E HMAC, e nao hash simples, porque hash simples aqui nao pseudonimiza.**
    Ate a TEC-226 isto era `sha256(aad)` sem sal. Um telefone brasileiro tem
    formato conhecido e espaco de busca pequeno: quem pusesse as maos no log
    reconstruiria o numero por forca bruta em tempo trivial, que e o oposto do
    que esta funcao existe para fazer. Com chave, sem a chave nao ha o que
    forcar.
    """
    return hmac.new(_chave_da_marca(), aad.encode(), hashlib.sha256).hexdigest()[:12]


def aad_de(message_id: uuid.UUID | str, coluna: str) -> str:
    """Amarra o ciphertext a sua propria linha e coluna.

    Sem isso, quem tem UPDATE no banco mas nao a chave pode mover o conteudo de
    um lead para a linha de outro, ou de `text_body` para `raw_payload`, e a
    aplicacao decifra sem reclamar.
    """
    return f"{message_id}:{coluna}"


def encrypt_bytes(dados: bytes, aad: str) -> bytes:
    """A mesma cifra de `encrypt`, sobre bytes. TEC-132: o arquivo de midia."""
    # Nonce novo a cada chamada: o mesmo conteudo cifra diferente toda vez, entao
    # busca por igualdade sobre conteudo deixa de existir. E intencional.
    nonce = os.urandom(NONCE_BYTES)
    return bytes([VERSAO_ATUAL]) + nonce + _cifra().encrypt(nonce, dados, aad.encode())


def decrypt_bytes(blob: bytes, aad: str) -> bytes:
    """Inverso de `encrypt_bytes`, com as mesmas guardas de `decrypt`."""
    # Sem esta guarda um blob curto sai como ValueError cru do `cryptography`
    # ("Nonce must be between 8 and 128 bytes") e quem captura DecryptionError
    # nao pega. A mensagem nunca carrega o blob.
    if len(blob) < _TAMANHO_MINIMO:
        raise DecryptionError(
            f"blob de {len(blob)} bytes, minimo {_TAMANHO_MINIMO}: aad={marca_do_aad(aad)}"
        )
    versao = blob[0]
    if versao != VERSAO_ATUAL:
        # Versao desconhecida nao e tentada: parsear com o layout errado
        # produziria InvalidTag e esconderia a causa real.
        raise DecryptionError(f"versao de cifra desconhecida {versao}: aad={marca_do_aad(aad)}")
    nonce, corpo = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
    try:
        return _cifra().decrypt(nonce, corpo, aad.encode())
    except InvalidTag as exc:
        raise DecryptionError(f"conteudo nao autentica: aad={marca_do_aad(aad)}") from exc


def encrypt(texto: str | None, aad: str) -> bytes | None:
    if texto is None:
        return None
    return encrypt_bytes(texto.encode(), aad)


def decrypt(blob: bytes | None, aad: str) -> str | None:
    if blob is None:
        return None
    return decrypt_bytes(blob, aad).decode()


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

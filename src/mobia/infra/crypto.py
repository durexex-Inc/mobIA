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

# Byte de versao a frente do blob. v1 foi a unica ate a TEC-203 e continua
# decifrando para sempre, com a chave legada (`content_encryption_key`). v2
# carrega o id da chave do keyring logo depois da versao, e e ele que permite
# duas chaves validas ao mesmo tempo -- a razao de o byte existir desde a
# TEC-126. O id nao entra no AAD: ele ESCOLHE a chave, e adulterado escolhe
# outra, sob a qual a tag nao autentica.
VERSAO_LEGADA = 1
VERSAO_COM_ID = 2
ID_BYTES = 4

_TAMANHO_MINIMO_V1 = 1 + NONCE_BYTES + TAG_BYTES
_TAMANHO_MINIMO_V2 = 1 + ID_BYTES + NONCE_BYTES + TAG_BYTES


class DecryptionError(Exception):
    """O conteudo nao autentica com esta chave e este AAD."""


def _decodificar(chave_b64: str, nome: str) -> bytes:
    chave = base64.b64decode(chave_b64)
    if len(chave) != CHAVE_BYTES:
        raise ValueError(f"{nome} deve ter {CHAVE_BYTES} bytes apos o base64, tem {len(chave)}")
    return chave


def _chave_legada() -> bytes:
    return _decodificar(get_settings().content_encryption_key, "content_encryption_key")


def _chave_do_keyring(identificador: int) -> bytes | None:
    chave = get_settings().content_encryption_keys.get(f"{identificador:08d}")
    return None if chave is None else _decodificar(chave, f"a chave {identificador}")


def id_da_chave_ativa() -> int | None:
    """O id que cifra agora, ou `None` com o keyring vazio (grava v1)."""
    ativa = get_settings().content_encryption_key_ativa
    return int(ativa) if ativa else None


def id_da_chave(blob: bytes) -> int | None:
    """O id do keyring que cifrou o blob; `None` e v1, a chave legada.

    Existe para o `recifrar` saber o que ainda falta reescrever sem decifrar.
    """
    if blob[:1] == bytes([VERSAO_COM_ID]) and len(blob) >= _TAMANHO_MINIMO_V2:
        return int.from_bytes(blob[1 : 1 + ID_BYTES], "big")
    return None


def _chave_da_marca() -> bytes:
    """Subchave HMAC para `marca_do_aad`, derivada da chave de conteudo.

    HKDF com `info` proprio da dois efeitos: a subchave nao e a chave de
    cifragem (dominio separado, entao vazar uma marca nao diz nada sobre a
    outra) e nao entra segredo novo no `config.py` -- nada a provisionar,
    nada a rotacionar por fora.

    **Consequencia aceita:** trocada a `content_encryption_key` ou a chave
    ativa do keyring, as marcas mudam. Elas existem para correlacionar linhas
    de log dentro de uma janela de incidente, nao para identificar uma
    conversa ao longo de meses, entao perder a correlacao atraves de uma
    rotacao nao custa nada de diagnostico.
    """
    ativa = id_da_chave_ativa()
    base = _chave_legada() if ativa is None else _chave_do_keyring(ativa)
    assert base is not None  # `_validar_keyring` garante que a ativa esta no keyring
    return HKDF(
        algorithm=hashes.SHA256(), length=CHAVE_BYTES, salt=None, info=b"mobia/marca-do-aad/v1"
    ).derive(base)


def marca_do_aad(aad: str) -> str:
    """Identifica o AAD no erro sem carregar o AAD.

    O texto da excecao vaza para o log via `str(exc)` de quem captura, e a
    mascara de PII do projeto so caminha por campos estruturados -- nunca por
    dentro de uma string de excecao. E a mesma razao do `hide_parameters=True`
    em `db.py`. Desde o TEC-127 nem todo AAD e um UUID: `aad_do_resumo` monta a
    identidade a partir de `(channel, conversation_key)`, e `conversation_key`
    era o telefone do lead (desde a TEC-203 e o HMAC dele, que continua sendo
    pseudonimo estavel do lead). A marca curta mantem o valor de diagnostico --
    duas falhas do mesmo AAD correlacionam -- sem carregar o identificador.

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
    ativa = id_da_chave_ativa()
    if ativa is None:
        cifra_legada = AESGCM(_chave_legada())
        return bytes([VERSAO_LEGADA]) + nonce + cifra_legada.encrypt(nonce, dados, aad.encode())
    chave = _chave_do_keyring(ativa)
    assert chave is not None  # `_validar_keyring` garante que a ativa esta no keyring
    cabecalho = bytes([VERSAO_COM_ID]) + ativa.to_bytes(ID_BYTES, "big")
    return cabecalho + nonce + AESGCM(chave).encrypt(nonce, dados, aad.encode())


def decrypt_bytes(blob: bytes, aad: str) -> bytes:
    """Inverso de `encrypt_bytes`, com as mesmas guardas de `decrypt`."""
    # Sem as guardas de tamanho um blob curto sai como ValueError cru do
    # `cryptography` ("Nonce must be between 8 and 128 bytes") e quem captura
    # DecryptionError nao pega. A mensagem nunca carrega o blob nem o AAD.
    versao = blob[0] if blob else None
    if versao == VERSAO_LEGADA:
        if len(blob) < _TAMANHO_MINIMO_V1:
            raise DecryptionError(
                f"blob de {len(blob)} bytes, minimo {_TAMANHO_MINIMO_V1}: aad={marca_do_aad(aad)}"
            )
        chave, inicio = _chave_legada(), 1
    elif versao == VERSAO_COM_ID:
        if len(blob) < _TAMANHO_MINIMO_V2:
            raise DecryptionError(
                f"blob de {len(blob)} bytes, minimo {_TAMANHO_MINIMO_V2}: aad={marca_do_aad(aad)}"
            )
        identificador = int.from_bytes(blob[1 : 1 + ID_BYTES], "big")
        encontrada = _chave_do_keyring(identificador)
        if encontrada is None:
            raise DecryptionError(f"chave {identificador} fora do keyring: aad={marca_do_aad(aad)}")
        chave, inicio = encontrada, 1 + ID_BYTES
    else:
        # Versao desconhecida nao e tentada: parsear com o layout errado
        # produziria InvalidTag e esconderia a causa real.
        raise DecryptionError(f"versao de cifra desconhecida {versao}: aad={marca_do_aad(aad)}")
    nonce, corpo = blob[inicio : inicio + NONCE_BYTES], blob[inicio + NONCE_BYTES :]
    try:
        return AESGCM(chave).decrypt(nonce, corpo, aad.encode())
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

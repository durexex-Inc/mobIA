import pytest

from mobia.infra.crypto import (
    DecryptionError,
    aad_de,
    decrypt,
    decrypt_json,
    encrypt,
    encrypt_json,
)

AAD = aad_de("11111111-1111-1111-1111-111111111111", "text_body")


def test_roundtrip_de_texto() -> None:
    cifrado = encrypt("orcamento de 600 mil", AAD)
    assert cifrado is not None
    assert decrypt(cifrado, AAD) == "orcamento de 600 mil"


def test_none_atravessa_sem_cifrar() -> None:
    """A coluna e nullable e ausencia de conteudo nao e conteudo."""
    assert encrypt(None, AAD) is None
    assert decrypt(None, AAD) is None


def test_mesmo_texto_cifra_diferente_a_cada_chamada() -> None:
    """Nonce aleatorio por chamada: e o que impede inferir igualdade pelo ciphertext."""
    assert encrypt("oi", AAD) != encrypt("oi", AAD)


def test_ciphertext_movido_de_outra_linha_e_rejeitado() -> None:
    """O AAD amarra o ciphertext ao seu proprio (message_id, coluna).

    Sem isso, quem tem UPDATE no banco mas nao a chave move o conteudo da Marina
    para a linha de outro lead e a aplicacao decifra sem reclamar.
    """
    cifrado = encrypt("oi", AAD)
    assert cifrado is not None
    outra_linha = aad_de("22222222-2222-2222-2222-222222222222", "text_body")
    with pytest.raises(DecryptionError):
        decrypt(cifrado, outra_linha)


def test_ciphertext_movido_de_outra_coluna_e_rejeitado() -> None:
    cifrado = encrypt("oi", AAD)
    assert cifrado is not None
    outra_coluna = aad_de("11111111-1111-1111-1111-111111111111", "raw_payload")
    with pytest.raises(DecryptionError):
        decrypt(cifrado, outra_coluna)


def test_ciphertext_adulterado_e_rejeitado() -> None:
    cifrado = bytearray(encrypt("oi", AAD) or b"")
    cifrado[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        decrypt(bytes(cifrado), AAD)


def test_roundtrip_de_json() -> None:
    payload = {"id": "wamid.ABC", "type": "text", "text": {"body": "oi"}}
    cifrado = encrypt_json(payload, AAD)
    assert cifrado is not None
    assert decrypt_json(cifrado, AAD) == payload

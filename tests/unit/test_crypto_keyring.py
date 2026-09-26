"""TEC-203, D1: o keyring. v1 continua decifrando; v2 carrega o id da chave."""

import base64
import os

import pytest

from mobia.app.config import Settings
from mobia.infra import crypto
from mobia.infra.crypto import DecryptionError, decrypt_bytes, encrypt_bytes, id_da_chave


def _chave() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def keyring(monkeypatch):
    chaves = {"20260101": _chave(), "20260926": _chave()}

    def configurar(ativa: str | None, **extra: str) -> None:
        valores = {"content_encryption_keys": chaves, **extra}
        if ativa is not None:
            valores["content_encryption_key_ativa"] = ativa
        monkeypatch.setattr(crypto, "get_settings", lambda: Settings(**valores))

    return configurar


def test_sem_keyring_grava_v1_como_antes(monkeypatch):
    blob = encrypt_bytes(b"oi", "aad")
    assert blob[0] == crypto.VERSAO_LEGADA
    assert id_da_chave(blob) is None
    assert decrypt_bytes(blob, "aad") == b"oi"


def test_com_keyring_grava_v2_com_a_ativa(keyring):
    keyring("20260926")
    blob = encrypt_bytes(b"oi", "aad")
    assert blob[0] == crypto.VERSAO_COM_ID
    assert id_da_chave(blob) == 20260926
    assert decrypt_bytes(blob, "aad") == b"oi"


def test_blob_da_chave_anterior_continua_decifrando(keyring):
    keyring("20260101")
    antigo = encrypt_bytes(b"oi", "aad")
    keyring("20260926")
    assert decrypt_bytes(antigo, "aad") == b"oi"


def test_v1_decifra_com_keyring_configurado(keyring):
    legado = encrypt_bytes(b"oi", "aad")  # antes do keyring, com a chave legada
    keyring("20260926")
    assert decrypt_bytes(legado, "aad") == b"oi"


def test_id_fora_do_keyring_reprova_sem_ecoar_o_aad(keyring):
    keyring("20260926")
    blob = bytearray(encrypt_bytes(b"oi", "telefone-do-lead"))
    blob[1:5] = (20991231).to_bytes(4, "big")
    with pytest.raises(DecryptionError) as erro:
        decrypt_bytes(bytes(blob), "telefone-do-lead")
    assert "telefone-do-lead" not in str(erro.value)


def test_id_adulterado_para_outra_chave_do_keyring_nao_autentica(keyring):
    keyring("20260926")
    blob = bytearray(encrypt_bytes(b"oi", "aad"))
    blob[1:5] = (20260101).to_bytes(4, "big")
    with pytest.raises(DecryptionError):
        decrypt_bytes(bytes(blob), "aad")


def test_ativa_fora_do_keyring_reprova_na_construcao():
    with pytest.raises(ValueError, match="ativa"):
        Settings(
            content_encryption_keys={"20260926": _chave()},
            content_encryption_key_ativa="20260101",
        )


def test_id_que_nao_e_data_reprova():
    with pytest.raises(ValueError, match="AAAAMMDD"):
        Settings(
            content_encryption_keys={"chave1": _chave()},
            content_encryption_key_ativa="chave1",
        )


def test_chave_que_nao_tem_32_bytes_reprova():
    curta = base64.b64encode(os.urandom(16)).decode()
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(
            content_encryption_keys={"20260926": curta},
            content_encryption_key_ativa="20260926",
        )

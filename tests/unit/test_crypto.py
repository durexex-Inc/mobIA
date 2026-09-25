import base64
import hashlib
from unittest.mock import patch

import pytest

from mobia.app.config import get_settings
from mobia.infra.crypto import (
    CHAVE_BYTES,
    NONCE_BYTES,
    TAG_BYTES,
    VERSAO_ATUAL,
    DecryptionError,
    aad_de,
    decrypt,
    decrypt_bytes,
    decrypt_json,
    encrypt,
    encrypt_bytes,
    encrypt_json,
    marca_do_aad,
)

AAD = aad_de("11111111-1111-1111-1111-111111111111", "text_body")


def test_bytes_cifrados_voltam_iguais() -> None:
    dados = bytes(range(256)) * 10
    blob = encrypt_bytes(dados, "m-1:midia")
    assert blob != dados
    assert decrypt_bytes(blob, "m-1:midia") == dados


def test_bytes_com_aad_errado_nao_decifram() -> None:
    blob = encrypt_bytes(b"conteudo", "m-1:midia")
    with pytest.raises(DecryptionError):
        decrypt_bytes(blob, "m-2:midia")


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


def test_blob_carrega_o_byte_de_versao() -> None:
    """O formato e version(1) || nonce(12) || ciphertext || tag(16).

    O byte de versao nao serve a nada hoje -- rotacao de chave esta fora de
    escopo. Ele existe porque o formato e a parte cara de mudar depois que ha
    linhas gravadas, e ainda nao ha nenhuma.
    """
    cifrado = encrypt("oi", AAD)
    assert cifrado is not None
    assert cifrado[0] == VERSAO_ATUAL
    assert len(cifrado) == 1 + NONCE_BYTES + len(b"oi") + TAG_BYTES
    assert decrypt(cifrado, AAD) == "oi"


def test_versao_desconhecida_e_rejeitada() -> None:
    """Tentar parsear com o layout errado daria InvalidTag e esconderia a causa."""
    cifrado = bytearray(encrypt("oi", AAD) or b"")
    cifrado[0] = 0x02
    with pytest.raises(DecryptionError):
        decrypt(bytes(cifrado), AAD)


@pytest.mark.parametrize("blob", [b"", b"12345", b"\x01" * 28])
def test_blob_curto_levanta_o_erro_documentado(blob: bytes) -> None:
    """Antes saia ValueError cru do `cryptography` e quem capturava
    DecryptionError nao pegava."""
    with pytest.raises(DecryptionError):
        decrypt(blob, AAD)


def test_erro_de_blob_curto_nao_carrega_o_conteudo() -> None:
    with pytest.raises(DecryptionError) as erro:
        decrypt(b"conteudo-secreto", AAD)
    assert "conteudo-secreto" not in str(erro.value)


def test_erro_de_autenticacao_nao_carrega_o_aad() -> None:
    """O AAD do resumo (TEC-127) carrega o telefone do lead; o erro nao pode.

    `aad_do_resumo` monta a identidade a partir de `(channel,
    conversation_key)` -- e `conversation_key` e o numero do lead. A mascara de
    PII do log so caminha por campos estruturados, nunca por dentro do texto de
    uma excecao, entao um `str(exc)` no consumidor colocaria o telefone no log.
    """
    cifrado = encrypt("oi", AAD)
    assert cifrado is not None
    aad_com_telefone = "4:whatsapp:13:5511911112222:resumo"

    with pytest.raises(DecryptionError) as erro:
        decrypt(cifrado, aad_com_telefone)

    assert "5511911112222" not in str(erro.value)
    assert aad_com_telefone not in str(erro.value)


def test_marca_do_aad_e_estavel_e_distingue_aads() -> None:
    """O diagnostico continua servindo: duas falhas do mesmo AAD correlacionam."""
    assert marca_do_aad("a:b") == marca_do_aad("a:b")
    assert marca_do_aad("a:b") != marca_do_aad("a:c")


def test_marca_do_aad_nao_e_forcavel_por_quem_so_tem_o_log() -> None:
    """TEC-226: a marca e HMAC com chave, nao hash simples.

    Ate a TEC-226 isto era `sha256(aad)` sem sal. Um telefone brasileiro tem
    formato conhecido e espaco de busca pequeno, entao quem tivesse o log
    reconstruiria o numero tentando os candidatos -- que e exatamente o que
    esta funcao existe para impedir. O teste faz a forca bruta do atacante com
    UM candidato: se a marca fosse hash sem chave, ele acertaria.
    """
    aad = "4:whatsapp:13:5511911112222:resumo"
    assert marca_do_aad(aad) != hashlib.sha256(aad.encode()).hexdigest()[:12]


def test_marca_do_aad_muda_com_a_chave() -> None:
    """O que prova que a marca e chaveada: trocada a chave, ela muda.

    E a consequencia aceita que o docstring de `_chave_da_marca` registra --
    marcas nao correlacionam atraves de uma rotacao de chave. O teste existe
    para que isso seja uma decisao visivel, e nao uma surpresa em incidente.
    """
    aad = "4:whatsapp:13:5511911112222:resumo"
    antes = marca_do_aad(aad)

    outra_chave = base64.b64encode(b"\x01" * CHAVE_BYTES).decode()
    with patch.object(get_settings(), "content_encryption_key", outra_chave):
        depois = marca_do_aad(aad)

    assert antes != depois


def test_erro_de_versao_desconhecida_nao_carrega_o_aad() -> None:
    cifrado = bytearray(encrypt("oi", AAD) or b"")
    cifrado[0] = 0x02
    aad_com_telefone = "4:whatsapp:13:5511911112222:resumo"

    with pytest.raises(DecryptionError) as erro:
        decrypt(bytes(cifrado), aad_com_telefone)

    assert "5511911112222" not in str(erro.value)


def test_erro_de_blob_curto_nao_carrega_o_aad() -> None:
    aad_com_telefone = "4:whatsapp:13:5511911112222:resumo"

    with pytest.raises(DecryptionError) as erro:
        decrypt(b"12345", aad_com_telefone)

    assert "5511911112222" not in str(erro.value)

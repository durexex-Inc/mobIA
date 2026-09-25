"""O segundo fator do ADMIN. TEC-201, D5.

A semente e o unico segredo desta card que precisa voltar em claro -- conferir
um codigo exige recalcula-lo --, entao ela e CIFRADA e nao hasheada, com o
`infra/crypto.py` e AAD amarrado ao id do usuario. Ver a D3 do desenho, que diz
por que isso e uma exposicao real e nao um detalhe.
"""

import uuid

import pyotp

from mobia.domain.usuarios.models import aad_do_totp
from mobia.infra.crypto import decrypt, encrypt

# Quantas janelas de 30s para tras e para frente sao aceitas.
#
# **Uma, e nao zero.** Zero exigiria que o relogio do telefone e o do servidor
# estivessem alinhados ao segundo, e o sintoma de um desvio de poucos segundos
# seria "o codigo certo nao funciona" -- que e indistinguivel, para quem tenta
# entrar, de ter digitado errado. Uma janela custa 30s a mais de validade a um
# codigo roubado e evita a classe inteira desses chamados.
#
# **Nao suba isto sem medir o que se ganha.** Cada janela a mais e tempo em que
# um codigo interceptado continua valendo.
JANELA = 1


def gerar_semente() -> str:
    """Uma semente nova, em base32 -- o formato que os aplicativos leem."""
    return pyotp.random_base32()


def cifrar_semente(semente: str, usuario_id: uuid.UUID) -> bytes:
    """A semente pronta para `usuarios.totp_segredo`.

    O AAD amarra o texto cifrado AO USUARIO: mover a coluna de uma linha para
    outra torna o valor indecifravel, em vez de dar a um usuario o segundo
    fator de outro.
    """
    cifrada = encrypt(semente, aad_do_totp(usuario_id))
    # `encrypt` devolve None para entrada None; aqui a entrada nunca e None, e
    # o `assert` documenta isso para o mypy sem inventar tratamento para um
    # caso que nao existe.
    assert cifrada is not None
    return cifrada


def confere_codigo(segredo_cifrado: bytes | None, usuario_id: uuid.UUID, codigo: str) -> bool:
    """Se o codigo confere com a semente guardada.

    **Semente ausente devolve False, e nao levanta.** Um usuario marcado com
    `mfa_habilitado` e sem semente e estado inconsistente -- que o desfecho
    seja "nao entra" e mais seguro que um 500, e mais honesto que deixar
    passar.

    `DecryptionError` **propaga**, ao contrario do que `carregar_estado` do CRM
    faz com o resumo. La, degradar preserva o que importa (a exportacao
    continua sem o texto); aqui, degradar para False seria transformar rotacao
    de chave em "o segundo fator de todo mundo parou", sem distinguir isso de
    codigo errado. Quem investiga precisa ver a excecao.
    """
    if segredo_cifrado is None:
        return False
    semente = decrypt(segredo_cifrado, aad_do_totp(usuario_id))
    if semente is None:
        return False
    return bool(pyotp.TOTP(semente).verify(codigo, valid_window=JANELA))

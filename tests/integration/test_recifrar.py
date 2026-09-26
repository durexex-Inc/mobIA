"""TEC-203, D1: `recifrar` reescreve com a chave ativa o que estava sob outra."""

import base64
import os
import uuid

import pytest
from sqlalchemy import select

from mobia.admin.recifrar import recifrar
from mobia.app.config import get_settings
from mobia.domain.identidade.indice import registrar
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, decrypt_bytes, encrypt_bytes, id_da_chave
from mobia.infra.db import get_sessionmaker

CHAVE_A = "20260101"
CHAVE_B = "20260926"


def _chave_de_32_bytes() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def keyring(monkeypatch: pytest.MonkeyPatch):
    """Muda o keyring da chave de conteudo, mutando o `Settings` cached.

    Mesmo padrao de `tests/integration/test_baixar_midia.py::configuracao`:
    `monkeypatch.setattr` no proprio objeto de settings, e nao substituindo
    `get_settings`, porque `mobia.infra.db` depende do mesmo cache para achar
    o banco -- so os dois campos do keyring precisam mudar por teste.
    """
    settings = get_settings()
    valor_a, valor_b = _chave_de_32_bytes(), _chave_de_32_bytes()

    def configurar(chaves: dict[str, str], ativa: str) -> None:
        monkeypatch.setattr(settings, "content_encryption_keys", chaves)
        monkeypatch.setattr(settings, "content_encryption_key_ativa", ativa)

    configurar.valor_a = valor_a  # type: ignore[attr-defined]
    configurar.valor_b = valor_b  # type: ignore[attr-defined]
    return configurar


async def test_recifrar_reescreve_com_a_chave_ativa(keyring, banco_limpo: None) -> None:
    valor_a, valor_b = keyring.valor_a, keyring.valor_b  # type: ignore[attr-defined]

    # 1. Grava uma mensagem sob a chave A, unica no keyring e ativa.
    keyring({CHAVE_A: valor_a}, CHAVE_A)
    texto = "quero um apartamento de 2 quartos"
    message_id = uuid.uuid4()
    async with get_sessionmaker()() as sessao:
        sessao.add(
            Message(
                id=message_id,
                channel="whatsapp",
                conversation_key="5511911112222",
                sender_external_id="5511911112222",
                role=MessageRole.LEAD,
                direction=MessageDirection.INBOUND,
                content_type=MessageContentType.TEXTO,
                status=MessageStatus.PROCESSED,
                text_body=encrypt_bytes(texto.encode(), aad_de(message_id, "text_body")),
            )
        )
        await sessao.commit()

    # 2. B entra no keyring e vira a ativa -- A continua valido para decifrar.
    keyring({CHAVE_A: valor_a, CHAVE_B: valor_b}, CHAVE_B)

    # 3. Roda a recifra: o blob antigo, sob A, tem de virar B.
    await recifrar(get_sessionmaker())

    async with get_sessionmaker()() as sessao:
        linha = (await sessao.execute(select(Message).where(Message.id == message_id))).scalar_one()
        blob = bytes(linha.text_body)

    assert id_da_chave(blob) == int(CHAVE_B)
    assert decrypt_bytes(blob, aad_de(message_id, "text_body")).decode() == texto

    # 4. Com A fora do keyring, so B, o blob recifrado continua decifravel.
    keyring({CHAVE_B: valor_b}, CHAVE_B)
    assert decrypt_bytes(blob, aad_de(message_id, "text_body")).decode() == texto


async def test_so_contar_numa_tabela_de_pk_composta_antes_e_depois(
    keyring, banco_limpo: None
) -> None:
    """`identidades_de_lead` tem PK `(channel, conversation_key)`, e nao um
    id so -- prova que a paginacao por tupla de chave primaria funciona e que
    `so_contar` conta pelo id REAL de cada blob, nao pela ativa do momento.

    E a mesma leitura que `scripts/recifrar.py` roda depois de escrever, para
    provar que nao sobrou nada fora da chave ativa -- em vez de confiar no
    relatorio da propria escrita, que da zero por construcao (ver a
    docstring do script).
    """
    valor_a, valor_b = keyring.valor_a, keyring.valor_b  # type: ignore[attr-defined]

    # 1. Grava uma identidade sob a chave A, unica no keyring e ativa.
    keyring({CHAVE_A: valor_a}, CHAVE_A)
    async with get_sessionmaker()() as sessao:
        await registrar(sessao, "whatsapp", "5511900000000")
        await sessao.commit()

    # 2. B entra no keyring e vira a ativa -- ainda SEM recifrar nada.
    keyring({CHAVE_A: valor_a, CHAVE_B: valor_b}, CHAVE_B)

    antes = await recifrar(get_sessionmaker(), so_contar=True)
    por_chave_antes = antes["identidades_de_lead.valor_cifrado"]
    assert por_chave_antes.get(int(CHAVE_A)) == 1
    assert por_chave_antes.get(int(CHAVE_B), 0) == 0

    # 3. Recifra de fato, e so ENTAO confere de novo, com uma leitura nova --
    # nao com o retorno da escrita, que sempre mostraria tudo sob a ativa.
    await recifrar(get_sessionmaker())
    depois = await recifrar(get_sessionmaker(), so_contar=True)
    por_chave_depois = depois["identidades_de_lead.valor_cifrado"]
    assert por_chave_depois.get(int(CHAVE_A), 0) == 0
    assert por_chave_depois.get(int(CHAVE_B)) == 1

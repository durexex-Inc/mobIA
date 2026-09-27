"""O wamid nao expoe o telefone do lead. TEC-383.

O wamid da Meta e base64 de um protobuf que carrega o `wa_id` legivel. Estes
testes montam um wamid com essa forma -- o telefone dentro, em bytes -- e
afirmam que nada dele sobra em claro em `messages`, nem depois da ingestao
nem depois da migration, e que a descida o devolve a partir do raw cifrado.
"""

import base64
import subprocess
import sys
import uuid
from typing import Any

from sqlalchemy import text

from mobia.domain.identidade.indice import chave_de_mensagem
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt_json
from mobia.infra.db import dispose_engine, get_sessionmaker

TELEFONE = "5548999887766"
# O comeco do wamid real (`HBgN...`) e exatamente isto: dois bytes de
# cabecalho do protobuf, o tamanho, e o `wa_id` em ASCII.
CORPO_DO_WAMID = base64.b64encode(bytes([0x1C, 0x18, 0x0D]) + TELEFONE.encode()).decode()
WAMID = f"wamid.{CORPO_DO_WAMID}"


def alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], check=True, capture_output=True)


def _webhook() -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "222222222"},
                            "contacts": [{"wa_id": TELEFONE}],
                            "messages": [
                                {
                                    "from": TELEFONE,
                                    "id": WAMID,
                                    "timestamp": "1755900000",
                                    "type": "text",
                                    "text": {"body": "oi"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


async def _linha_em_texto(session, message_id: uuid.UUID) -> str:
    """A linha inteira como texto: `bytea` sai em hex, o resto como esta."""
    return (
        await session.execute(
            text("SELECT row_to_json(m)::text FROM messages m WHERE id = :id"), {"id": message_id}
        )
    ).scalar_one()


async def test_mensagem_do_whatsapp_e_gravada_sem_o_telefone(session, redis_pool) -> None:
    """Cenario 1 da card: nem cru nem em base64."""
    assert TELEFONE in base64.b64decode(CORPO_DO_WAMID).decode("latin-1")

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest(
        parse_meta_envelope(_webhook())
    )

    linha = await _linha_em_texto(session, message_id)
    assert TELEFONE not in linha
    assert CORPO_DO_WAMID[:12] not in linha
    assert "wamid" not in linha


async def test_reentrega_do_mesmo_wamid_e_descartada(session, redis_pool) -> None:
    """Cenario 2 da card, sobre o wamid com o telefone dentro."""
    servico = IngestionService(get_sessionmaker(), redis_pool)

    primeira = await servico.ingest(parse_meta_envelope(_webhook()))
    reentrega = await servico.ingest(parse_meta_envelope(_webhook()))

    assert len(primeira) == 1
    assert reentrega == []


def _linha_antiga(identificador: uuid.UUID, provider_message_id: str, raw: dict | None) -> Message:
    return Message(
        id=identificador,
        channel="whatsapp",
        provider_message_id=provider_message_id,
        sender_external_id="chave-do-lead",
        recipient_external_id="222222222",
        conversation_key="chave-do-lead",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        raw_payload=None
        if raw is None
        else encrypt_json(raw, aad_de(identificador, "raw_payload")),
        status=MessageStatus.PROCESSED,
    )


async def _provider_ids() -> dict[uuid.UUID, str]:
    async with get_sessionmaker()() as sessao:
        linhas = await sessao.execute(text("SELECT id, provider_message_id FROM messages"))
        return {linha.id: linha.provider_message_id for linha in linhas}


async def test_a_0066_troca_o_wamid_antigo_e_a_descida_o_devolve(banco_limpo) -> None:
    """Cenario 4 da card, e a volta.

    Tres linhas: uma gravada antes da card (wamid cru, raw com o wamid), uma
    anonimizada (TEC-207) e uma cujo raw a retencao ja esvaziou. So a primeira
    muda na subida, e so ela volta na descida -- as outras duas nao tem de
    onde tirar um wamid, e o que guardam ja cumpre a UNIQUE.
    """
    antiga, anonimizada, sem_raw = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    hmac_sem_raw = chave_de_mensagem("whatsapp", "wamid.RETIDO")
    async with get_sessionmaker()() as sessao:
        sessao.add_all(
            [
                _linha_antiga(antiga, WAMID, {"id": WAMID}),
                _linha_antiga(anonimizada, f"anon:{anonimizada}", None),
                _linha_antiga(sem_raw, hmac_sem_raw, None),
            ]
        )
        await sessao.commit()

    await dispose_engine()
    try:
        alembic("downgrade", "0065")
        alembic("upgrade", "head")
    finally:
        await dispose_engine()

    subida = await _provider_ids()
    assert subida[antiga] == chave_de_mensagem("whatsapp", WAMID)
    assert subida[anonimizada] == f"anon:{anonimizada}"
    assert subida[sem_raw] == hmac_sem_raw

    try:
        alembic("downgrade", "0065")
        descida = await _provider_ids()
    finally:
        await dispose_engine()
        alembic("upgrade", "head")
        await dispose_engine()

    assert descida[antiga] == WAMID
    assert descida[anonimizada] == f"anon:{anonimizada}"
    assert descida[sem_raw] == hmac_sem_raw

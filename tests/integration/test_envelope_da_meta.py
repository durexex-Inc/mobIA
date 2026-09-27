"""O envelope da Meta sobrevive a ingestao, cifrado. TEC-217.

Os tres cenarios da card, do parser ao banco: o que o `parse_meta_envelope`
monta e gravado em `messages.envelope_context` com o AAD da propria linha, e
decifrado de volta.
"""

from typing import Any

from sqlalchemy import text as sql

from mobia.domain.messages.schemas import nome_no_envelope, parse_meta_envelope
from mobia.domain.messages.service import IngestionService
from mobia.infra.crypto import aad_de, decrypt_json
from mobia.infra.db import get_sessionmaker

LEAD = "5511911112222"


def _mensagem(wamid: str, texto: str) -> dict[str, Any]:
    return {
        "from": LEAD,
        "id": wamid,
        "timestamp": "1755900000",
        "type": "text",
        "text": {"body": texto},
    }


def _webhook(*mensagens: dict[str, Any], contacts: list[dict[str, Any]] | None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "5511999998888", "phone_number_id": "222222222"},
        "messages": list(mensagens),
    }
    if contacts is not None:
        value["contacts"] = contacts
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "111111111", "changes": [{"field": "messages", "value": value}]}],
    }


async def _envelope_gravado(session, message_id) -> dict[str, Any] | None:
    cru = (
        await session.execute(
            sql("SELECT envelope_context FROM messages WHERE id = :id"), {"id": message_id}
        )
    ).scalar_one()
    if cru is None:
        return None
    return decrypt_json(bytes(cru), aad_de(message_id, "envelope_context"))


async def test_nome_do_lead_sobrevive_a_ingestao(session, redis_pool) -> None:
    """Cenario 1 da card."""
    webhook = _webhook(
        _mensagem("wamid.NOME", "oi"),
        contacts=[{"wa_id": LEAD, "profile": {"name": "Marina Souza"}}],
    )

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest(
        parse_meta_envelope(webhook)
    )

    cru = (
        await session.execute(
            sql("SELECT envelope_context FROM messages WHERE id = :id"), {"id": message_id}
        )
    ).scalar_one()
    # Cifrado em repouso: o nome nao aparece num SELECT cru (TEC-221).
    assert b"Marina" not in bytes(cru)
    assert nome_no_envelope(await _envelope_gravado(session, message_id)) == "Marina Souza"


async def test_lote_nao_perde_contexto_nem_carrega_as_irmas(session, redis_pool) -> None:
    """Cenario 2 da card: tres mensagens do mesmo lead num envelope so."""
    textos = ["procuro apartamento", "de 2 quartos", "no Campeche"]
    webhook = _webhook(
        *(_mensagem(f"wamid.LOTE{i}", texto) for i, texto in enumerate(textos)),
        contacts=[{"wa_id": LEAD, "profile": {"name": "Marina"}}],
    )

    ids = await IngestionService(get_sessionmaker(), redis_pool).ingest(
        parse_meta_envelope(webhook)
    )

    assert len(ids) == 3
    for message_id in ids:
        envelope = await _envelope_gravado(session, message_id)
        assert envelope is not None
        assert envelope["entry_id"] == "111111111"
        assert envelope["value"]["metadata"]["display_phone_number"] == "5511999998888"
        serializado = str(envelope)
        assert not any(texto in serializado for texto in textos)


async def test_envelope_sem_contacts_nao_quebra_a_ingestao(session, redis_pool) -> None:
    """Cenario 3 da card."""
    webhook = _webhook(_mensagem("wamid.SEMCONTATO", "oi"), contacts=None)

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest(
        parse_meta_envelope(webhook)
    )

    envelope = await _envelope_gravado(session, message_id)
    assert envelope is not None
    assert nome_no_envelope(envelope) is None

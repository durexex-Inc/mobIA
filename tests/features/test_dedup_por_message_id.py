"""Cenarios Gherkin de TEC-125.

Funcionalidade: Idempotencia na recepcao de mensagens
"""

import asyncio
import json

from sqlalchemy import func, select

from mobia.domain.messages.models import Message
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature


def envelope(*wamids: str, texto: str = "ainda tem o 2 quartos?") -> dict:
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
                            "messages": [
                                {
                                    "from": "5511911112222",
                                    "id": wamid,
                                    "timestamp": "1755900000",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                                for wamid in wamids
                            ],
                        },
                    }
                ],
            }
        ],
    }


def assinado(payload: dict, secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    return body, {
        SIGNATURE_HEADER: compute_signature(secret, body),
        "Content-Type": "application/json",
    }


def eventos_de_log(caplog, evento: str) -> list[dict]:
    """Decodifica os registros JSON do structlog que carregam `evento`."""
    encontrados = []
    for registro in caplog.records:
        try:
            dados = json.loads(registro.getMessage())
        except (json.JSONDecodeError, TypeError):
            continue
        if dados.get("event") == evento:
            encontrados.append(dados)
    return encontrados


async def test_mesma_mensagem_entregue_duas_vezes(client, session, redis_pool, settings, caplog):
    """Cenario: Mesma mensagem entregue duas vezes."""
    body, headers = assinado(envelope("wamid.ABC123"), settings.whatsapp_app_secret)

    primeira = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert primeira.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 1
    assert len(await redis_pool.queued_jobs()) == 1

    with caplog.at_level("INFO"):
        segunda = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert segunda.status_code == 200, "a reentrega tambem tem de ser confirmada a Meta"
    assert await session.scalar(select(func.count()).select_from(Message)) == 1
    assert len(await redis_pool.queued_jobs()) == 1, "a duplicata nao gera novo processamento"

    descartes = eventos_de_log(caplog, "message.duplicate_discarded")
    assert len(descartes) == 1
    assert descartes[0]["provider_message_id"] == "wamid.ABC123"
    assert descartes[0]["channel"] == "whatsapp"


async def test_reentrega_concorrente_em_replicas_diferentes(client, session, redis_pool, settings):
    """Cenario: Reentrega concorrente em replicas diferentes.

    Duas requisicoes identicas em voo ao mesmo tempo contra o Postgres real. So
    o `ON CONFLICT` no banco resolve isso -- checagem em memoria perderia a corrida.
    """
    body, headers = assinado(envelope("wamid.CONCORRENTE"), settings.whatsapp_app_secret)

    respostas = await asyncio.gather(
        client.post("/webhooks/whatsapp", content=body, headers=headers),
        client.post("/webhooks/whatsapp", content=body, headers=headers),
    )

    assert [r.status_code for r in respostas] == [200, 200]
    assert await session.scalar(select(func.count()).select_from(Message)) == 1
    assert len(await redis_pool.queued_jobs()) == 1


async def test_mensagens_distintas_do_mesmo_lead_nao_se_confundem(
    client, session, redis_pool, settings
):
    """Cenario: Mensagens distintas do mesmo lead nao sao confundidas."""
    for wamid, texto in (("wamid.PRIMEIRA", "oi"), ("wamid.SEGUNDA", "tem garagem?")):
        body, headers = assinado(envelope(wamid, texto=texto), settings.whatsapp_app_secret)
        resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
        assert resposta.status_code == 200

    linhas = (await session.scalars(select(Message))).all()
    assert {linha.provider_message_id for linha in linhas} == {
        "wamid.PRIMEIRA",
        "wamid.SEGUNDA",
    }
    assert len(await redis_pool.queued_jobs()) == 2


async def test_duplicata_dentro_do_mesmo_envelope(client, session, redis_pool, settings, caplog):
    """A Meta pode repetir o mesmo wamid dentro de um unico envelope.

    O descarte tem de ser contabilizado tambem aqui: contar por conjunto em vez
    de por ocorrencia faria a segunda copia sumir sem log.
    """
    body, headers = assinado(
        envelope("wamid.REPETIDA", "wamid.REPETIDA", "wamid.OUTRA"),
        settings.whatsapp_app_secret,
    )

    with caplog.at_level("INFO"):
        resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert resposta.status_code == 200
    linhas = (await session.scalars(select(Message))).all()
    assert {linha.provider_message_id for linha in linhas} == {
        "wamid.REPETIDA",
        "wamid.OUTRA",
    }
    assert len(await redis_pool.queued_jobs()) == 2

    descartes = eventos_de_log(caplog, "message.duplicate_discarded")
    assert [d["provider_message_id"] for d in descartes] == ["wamid.REPETIDA"]


async def test_lote_com_duplicata_nao_derruba_as_mensagens_legitimas(
    client, session, redis_pool, settings
):
    """Uma duplicata no meio do lote nao pode abortar as mensagens novas."""
    primeiro, headers = assinado(envelope("wamid.JA_VISTA"), settings.whatsapp_app_secret)
    await client.post("/webhooks/whatsapp", content=primeiro, headers=headers)

    segundo, headers = assinado(
        envelope("wamid.JA_VISTA", "wamid.NOVA"), settings.whatsapp_app_secret
    )
    resposta = await client.post("/webhooks/whatsapp", content=segundo, headers=headers)

    assert resposta.status_code == 200
    linhas = (await session.scalars(select(Message))).all()
    assert {linha.provider_message_id for linha in linhas} == {
        "wamid.JA_VISTA",
        "wamid.NOVA",
    }
    assert len(await redis_pool.queued_jobs()) == 2, "so a mensagem nova entra na fila"

"""Cenarios Gherkin de TEC-380.

Funcionalidade: Redacao de dado sensivel

A mensagem entra pela rota do webhook de verdade, e o que se afirma e o que
ficou gravado -- `text_body` e `raw_payload`, decifrados. Nenhum dos dois pode
ter o dado.
"""

import json
from typing import Any

from conftest import pmid_do_whatsapp
from sqlalchemy import select

from mobia.domain.messages.models import Message
from mobia.domain.privacidade.redacao import MARCADOR_DE_DADO_SENSIVEL
from mobia.infra.crypto import aad_de, decrypt, decrypt_json
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature


def _envelope_de_texto(provider_message_id: str, texto: str) -> dict[str, Any]:
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
                                    "from": "5511944445555",
                                    "id": provider_message_id,
                                    "timestamp": "1758700000",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


async def _receber_e_ler(client, session, settings, provider_message_id: str, texto: str):
    body = json.dumps(_envelope_de_texto(provider_message_id, texto)).encode("utf-8")
    headers = {
        SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body),
        "Content-Type": "application/json",
    }
    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200
    procurado = pmid_do_whatsapp(provider_message_id)
    linha = (
        await session.execute(select(Message).where(Message.provider_message_id == procurado))
    ).scalar_one()
    return (
        decrypt(linha.text_body, aad_de(linha.id, "text_body")),
        decrypt_json(linha.raw_payload, aad_de(linha.id, "raw_payload")),
    )


async def test_dado_sensivel_informado_espontaneamente_e_redigido(
    client, session, settings
) -> None:
    """Cenario: Dado sensivel informado espontaneamente e redigido.

    Dado um lead que menciona uma condicao de saude na conversa, quando a
    mensagem e persistida, o trecho sensivel e redigido antes da gravacao -- e
    so o trecho: o pedido de imovel que veio junto fica.
    """
    texto = "Oi! Faço quimioterapia, então preciso de algo perto do hospital, 2 quartos"

    corpo, envelope = await _receber_e_ler(client, session, settings, "wamid.SAUDE1", texto)

    esperado = (
        f"Oi! Faço {MARCADOR_DE_DADO_SENSIVEL}, então preciso de algo perto do hospital, 2 quartos"
    )
    assert corpo == esperado
    assert envelope is not None
    assert envelope["text"]["body"] == esperado
    # O dado nao sobrevive em lugar nenhum do que foi gravado.
    assert "quimioterapia" not in json.dumps(envelope, ensure_ascii=False).lower()


async def test_mensagem_sem_dado_sensivel_e_gravada_inteira(client, session, settings) -> None:
    """Cenario: Mensagem sem dado sensivel e gravada inteira.

    Dado um lead que fala so de imovel, preco e bairro, o texto e gravado sem
    redacao.
    """
    texto = "Procuro apartamento de 3 quartos em Pinheiros, até R$ 900 mil, com vaga"

    corpo, envelope = await _receber_e_ler(client, session, settings, "wamid.IMOVEL1", texto)

    assert corpo == texto
    assert envelope is not None
    assert envelope["text"]["body"] == texto

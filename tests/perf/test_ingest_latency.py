"""Criterio de aceite de TEC-122: 200 OK em ate 300 ms no p95.

Marcado `perf` e fora do run padrao: a medicao depende da maquina.
Rode com `python -m pytest -m perf`.
"""

import json
import statistics
import time

import pytest

from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

REQUISICOES = 200
P95_MAXIMO_MS = 300.0


def envelope(indice: int) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [
                                {
                                    "from": "5511911112222",
                                    "id": f"wamid.PERF{indice}",
                                    "type": "text",
                                    "text": {"body": "tem apartamento de 2 quartos?"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }


@pytest.mark.perf
async def test_p95_do_webhook_fica_abaixo_de_300ms(client, settings) -> None:
    latencias_ms: list[float] = []

    for indice in range(REQUISICOES):
        body = json.dumps(envelope(indice)).encode("utf-8")
        headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

        inicio = time.perf_counter()
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)
        latencias_ms.append((time.perf_counter() - inicio) * 1000)

        assert response.status_code == 200

    quantis = statistics.quantiles(latencias_ms, n=100)
    p95 = quantis[94]
    p99 = quantis[98]

    print(f"\np50={statistics.median(latencias_ms):.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms")
    # So o p95 e criterio de aceite de TEC-122. O p99 fica no print como
    # observacao, sem virar orcamento que a historia nunca definiu.
    assert p95 < P95_MAXIMO_MS, f"p95 de {p95:.1f}ms estourou o orcamento de {P95_MAXIMO_MS}ms"

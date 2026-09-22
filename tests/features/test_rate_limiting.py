"""Cenarios Gherkin de TEC-205.

Funcionalidade: Rate limiting e protecao contra abuso
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from mobia.app.config import get_settings
from mobia.domain.limites.models import RateLimitEvent
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

NUMERO = "5511999999999"


def envelope(*wamids: str, texto: str = "oi") -> dict[str, Any]:
    """O envelope da Meta com uma mensagem por wamid.

    Copiado da forma usada em `tests/features/test_dedup_por_message_id.py`;
    confira la se o formato divergir.
    """
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "5511000000000"},
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": NUMERO,
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                                for wamid in wamids
                            ],
                        }
                    }
                ]
            }
        ]
    }


def assinado(payload: dict[str, Any], secret: str) -> tuple[bytes, dict[str, str]]:
    corpo = json.dumps(payload).encode()
    return corpo, {SIGNATURE_HEADER: compute_signature(secret, corpo)}


async def _defers_ms(redis_pool) -> list[float]:
    agora_ms = datetime.now(UTC).timestamp() * 1000
    jobs = await redis_pool.zrange("arq:queue", 0, -1, withscores=True)
    return sorted(score - agora_ms for _, score in jobs)


async def test_numero_que_excede_o_limite_entra_em_backoff(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Numero que excede o limite entra em backoff."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "20")
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "1")
    monkeypatch.setenv("ATRASO_DE_BACKOFF_SEGUNDOS", "25")
    get_settings.cache_clear()

    # Dado um numero que enviou 20 mensagens no ultimo minuto
    corpo, cabecalhos = assinado(
        envelope(*[f"wamid.b{i}" for i in range(20)]),
        get_settings().whatsapp_app_secret,
    )
    await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)

    # Quando ele envia a vigesima primeira
    corpo, cabecalhos = assinado(envelope("wamid.b20"), get_settings().whatsapp_app_secret)
    await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)

    # Entao a mensagem entra em backoff
    # E nenhum processamento de LLM e disparado por ela imediatamente
    defers = await _defers_ms(redis_pool)
    assert len(defers) == 21
    assert max(defers) > 20_000


async def test_ip_que_excede_o_limite_no_widget(
    client, monkeypatch, caches_de_cliente_limpos
) -> None:
    """Cenario: IP que excede o limite no widget.

    O widget web e o TEC-124 e ainda nao existe; o limite por IP vale para
    toda rota HTTP menos as de `ROTAS_ISENTAS`, entao o cenario e exercitado
    contra uma rota real. Quando o widget existir, ele ja nasce coberto pelo
    mesmo middleware -- ver D1 do desenho.
    """
    monkeypatch.setenv("RATE_LIMIT_REQUISICOES_POR_IP_POR_MINUTO", "100")
    get_settings.cache_clear()

    # Dado um IP com 100 requisicoes no ultimo minuto
    for _ in range(100):
        assert (await client.get("/docs")).status_code == 200

    # Quando ele faz a centesima primeira / Entao a requisicao e limitada
    assert (await client.get("/docs")).status_code == 429


async def test_lead_legitimo_nao_e_punido_com_erro(
    client, session, redis_pool, monkeypatch, caches_de_cliente_limpos
) -> None:
    """Cenario: Lead legitimo nao e punido com erro.

    **Este cenario passa sem exercitar o limitador**, e isso esta registrado
    no comentario da card em vez de disfarcado: cinco mensagens estao muito
    abaixo de vinte, entao ele passaria identico se o rate limiting nao
    existisse. Quem exercita o backoff e o primeiro cenario deste arquivo.
    Mantido porque e o criterio de aceite escrito na card, e porque ele de
    fato prende uma regressao possivel -- a de alguem trocar o adiamento por
    recusa e o lead legitimo comecar a receber erro.
    """
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "20")
    get_settings.cache_clear()

    # Dado um lead que envia 5 mensagens rapidas em sequencia
    # Quando elas sao processadas
    for i in range(5):
        corpo, cabecalhos = assinado(envelope(f"wamid.l{i}"), get_settings().whatsapp_app_secret)
        resposta = await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)
        # Entao nenhuma e rejeitada com erro
        assert resposta.status_code == 200

    assert (await session.execute(select(RateLimitEvent))).first() is None


async def test_bloqueio_vira_evento(
    client, session, redis_pool, monkeypatch, caches_de_cliente_limpos
) -> None:
    """Cenario: Bloqueio vira evento."""
    monkeypatch.setenv("RATE_LIMIT_MENSAGENS_POR_MINUTO", "20")
    get_settings.cache_clear()

    # Dado um numero bloqueado por rate limit
    corpo, cabecalhos = assinado(
        envelope(*[f"wamid.e{i}" for i in range(21)]),
        get_settings().whatsapp_app_secret,
    )
    await client.post("/webhooks/whatsapp", content=corpo, headers=cabecalhos)

    # Quando o evento e consultado
    linha = (await session.execute(select(RateLimitEvent))).scalar_one()

    # Entao constam o numero, o momento e o volume que disparou o limite
    assert linha.chave == NUMERO
    assert linha.created_at is not None
    assert linha.volume == 21
    assert linha.limite == 20

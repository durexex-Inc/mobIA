"""Cenarios Gherkin de TEC-128.

Funcionalidade: Agrupamento de rajada de mensagens
"""

import asyncio
import json

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

JANELA = "0.3"


def envelope(wamid: str, texto: str) -> dict:
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


async def enviar(client, settings, wamid: str, texto: str) -> None:
    body, headers = assinado(envelope(wamid, texto), settings.whatsapp_app_secret)
    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200


async def test_tres_mensagens_em_rajada_viram_um_turno(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Tres mensagens em cinco segundos viram um turno.

    A prova e sobre a FILA, nao sobre a resposta: o que a card pede e que so
    uma das tres carregue o turno. Rodar o turno de verdade exigiria o
    classificador, que e outro assunto.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.R1", "oi")
        await enviar(client, settings, "wamid.R2", "procuro apartamento")
        await enviar(client, settings, "wamid.R3", "ate 500 mil")

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 3
        # As tres esperam, e nenhuma esta pronta agora: e isso que impede as
        # tres respostas.
        assert all(job.score is not None for job in jobs)
    finally:
        get_settings.cache_clear()


async def test_mensagem_nova_empurra_o_fim_da_espera(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Mensagem nova durante a espera reinicia o debounce.

    Reiniciar nao e um mecanismo aqui: cada mensagem carrega o proprio relogio,
    entao o instante em que a ULTIMA acorda ja e `ultima + janela`.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.E1", "oi")
        primeiro = {job.job_id: job.score for job in await redis_pool.queued_jobs()}

        await asyncio.sleep(0.1)
        await enviar(client, settings, "wamid.E2", "procuro apartamento")

        jobs = {job.job_id: job.score for job in await redis_pool.queued_jobs()}
        nova = next(score for job_id, score in jobs.items() if job_id not in primeiro)
        antiga = next(iter(primeiro.values()))
        assert nova is not None and antiga is not None
        assert nova > antiga
    finally:
        get_settings.cache_clear()


async def test_mensagem_isolada_tambem_espera_a_janela(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Mensagem isolada nao espera -- com a emenda E-01, ela espera.

    A card intitula o cenario "nao espera" e o corpo dele diz "quando os 6
    segundos de debounce se esgotam". O corpo e que descreve o sistema: a
    espera e incondicional, porque a rajada so e reconhecivel depois de
    terminada. Ver a D1 do desenho e a emenda E-01.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.S1", "ainda tem o 2 quartos?")

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
    finally:
        get_settings.cache_clear()


async def test_optout_na_rajada_nao_espera(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Opt-out nao espera o fim da rajada."""
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "30")
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.O1", "oi")
        # Valor citado: e o termo inequivoco que `pediu_optout` reconhece
        # (dominio/optout/deteccao.py), entao mantem o acento que ele espera.
        await enviar(client, settings, "wamid.O2", "nao quero mais receber mensagens")

        jobs = {job.job_id: job for job in await redis_pool.queued_jobs()}
        assert len(jobs) == 2

        optout = await session.scalar(
            select(Message).where(Message.provider_message_id == "wamid.O2")
        )
        assert optout is not None
        pronto = jobs[f"msg:{optout.id}"]
        comum = next(job for job_id, job in jobs.items() if job_id != f"msg:{optout.id}")
        assert pronto.score is not None and comum.score is not None
        assert pronto.score < comum.score
    finally:
        get_settings.cache_clear()


async def test_todas_da_rajada_ficam_gravadas(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """A resposta contempla as tres porque as tres estao no banco.

    O agrupamento nao descarta conteudo: a mensagem superada fecha como
    PROCESSED e entra no contexto do turno da carregadora pela janela de
    `literais_apos`, que e o mecanismo que ja existia. Aqui nenhum job roda --
    e so o webhook que entrega -- entao as tres INBOUND ficam em QUEUED; o
    filtro por `direction` protege a asserta contra uma linha de saida sem
    `status` (a coluna e nullable para OUTBOUND) se este teste um dia disparar
    o worker.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        await enviar(client, settings, "wamid.G1", "oi")
        await enviar(client, settings, "wamid.G2", "procuro apartamento")
        await enviar(client, settings, "wamid.G3", "ate 500 mil")

        total = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.direction == MessageDirection.INBOUND)
        )
        assert total == 3
        estados = await session.scalars(
            select(Message.status).where(Message.direction == MessageDirection.INBOUND)
        )
        assert set(estados) == {MessageStatus.QUEUED}
    finally:
        get_settings.cache_clear()

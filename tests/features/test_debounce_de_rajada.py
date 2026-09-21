"""Cenarios Gherkin de TEC-128.

Funcionalidade: Agrupamento de rajada de mensagens
"""

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import func, select

from mobia.app.config import get_settings
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

JANELA = "0.3"
JANELA_MS = 300.0

# `job.score is not None` nao prova nada: no ARQ instalado (arq/connections.py,
# `queued_jobs`) TODO job da fila tem score, com ou sem `_defer_by` -- vira
# `enqueue_time_ms + defer_by_ms` ou so `enqueue_time_ms`. A prova de que um
# job esperou tem de comparar o score contra o relogio, no padrao de
# `tests/integration/test_queue.py:87-111`. A folga e proporcional a
# `JANELA_MS`: o limite de baixo fica bem acima do que o webhook leva sem
# nenhum atraso (persistir no Postgres + enfileirar, tipicamente poucas
# dezenas de ms nesta maquina) e o de cima tolera lentidao esporadica do
# ambiente sem abrir mao de provar que o atraso nao e zero.
ESPERA_MINIMA_MS = 200.0
ESPERA_MAXIMA_MS = 3_000.0

# Limite para "o job nasceu pronto" (atraso zero), no mesmo padrao de
# `test_optout_fura_a_janela.py` e `test_queue.py::test_sem_atraso_o_job_
# nasce_pronto`: bem abaixo de `ESPERA_MINIMA_MS`, entao os dois limites nunca
# se confundem.
PRONTO_MAX_MS = 1_000.0


def agora_ms() -> float:
    return datetime.now(UTC).timestamp() * 1000


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


async def test_tres_mensagens_em_rajada_nenhuma_sai_na_hora(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Tres mensagens em cinco segundos viram um turno.

    A prova e sobre a FILA, nao sobre a resposta, e nao sobre o turno: nenhum
    job roda aqui, entao "viram um turno" nao e o que este teste demonstra --
    quem prova que so a ultima carrega o turno e
    `tests/integration/test_process_message_agrupado.py` e
    `tests/integration/test_rajada.py`. O que fica provado, com o relogio, e a
    precondicao de que a card depende: nenhuma das tres sai pronta na hora, o
    que e o que impede as tres respostas imediatas.
    """
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", JANELA)
    get_settings.cache_clear()
    try:
        antes_ms = agora_ms()
        await enviar(client, settings, "wamid.R1", "oi")
        await enviar(client, settings, "wamid.R2", "procuro apartamento")
        await enviar(client, settings, "wamid.R3", "ate 500 mil")

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 3
        # As tres esperam, e nenhuma esta pronta agora: e isso que impede as
        # tres respostas. `antes_ms` e anterior as tres requisicoes, entao o
        # limite de baixo vale para as tres (a segunda e a terceira so podem
        # ter esperado MAIS, nunca menos, porque partem de um relogio ja
        # adiantado).
        atrasos = [job.score - antes_ms for job in jobs if job.score is not None]
        assert len(atrasos) == 3
        assert all(atraso > ESPERA_MINIMA_MS for atraso in atrasos)
        assert all(atraso < ESPERA_MAXIMA_MS for atraso in atrasos)
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
        antes_ms = agora_ms()
        await enviar(client, settings, "wamid.S1", "ainda tem o 2 quartos?")

        jobs = await redis_pool.queued_jobs()
        assert len(jobs) == 1
        assert jobs[0].score is not None
        # E aqui que o comportamento pre-emenda (atraso zero para mensagem
        # isolada) e distinguido do emendado: com atraso zero o score ficaria
        # perto de `antes_ms` (dentro de `PRONTO_MAX_MS`), nao acima de
        # `ESPERA_MINIMA_MS`.
        atraso = jobs[0].score - antes_ms
        assert ESPERA_MINIMA_MS < atraso < ESPERA_MAXIMA_MS
    finally:
        get_settings.cache_clear()


async def test_optout_na_rajada_nao_espera(
    client, session, redis_pool, settings, monkeypatch
) -> None:
    """Cenario: Opt-out nao espera o fim da rajada."""
    monkeypatch.setenv("DEBOUNCE_DE_RAJADA_SEGUNDOS", "30")
    get_settings.cache_clear()
    try:
        antes_ms = agora_ms()
        await enviar(client, settings, "wamid.O1", "oi")
        # Valor citado: a grafia tem de bater exatamente com o termo que
        # `_TERMOS_INEQUIVOCOS` guarda em `src/mobia/domain/optout/deteccao.py`
        # -- ali o termo tambem nao leva acento, entao nao ha divergencia a
        # preservar aqui.
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
        # A RN-01.6 pede atraso ZERO para o opt-out, nao "mais rapido que o
        # comum": a comparacao relativa sozinha passaria com uma implementacao
        # que desse ao opt-out so metade da janela. A comparacao contra o
        # relogio fecha essa lacuna.
        assert pronto.score - antes_ms < PRONTO_MAX_MS
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
    e so o webhook que entrega -- entao as tres INBOUND ficam em QUEUED.

    O filtro por `direction == INBOUND` e deliberado e tem custo, nao so
    ganho: sem ele, a asserta original reprovaria se aparecesse qualquer linha
    de outra direcao -- inclusive uma hipotetica resposta escapando
    sincronamente da janela, que seria exatamente o tipo de regressao que se
    quer pegar. Com o filtro, essa regressao especifica fica invisivel para
    este teste (uma linha OUTBOUND extra nao derruba a asserta). A troca e
    aceita porque `status=None` em OUTBOUND e esperado por desenho (a coluna
    so marca o pipeline de ingestao, ver `models.py`), entao sem o filtro o
    teste reprovaria por um motivo estrutural, nao por uma regressao real, no
    dia em que deixar de ser verdade que nenhum job roda aqui.
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

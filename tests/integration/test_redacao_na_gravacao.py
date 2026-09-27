"""TEC-380: os dois pontos que gravam texto do lead gravam o texto redigido.

`IngestionService._persist` (WhatsApp e widget) e `transcrever_audio`. Em
cada um, o que se le de volta do banco -- `text_body` E `raw_payload` -- nao
tem o dado.
"""

import time
from typing import Any

import httpx
from conftest import TranscritorFake, ogg_opus

from mobia.app.config import get_settings
from mobia.domain.messages.canais import CANAL_WEB
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.models import MidiaRecebida, StatusDaMidia
from mobia.domain.privacidade.redacao import MARCADOR_DE_DADO_SENSIVEL
from mobia.infra.crypto import aad_de, decrypt, decrypt_json
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.transcrever_audio import transcrever_audio

S = MARCADOR_DE_DADO_SENSIVEL


async def _gravada(session, message_id) -> tuple[str | None, dict[str, Any] | None]:
    linha = await session.get(Message, message_id, populate_existing=True)
    assert linha is not None
    return (
        decrypt(linha.text_body, aad_de(linha.id, "text_body")),
        decrypt_json(linha.raw_payload, aad_de(linha.id, "raw_payload")),
    )


async def test_whatsapp_grava_corpo_e_envelope_redigidos(session, redis_pool) -> None:
    texto = "tenho diabetes, quero 2 quartos no Centro"
    parsed = ParsedMessage(
        provider_message_id="wamid.SENS1",
        sender_external_id="5511977778888",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body=texto,
        raw_payload={"id": "wamid.SENS1", "type": "text", "text": {"body": texto}},
    )

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest([parsed])

    corpo, envelope = await _gravada(session, message_id)
    assert corpo == f"tenho {S}, quero 2 quartos no Centro"
    assert envelope == {
        "id": "wamid.SENS1",
        "type": "text",
        "text": {"body": f"tenho {S}, quero 2 quartos no Centro"},
    }


async def test_legenda_de_imagem_e_redigida_e_a_midia_segue(session, redis_pool) -> None:
    """A legenda vira `text_body` (TEC-132) e fica no envelope; os ids de midia
    que `linha_pendente` le do envelope continuam la."""
    parsed = ParsedMessage(
        provider_message_id="wamid.SENS2",
        sender_external_id="5511977778888",
        recipient_external_id="222222222",
        content_type=MessageContentType.IMAGEM,
        text_body="sou católica, gostei desse",
        raw_payload={
            "id": "wamid.SENS2",
            "type": "image",
            "image": {
                "id": "media-9",
                "mime_type": "image/jpeg",
                "caption": "sou católica, gostei desse",
            },
        },
    )

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest([parsed])

    corpo, envelope = await _gravada(session, message_id)
    assert corpo == f"sou {S}, gostei desse"
    assert envelope is not None
    assert envelope["image"] == {
        "id": "media-9",
        "mime_type": "image/jpeg",
        "caption": f"sou {S}, gostei desse",
    }
    midia = await session.get(MidiaRecebida, message_id)
    assert midia is not None and midia.media_id_da_meta == "media-9"


async def test_widget_grava_redigido(session, redis_pool) -> None:
    texto = "minha esposa está grávida"
    parsed = ParsedMessage(
        provider_message_id="web-sens-1",
        sender_external_id="sessao-web-1",
        recipient_external_id="widget",
        content_type=MessageContentType.TEXTO,
        text_body=texto,
        raw_payload={"tipo": "mensagem", "id": "x", "texto": texto},
    )

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest(
        [parsed], channel=CANAL_WEB
    )

    corpo, envelope = await _gravada(session, message_id)
    assert corpo == f"minha esposa está {S}"
    assert envelope == {"tipo": "mensagem", "id": "x", "texto": f"minha esposa está {S}"}


async def test_optout_continua_detectado_sobre_o_original(session, redis_pool) -> None:
    """A deteccao da ingestao le o `ParsedMessage`, e nao o gravado: a
    redacao nao pode atrasar nem esconder um pedido de parar."""
    parsed = ParsedMessage(
        provider_message_id="wamid.SENS3",
        sender_external_id="5511977778888",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body="estou com depressão, pare de me mandar mensagens",
        raw_payload={"id": "wamid.SENS3", "type": "text"},
    )

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest([parsed])

    # Sem atraso: o opt-out furou o debounce, como antes desta card. O score do
    # ARQ e o instante de execucao em ms; com a janela ele ficaria segundos
    # a frente de agora.
    score = await redis_pool.zscore("arq:queue", f"msg:{message_id}")
    assert score is not None
    janela_ms = get_settings().debounce_de_rajada_segundos * 1000
    assert score < time.time() * 1000 + janela_ms / 2
    corpo, _ = await _gravada(session, message_id)
    assert corpo == f"estou com {S}, pare de me mandar mensagens"


async def test_texto_sem_dado_sensivel_e_gravado_inteiro(session, redis_pool) -> None:
    texto = "procuro apartamento perto da Católica até 600 mil"
    parsed = ParsedMessage(
        provider_message_id="wamid.SENS4",
        sender_external_id="5511977778888",
        recipient_external_id="222222222",
        content_type=MessageContentType.TEXTO,
        text_body=texto,
        raw_payload={"id": "wamid.SENS4", "type": "text", "text": {"body": texto}},
    )

    (message_id,) = await IngestionService(get_sessionmaker(), redis_pool).ingest([parsed])

    corpo, envelope = await _gravada(session, message_id)
    assert corpo == texto
    assert envelope == parsed.raw_payload


async def test_a_transcricao_do_audio_e_redigida(session, tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_access_token", "t")
    mensagem = Message(
        channel="whatsapp",
        conversation_key="5511977778888",
        sender_external_id="5511977778888",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.AUDIO,
        status=MessageStatus.QUEUED,
    )
    session.add(mensagem)
    await session.commit()
    session.add(
        MidiaRecebida(
            message_id=mensagem.id,
            media_id_da_meta="media-1",
            mime_type="audio/ogg",
            status=StatusDaMidia.PENDENTE,
        )
    )
    await session.commit()
    dados = ogg_opus(20.0)

    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://lookaside.fbsbx.com/a":
            return httpx.Response(200, content=dados)
        return httpx.Response(
            200, json={"url": "https://lookaside.fbsbx.com/a", "mime_type": "audio/ogg"}
        )

    ctx = {
        "session_factory": get_sessionmaker(),
        "settings": settings,
        "armazem": ArmazemLocal(tmp_path),
        "cliente_http_da_meta": httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
        "transcritor": TranscritorFake("sou cadeirante e quero térreo"),
        "redis": None,
    }

    assert await transcrever_audio(ctx, str(mensagem.id)) == "transcrita"

    corpo, _ = await _gravada(session, mensagem.id)
    assert corpo == "sou [necessidade de acessibilidade] e quero térreo"

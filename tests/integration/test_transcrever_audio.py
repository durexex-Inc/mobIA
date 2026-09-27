"""O job que transcreve o audio do lead, e a espera do turno. TEC-131, D1 e D2.

A Graph API e simulada por `httpx.MockTransport`, como em `test_baixar_midia.py`;
a Whisper, pelo `TranscritorFake` do conftest; e a fila, por um duble que so
registra o que foi enfileirado.
"""

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import TranscritorFake, ogg_opus

from mobia.app.config import get_settings
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.audio import PRAZO_DA_TRANSCRICAO
from mobia.domain.midia.espera import ha_audio_sem_transcricao
from mobia.domain.midia.models import (
    MidiaRecebida,
    MotivoDaMidia,
    MotivoDaTranscricao,
    StatusDaMidia,
    StatusDaTranscricao,
)
from mobia.domain.midia.politica import chave_do_objeto
from mobia.domain.midia.transcricao import TranscricaoIndisponivel
from mobia.infra.crypto import aad_de, decrypt, decrypt_bytes, encrypt_bytes
from mobia.infra.db import get_sessionmaker
from mobia.infra.queue import PROCESS_MESSAGE_JOB, TRANSCREVER_AUDIO_JOB
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.transcrever_audio import transcrever_audio
from mobia.workers.main import WorkerSettings

TOKEN = "token-de-teste"
URL_DA_META = "https://lookaside.fbsbx.com/x"
CANAL = "whatsapp"
CONVERSA = "5511933334444"


@pytest.fixture
def configuracao(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_access_token", TOKEN)
    return settings


class FilaQueRegistra:
    """O `ArqRedis` do ctx, reduzido ao que o job chama."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue_job(self, nome: str, *args: Any, _job_id: str | None = None, **_: Any):
        self.jobs.append((nome, args, _job_id))
        return object()


async def _mensagem(
    session,
    *,
    tipo: MessageContentType = MessageContentType.AUDIO,
    direcao: MessageDirection = MessageDirection.INBOUND,
    status: MessageStatus = MessageStatus.QUEUED,
) -> Message:
    linha = Message(
        channel=CANAL,
        conversation_key=CONVERSA,
        sender_external_id=CONVERSA,
        role=MessageRole.LEAD if direcao == MessageDirection.INBOUND else MessageRole.AGENTE,
        direction=direcao,
        content_type=tipo,
        status=status,
    )
    session.add(linha)
    await session.commit()
    return linha


async def _audio(
    session,
    *,
    mime: str = "audio/ogg; codecs=opus",
    status: StatusDaMidia = StatusDaMidia.PENDENTE,
    chave: str | None = None,
) -> uuid.UUID:
    """A mensagem de audio e a linha de midia que a ingestao teria gravado."""
    mensagem = await _mensagem(session)
    session.add(
        MidiaRecebida(
            message_id=mensagem.id,
            media_id_da_meta="media-1",
            mime_type=mime,
            sha256=None,
            status=status,
            chave_no_armazem=chave,
        )
    )
    await session.commit()
    return mensagem.id


def _meta(corpo: bytes, *, mime: str = "audio/ogg", status_resolucao: int = 200):
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if str(request.url) == URL_DA_META:
            return httpx.Response(200, content=corpo)
        return httpx.Response(status_resolucao, json={"url": URL_DA_META, "mime_type": mime})

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _ctx(
    tmp_path: Path,
    settings: Any,
    transcritor: TranscritorFake,
    *,
    cliente: httpx.AsyncClient | None = None,
    fila: FilaQueRegistra | None = None,
) -> dict[str, Any]:
    return {
        "session_factory": get_sessionmaker(),
        "settings": settings,
        "armazem": ArmazemLocal(tmp_path),
        "cliente_http_da_meta": cliente,
        "transcritor": transcritor,
        "redis": fila,
    }


async def _midia(session, message_id: uuid.UUID) -> MidiaRecebida:
    session.expire_all()
    linha = await session.get(MidiaRecebida, message_id)
    assert linha is not None
    return linha


async def _texto(session, message_id: uuid.UUID) -> str | None:
    session.expire_all()
    linha = await session.get(Message, message_id)
    assert linha is not None
    return decrypt(linha.text_body, aad_de(linha.id, "text_body"))


async def test_audio_curto_e_transcrito_guardado_e_acorda_o_turno(
    session, configuracao, tmp_path
) -> None:
    audio = await _audio(session)
    dados = ogg_opus(40.0)
    transcritor = TranscritorFake("quero um apartamento de 2 quartos")
    fila = FilaQueRegistra()

    resultado = await transcrever_audio(
        _ctx(tmp_path, configuracao, transcritor, cliente=_meta(dados), fila=fila), str(audio)
    )

    assert resultado == "transcrita"
    assert await _texto(session, audio) == "quero um apartamento de 2 quartos"
    midia = await _midia(session, audio)
    assert midia.status_da_transcricao == StatusDaTranscricao.TRANSCRITA
    assert midia.duracao_segundos == pytest.approx(40.0)
    assert midia.transcrita_em is not None
    # O audio original fica guardado, cifrado, como a imagem da TEC-132.
    assert midia.status == StatusDaMidia.ARMAZENADA
    blob = (tmp_path / chave_do_objeto(audio)).read_bytes()
    assert decrypt_bytes(blob, aad_de(audio, "midia")) == dados
    assert transcritor.chamadas == [(dados, "ogg")]
    # Sem mensagem mais nova, quem esperava era o proprio audio.
    assert fila.jobs == [(PROCESS_MESSAGE_JOB, (str(audio),), f"msg:{audio}:audio:{audio}")]


async def test_audio_longo_nao_chega_a_whisper(session, configuracao, tmp_path) -> None:
    audio = await _audio(session)
    transcritor = TranscritorFake()

    resultado = await transcrever_audio(
        _ctx(tmp_path, configuracao, transcritor, cliente=_meta(ogg_opus(150.0))), str(audio)
    )

    assert resultado == "recusada"
    assert transcritor.chamadas == []
    midia = await _midia(session, audio)
    assert midia.motivo_da_transcricao == MotivoDaTranscricao.ACIMA_DA_DURACAO
    assert midia.duracao_segundos == pytest.approx(150.0)
    # Recusado para transcrever, e guardado do mesmo jeito.
    assert midia.status == StatusDaMidia.ARMAZENADA
    assert await _texto(session, audio) is None


async def test_audio_de_exatamente_120_segundos_e_transcrito(
    session, configuracao, tmp_path
) -> None:
    audio = await _audio(session)

    resultado = await transcrever_audio(
        _ctx(tmp_path, configuracao, TranscritorFake(), cliente=_meta(ogg_opus(120.0))), str(audio)
    )

    assert resultado == "transcrita"


async def test_formato_sem_duracao_previa_confere_a_duracao_da_whisper(
    session, configuracao, tmp_path
) -> None:
    """D2, passo 6: o MP3 encaminhado nao se mede antes; a Whisper transcreve e
    diz 150s, e o texto e descartado."""
    audio = await _audio(session, mime="audio/mpeg")
    transcritor = TranscritorFake("fala longa", duracao=150.0)

    resultado = await transcrever_audio(
        _ctx(
            tmp_path,
            configuracao,
            transcritor,
            cliente=_meta(b"ID3" + b"\x00" * 64, mime="audio/mpeg"),
        ),
        str(audio),
    )

    assert resultado == "recusada"
    assert [extensao for _, extensao in transcritor.chamadas] == ["mp3"]
    assert await _texto(session, audio) is None


async def test_whisper_fora_do_ar_registra_a_falha(session, configuracao, tmp_path) -> None:
    audio = await _audio(session)
    fila = FilaQueRegistra()

    resultado = await transcrever_audio(
        _ctx(
            tmp_path,
            configuracao,
            TranscritorFake(erro=TranscricaoIndisponivel("APIConnectionError")),
            cliente=_meta(ogg_opus(40.0)),
            fila=fila,
        ),
        str(audio),
    )

    assert resultado == "falhou"
    midia = await _midia(session, audio)
    assert midia.status_da_transcricao == StatusDaTranscricao.FALHOU
    assert midia.motivo_da_transcricao == MotivoDaTranscricao.SERVICO_INDISPONIVEL
    # A falha tambem acorda o turno: e ele que manda o pedido de texto.
    assert len(fila.jobs) == 1


async def test_amr_nao_vai_para_a_whisper(session, configuracao, tmp_path) -> None:
    audio = await _audio(session, mime="audio/amr")
    transcritor = TranscritorFake()

    resultado = await transcrever_audio(
        _ctx(
            tmp_path,
            configuracao,
            transcritor,
            cliente=_meta(b"#!AMR\n" + b"\x00" * 32, mime="audio/amr"),
        ),
        str(audio),
    )

    assert resultado == "falhou"
    assert transcritor.chamadas == []
    assert (await _midia(session, audio)).motivo_da_transcricao == (
        MotivoDaTranscricao.FORMATO_NAO_SUPORTADO
    )


async def test_transcricao_vazia_e_falha(session, configuracao, tmp_path) -> None:
    audio = await _audio(session)

    resultado = await transcrever_audio(
        _ctx(tmp_path, configuracao, TranscritorFake("   "), cliente=_meta(ogg_opus(5.0))),
        str(audio),
    )

    assert resultado == "falhou"
    assert (await _midia(session, audio)).motivo_da_transcricao == (
        MotivoDaTranscricao.TRANSCRICAO_VAZIA
    )
    assert await _texto(session, audio) is None


async def test_meta_recusando_o_download_e_midia_indisponivel(
    session, configuracao, tmp_path
) -> None:
    audio = await _audio(session)
    transcritor = TranscritorFake()

    resultado = await transcrever_audio(
        _ctx(tmp_path, configuracao, transcritor, cliente=_meta(b"", status_resolucao=404)),
        str(audio),
    )

    assert resultado == "falhou"
    assert transcritor.chamadas == []
    midia = await _midia(session, audio)
    assert midia.motivo_da_transcricao == MotivoDaTranscricao.MIDIA_INDISPONIVEL
    # O desfecho do download e gravado pelo mesmo caminho de `baixar_midia`.
    assert midia.status == StatusDaMidia.FALHOU
    assert midia.motivo == MotivoDaMidia.RECUSADA_PELA_META


async def test_audio_ja_armazenado_e_lido_do_armazem_sem_ir_a_meta(
    session, configuracao, tmp_path
) -> None:
    """A `sweep_midias_pendentes` pode ter guardado o audio antes: nao se baixa
    de novo. O cliente da Meta ausente faria o job abrir um de verdade -- e o
    teste pega isso porque nao ha rede para ele."""
    dados = ogg_opus(10.0)
    armazem = ArmazemLocal(tmp_path)
    audio_id = uuid.uuid4()
    chave = chave_do_objeto(audio_id)
    mensagem = Message(
        id=audio_id,
        channel=CANAL,
        conversation_key=CONVERSA,
        sender_external_id=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.AUDIO,
        status=MessageStatus.QUEUED,
    )
    session.add(mensagem)
    await session.commit()
    session.add(
        MidiaRecebida(
            message_id=audio_id,
            media_id_da_meta="media-1",
            mime_type="audio/ogg",
            status=StatusDaMidia.ARMAZENADA,
            chave_no_armazem=chave,
        )
    )
    await session.commit()
    await armazem.guardar(chave, encrypt_bytes(dados, aad_de(audio_id, "midia")))

    def _nao_chame(request: httpx.Request) -> httpx.Response:
        raise AssertionError("o audio ja estava guardado")

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_nao_chame))
    transcritor = TranscritorFake()

    resultado = await transcrever_audio(
        _ctx(tmp_path, configuracao, transcritor, cliente=cliente), str(audio_id)
    )

    assert resultado == "transcrita"
    assert transcritor.chamadas == [(dados, "ogg")]


async def test_segunda_passada_nao_faz_nada(session, configuracao, tmp_path) -> None:
    audio = await _audio(session)
    transcritor = TranscritorFake()
    ctx = _ctx(tmp_path, configuracao, transcritor, cliente=_meta(ogg_opus(10.0)))

    assert await transcrever_audio(ctx, str(audio)) == "transcrita"
    assert await transcrever_audio(ctx, str(audio)) == "nada_a_fazer"
    assert len(transcritor.chamadas) == 1


async def test_acorda_a_mensagem_mais_nova_da_conversa(session, configuracao, tmp_path) -> None:
    """D1: com audio seguido de "?", quem responde a rajada e o "?"."""
    audio = await _audio(session)
    depois = await _mensagem(session, tipo=MessageContentType.TEXTO)
    fila = FilaQueRegistra()

    await transcrever_audio(
        _ctx(tmp_path, configuracao, TranscritorFake(), cliente=_meta(ogg_opus(10.0)), fila=fila),
        str(audio),
    )

    assert fila.jobs == [(PROCESS_MESSAGE_JOB, (str(depois.id),), f"msg:{depois.id}:audio:{audio}")]


async def test_excecao_inesperada_grava_falha_acorda_e_sobe(
    session, configuracao, tmp_path
) -> None:
    audio = await _audio(session)
    fila = FilaQueRegistra()

    with pytest.raises(RuntimeError):
        await transcrever_audio(
            _ctx(
                tmp_path,
                configuracao,
                TranscritorFake(erro=RuntimeError("defeito")),
                cliente=_meta(ogg_opus(10.0)),
                fila=fila,
            ),
            str(audio),
        )

    assert (await _midia(session, audio)).motivo_da_transcricao == (
        MotivoDaTranscricao.ERRO_INESPERADO
    )
    assert len(fila.jobs) == 1


def test_o_job_esta_registrado_sem_retentativa() -> None:
    registrado = {
        getattr(f, "name", None): f for f in WorkerSettings.functions if hasattr(f, "name")
    }
    assert registrado[TRANSCREVER_AUDIO_JOB].max_tries == 1


# --- A espera (D1) ---


async def test_o_turno_espera_o_audio_da_rajada_sem_reivindicar(session) -> None:
    audio = await _audio(session)
    depois = await _mensagem(session, tipo=MessageContentType.TEXTO)

    # As portas do turno entram vazias: `process_message` as le de cara, mas a
    # espera sai antes de qualquer uma ser usada -- e e isso que se afirma.
    ctx = {
        "session_factory": get_sessionmaker(),
        "outbound": None,
        "agendador": None,
        "agendador_de_avisos": None,
    }
    resultado = await process_message(ctx, str(depois.id))

    assert resultado == "aguardando_transcricao"
    linha = await session.get(Message, depois.id, populate_existing=True)
    assert linha is not None
    # Nem claim, nem lease, nem tentativa: a linha fica como chegou.
    assert (linha.status, linha.claimed_at, linha.attempts) == (MessageStatus.QUEUED, None, 0)
    assert audio is not None


async def test_audio_com_desfecho_nao_segura_o_turno(session) -> None:
    audio = await _audio(session)
    midia = await session.get(MidiaRecebida, audio)
    assert midia is not None
    midia.status_da_transcricao = StatusDaTranscricao.FALHOU
    await session.commit()
    linha = await session.get(Message, audio)
    assert linha is not None

    assert not await ha_audio_sem_transcricao(session, linha)


async def test_passado_o_prazo_o_audio_nao_segura_mais(session) -> None:
    audio = await _audio(session)
    linha = await session.get(Message, audio)
    midia = await session.get(MidiaRecebida, audio)
    assert linha is not None and midia is not None

    assert await ha_audio_sem_transcricao(session, linha, agora=midia.criado_em)
    depois_do_prazo = midia.criado_em + PRAZO_DA_TRANSCRICAO + timedelta(seconds=1)
    assert not await ha_audio_sem_transcricao(session, linha, agora=depois_do_prazo)


async def test_audio_antes_da_ultima_fala_do_agente_nao_segura(session) -> None:
    audio = await _audio(session)
    await _mensagem(
        session,
        tipo=MessageContentType.TEXTO,
        direcao=MessageDirection.OUTBOUND,
        status=MessageStatus.PROCESSED,
    )
    depois = await _mensagem(session, tipo=MessageContentType.TEXTO)
    assert audio is not None

    assert not await ha_audio_sem_transcricao(session, depois)


async def test_audio_mais_novo_nao_segura_a_mensagem_anterior(session) -> None:
    """A rajada vai ate ESTA mensagem: o turno de uma mensagem anterior ao
    audio vai fechar "agrupado" de qualquer jeito, e nao ha o que esperar."""
    antes = await _mensagem(session, tipo=MessageContentType.TEXTO)
    await _audio(session)

    assert not await ha_audio_sem_transcricao(session, antes)

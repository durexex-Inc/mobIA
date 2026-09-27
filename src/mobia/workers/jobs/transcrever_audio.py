"""Transcrever o audio do lead e acordar o turno que o espera. TEC-131, D1 e D2.

**Job proprio, e nao um passo do turno**, porque o turno nao tem folga: a soma
de `test_o_pior_turno_cabe_no_job_timeout` deixa 3s acima da reserva do banco,
e so resolver a midia na Graph API ja pode custar 10s. Aqui o `job_timeout`
e do job inteiro, e o pior caso (resolver, baixar, 30s da Whisper) cabe com
folga.

Toda saida grava um desfecho por `gravar_transcricao`, que so muda linha ainda
sem desfecho -- entao o job e idempotente -- e toda saida acorda o turno,
inclusive a da excecao inesperada: o turno esta parado esperando por este job
(`domain/midia/espera.py`), e um desfecho que nao o acorda deixa o lead em
silencio ate o `sweep_stalled`.

**Nenhuma falha retenta** (D2). O lead esta esperando, e a card pede para a
falha o pedido de texto, nao uma espera maior.
"""

import uuid
from typing import Any, NamedTuple

import httpx
import structlog
from sqlalchemy import select

from mobia.app.config import Settings, get_settings
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.midia import graph
from mobia.domain.midia.armazem import ArmazemDeMidia
from mobia.domain.midia.audio import (
    dentro_do_limite,
    duracao_do_ogg_opus,
    extensao_para_transcricao,
)
from mobia.domain.midia.models import (
    MidiaRecebida,
    MotivoDaTranscricao,
    StatusDaMidia,
    StatusDaTranscricao,
)
from mobia.domain.midia.repositorio import gravar_transcricao, ler_midia
from mobia.domain.midia.transcricao import TranscricaoIndisponivel, TranscritorPort
from mobia.infra.crypto import aad_de, decrypt_bytes
from mobia.infra.queue import enqueue_turno_apos_transcricao
from mobia.workers.jobs.baixar_midia import DesfechoDoDownload, baixar_e_guardar, gravar_desfecho

log = structlog.get_logger(__name__)


class _Desfecho(NamedTuple):
    status: StatusDaTranscricao
    motivo: MotivoDaTranscricao | None = None
    duracao: float | None = None
    texto: str | None = None


class _SemAudio(Exception):
    """Os bytes nao vieram: a Meta nao entregou, ou o armazem nao devolveu."""


async def transcrever_audio(ctx: dict[str, Any], message_id: str) -> str:
    """Devolve o status gravado, em minusculas, ou `nada_a_fazer`."""
    identificador = uuid.UUID(message_id)
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    async with session_factory() as sessao:
        midia = await ler_midia(sessao, identificador)
    if midia is None or midia.status_da_transcricao is not None:
        return "nada_a_fazer"

    try:
        desfecho = await _decidir(ctx, midia, settings)
    except Exception:
        await gravar_transcricao(
            session_factory,
            identificador,
            status=StatusDaTranscricao.FALHOU,
            motivo=MotivoDaTranscricao.ERRO_INESPERADO,
        )
        log.warning(
            "audio.transcricao_falhou",
            message_id=message_id,
            motivo=MotivoDaTranscricao.ERRO_INESPERADO.value,
        )
        await _acordar_turno(ctx, identificador)
        raise

    gravou = await gravar_transcricao(
        session_factory,
        identificador,
        status=desfecho.status,
        motivo=desfecho.motivo,
        duracao=desfecho.duracao,
        texto=desfecho.texto,
    )
    if not gravou:
        # Outro job sobre o mesmo audio gravou primeiro. O desfecho dele vale, e
        # foi ele quem acordou o turno.
        log.info("audio.corrida_perdida", message_id=message_id)
        return "nada_a_fazer"
    # FALHOU em WARNING, como em `baixar_midia`: e o nivel que alimenta alerta,
    # e e o registro que a card pede "para reprocessamento". RECUSADA (acima da
    # duracao) e o caminho previsto, e fica em INFO. O texto nunca entra no log.
    emitir = log.warning if desfecho.status == StatusDaTranscricao.FALHOU else log.info
    emitir(
        "audio.transcricao_falhou"
        if desfecho.status == StatusDaTranscricao.FALHOU
        else f"audio.{desfecho.status.value.lower()}",
        message_id=message_id,
        motivo=desfecho.motivo.value if desfecho.motivo else None,
        duracao_segundos=desfecho.duracao,
    )
    await _acordar_turno(ctx, identificador)
    return desfecho.status.value.lower()


async def _decidir(ctx: dict[str, Any], midia: MidiaRecebida, settings: Settings) -> _Desfecho:
    """A sequencia da D2, do audio em maos ao desfecho. Nao grava nada."""
    try:
        dados = await _obter_audio(ctx, midia, settings)
    except _SemAudio:
        return _Desfecho(StatusDaTranscricao.FALHOU, MotivoDaTranscricao.MIDIA_INDISPONIVEL)

    limite = settings.transcricao_duracao_maxima_segundos
    # Antes de transcrever: e o que faz o audio longo NAO ser transcrito. So
    # mede Ogg/Opus, que e toda nota de voz do WhatsApp.
    duracao = duracao_do_ogg_opus(dados)
    if duracao is not None and not dentro_do_limite(duracao, limite):
        return _Desfecho(
            StatusDaTranscricao.RECUSADA, MotivoDaTranscricao.ACIMA_DA_DURACAO, duracao
        )

    extensao = extensao_para_transcricao(midia.mime_type)
    if extensao is None:
        return _Desfecho(
            StatusDaTranscricao.FALHOU, MotivoDaTranscricao.FORMATO_NAO_SUPORTADO, duracao
        )

    transcritor: TranscritorPort = ctx["transcritor"]
    try:
        transcricao = await transcritor.transcrever(dados, extensao)
    except TranscricaoIndisponivel:
        return _Desfecho(
            StatusDaTranscricao.FALHOU, MotivoDaTranscricao.SERVICO_INDISPONIVEL, duracao
        )

    # A segunda conferencia (D2, passo 6): nos formatos que o parser nao mede,
    # quem diz a duracao e a Whisper -- depois de ja ter transcrito. O texto e
    # descartado, e o lead recebe a mesma recusa do audio longo.
    if duracao is None:
        duracao = transcricao.duracao_segundos
        if duracao is not None and not dentro_do_limite(duracao, limite):
            return _Desfecho(
                StatusDaTranscricao.RECUSADA, MotivoDaTranscricao.ACIMA_DA_DURACAO, duracao
            )

    texto = transcricao.texto.strip()
    if not texto:
        # Audio mudo, ou so ruido. Gravar texto vazio faria o turno responder a
        # uma fala em branco; o pedido de texto e a resposta certa.
        return _Desfecho(StatusDaTranscricao.FALHOU, MotivoDaTranscricao.TRANSCRICAO_VAZIA, duracao)
    return _Desfecho(StatusDaTranscricao.TRANSCRITA, None, duracao, texto)


async def _obter_audio(ctx: dict[str, Any], midia: MidiaRecebida, settings: Settings) -> bytes:
    """Os bytes em claro: do armazem se ja estao la, da Meta se nao.

    Baixando, grava tambem o desfecho do DOWNLOAD (ARMAZENADA, ou o terminal
    que a sequencia de `baixar_e_guardar` decidir) -- e a card manda guardar o
    audio original. O retentavel nao grava nada: a linha fica PENDENTE e a
    `sweep_midias_pendentes` a leva a `baixar_midia` depois, entao o audio e
    guardado mesmo que a transcricao tenha desistido.
    """
    armazem: ArmazemDeMidia = ctx["armazem"]
    identificador = midia.message_id
    if midia.status == StatusDaMidia.ARMAZENADA and midia.chave_no_armazem:
        try:
            blob = await armazem.ler(midia.chave_no_armazem)
        except Exception as exc:
            raise _SemAudio(type(exc).__name__) from exc
        return decrypt_bytes(blob, aad_de(identificador, "midia"))
    if midia.status != StatusDaMidia.PENDENTE:
        # RECUSADA ou FALHOU no download: nao ha audio para transcrever.
        raise _SemAudio(midia.status)

    session_factory = ctx["session_factory"]
    injetado: httpx.AsyncClient | None = ctx.get("cliente_http_da_meta")
    cliente = injetado or httpx.AsyncClient(timeout=graph.TIMEOUT_SEGUNDOS)
    try:
        chave, dados = await baixar_e_guardar(
            identificador,
            midia.media_id_da_meta,
            midia.sha256,
            teto=settings.midia_teto_bytes,
            cliente=cliente,
            armazem=armazem,
        )
    except DesfechoDoDownload as desfecho:
        await gravar_desfecho(session_factory, identificador, desfecho.status, desfecho.motivo)
        raise _SemAudio(desfecho.motivo.value) from desfecho
    except graph.MidiaIndisponivel as exc:
        raise _SemAudio(str(exc)) from exc
    finally:
        if injetado is None:
            await cliente.aclose()
    await gravar_desfecho(
        session_factory,
        identificador,
        StatusDaMidia.ARMAZENADA,
        None,
        chave=chave,
        tamanho=len(dados),
    )
    return dados


async def _acordar_turno(ctx: dict[str, Any], audio_id: uuid.UUID) -> None:
    """Enfileira o turno da INBOUND mais nova da conversa do audio (D1).

    A mais nova, e nao o proprio audio: com audio seguido de "?", quem responde
    a rajada e o "?" (RN-01.6), e e ele que esta esperando. O audio fecha
    "agrupado" no turno dele.

    Engole toda falha, como os enqueues da ingestao: a mensagem continua QUEUED
    (a espera nao reivindica nada), e o `sweep_stalled` a recupera.
    """
    fila = ctx.get("redis")
    if fila is None:
        log.warning("audio.acordar_turno_falhou", message_id=str(audio_id), reason="no_queue")
        return
    try:
        async with ctx["session_factory"]() as sessao:
            audio = await sessao.get(Message, audio_id)
            if audio is None:
                return
            mais_nova = await sessao.scalar(
                select(Message.id)
                .where(
                    Message.channel == audio.channel,
                    Message.conversation_key == audio.conversation_key,
                    Message.direction == MessageDirection.INBOUND,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        if mais_nova is not None:
            await enqueue_turno_apos_transcricao(fila, mais_nova, audio_id=audio_id)
    except Exception as exc:
        log.warning(
            "audio.acordar_turno_falhou", message_id=str(audio_id), reason=type(exc).__name__
        )

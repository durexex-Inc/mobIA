"""A linha de midia e o seu ciclo de status. TEC-132, D2."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.models import MidiaRecebida, MotivoDaMidia, StatusDaMidia
from mobia.domain.midia.repositorio import (
    expirar_pendentes,
    ler_midia,
    linha_pendente,
    marcar,
    pendentes_para_reenfileirar,
)
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"

ENVELOPE_IMAGEM = {
    "type": "image",
    "image": {"id": "m1", "mime_type": "image/jpeg", "sha256": "ab" * 32},
}


def test_linha_pendente_de_imagem() -> None:
    identificador = uuid.uuid4()
    linha = linha_pendente(identificador, ENVELOPE_IMAGEM, MessageContentType.IMAGEM)
    assert linha == {
        "message_id": identificador,
        "media_id_da_meta": "m1",
        "mime_type": "image/jpeg",
        "sha256": "ab" * 32,
        "status": StatusDaMidia.PENDENTE,
    }


def test_linha_pendente_de_documento() -> None:
    envelope = {
        "type": "document",
        "document": {"id": "d1", "mime_type": "application/pdf", "filename": "rg.pdf"},
    }
    linha = linha_pendente(uuid.uuid4(), envelope, MessageContentType.DOCUMENTO)
    assert linha is not None
    # O nome do arquivo NAO vira coluna (D2): fica cifrado no raw_payload.
    assert "filename" not in linha and linha["sha256"] is None


def test_texto_e_audio_nao_geram_linha() -> None:
    assert linha_pendente(uuid.uuid4(), {"type": "text"}, MessageContentType.TEXTO) is None
    envelope_audio = {"type": "audio", "audio": {"id": "a"}}
    assert linha_pendente(uuid.uuid4(), envelope_audio, MessageContentType.AUDIO) is None


def test_envelope_sem_id_nao_gera_linha() -> None:
    envelope = {"type": "image", "image": {}}
    assert linha_pendente(uuid.uuid4(), envelope, MessageContentType.IMAGEM) is None


async def _mensagem_de_midia(session) -> uuid.UUID:
    """Uma Message minima para servir de FK -- padrao da TEC-129 (test_vinculos_de_sessao)."""
    linha = Message(
        channel=CANAL,
        conversation_key=CONVERSA,
        sender_external_id=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.IMAGEM,
        status=MessageStatus.RECEIVED,
    )
    session.add(linha)
    await session.commit()
    return linha.id


async def _gravar_pendente(
    session, message_id: uuid.UUID, *, criado_em: datetime | None = None
) -> None:
    """Grava a linha PENDENTE que o teste precisa, com `linha_pendente` de verdade."""
    valores = linha_pendente(message_id, ENVELOPE_IMAGEM, MessageContentType.IMAGEM)
    assert valores is not None
    session.add(MidiaRecebida(**valores))
    await session.commit()
    if criado_em is not None:
        await session.execute(
            update(MidiaRecebida)
            .where(MidiaRecebida.message_id == message_id)
            .values(criado_em=criado_em)
        )
        await session.commit()


async def test_marcar_armazenada_grava_chave_e_tamanho(session) -> None:
    message_id = await _mensagem_de_midia(session)
    await _gravar_pendente(session, message_id)

    await marcar(
        get_sessionmaker(),
        message_id,
        status=StatusDaMidia.ARMAZENADA,
        chave=f"midias/{message_id}",
        tamanho=1234,
    )

    linha = await ler_midia(session, message_id)
    assert linha is not None
    assert linha.status == StatusDaMidia.ARMAZENADA
    assert linha.chave_no_armazem == f"midias/{message_id}"
    assert linha.bytes == 1234
    assert linha.motivo is None


async def test_pendente_antiga_e_reenfileiravel_e_nova_nao(session) -> None:
    fabrica = get_sessionmaker()
    agora = datetime.now(UTC)
    antiga = await _mensagem_de_midia(session)
    nova = await _mensagem_de_midia(session)
    await _gravar_pendente(session, antiga, criado_em=agora - timedelta(minutes=20))
    await _gravar_pendente(session, nova, criado_em=agora - timedelta(minutes=1))

    pendentes = await pendentes_para_reenfileirar(
        fabrica,
        mais_velhas_que=timedelta(minutes=10),
        mais_novas_que=timedelta(days=7),
        limite=10,
    )

    assert pendentes == [antiga]


async def test_pendente_de_oito_dias_expira(session) -> None:
    fabrica = get_sessionmaker()
    message_id = await _mensagem_de_midia(session)
    await _gravar_pendente(session, message_id, criado_em=datetime.now(UTC) - timedelta(days=8))

    fechadas = await expirar_pendentes(fabrica, mais_velhas_que=timedelta(days=7))
    assert fechadas == 1

    linha = await ler_midia(session, message_id)
    assert linha is not None
    assert (linha.status, linha.motivo) == (StatusDaMidia.FALHOU, MotivoDaMidia.EXPIRADA)

    pendentes = await pendentes_para_reenfileirar(
        fabrica,
        mais_velhas_que=timedelta(minutes=10),
        mais_novas_que=timedelta(days=30),
        limite=10,
    )
    assert message_id not in pendentes


async def test_armazenada_nunca_e_reenfileirada(session) -> None:
    fabrica = get_sessionmaker()
    message_id = await _mensagem_de_midia(session)
    await _gravar_pendente(session, message_id, criado_em=datetime.now(UTC) - timedelta(minutes=20))
    await marcar(fabrica, message_id, status=StatusDaMidia.ARMAZENADA, chave="midias/x", tamanho=1)

    pendentes = await pendentes_para_reenfileirar(
        fabrica,
        mais_velhas_que=timedelta(minutes=10),
        mais_novas_que=timedelta(days=7),
        limite=10,
    )

    assert message_id not in pendentes

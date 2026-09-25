"""O modelo ve que recebeu midia e que nao a enxerga. TEC-132, D4."""

import uuid

from mobia.domain.context.montagem import _texto_da
from mobia.domain.messages.enums import MessageContentType, MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, encrypt


def _linha(tipo: MessageContentType, texto: str | None) -> Message:
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        role=MessageRole.LEAD,
        content_type=tipo,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
    )


def test_imagem_sem_legenda() -> None:
    assert _texto_da(_linha(MessageContentType.IMAGEM, None)) == (
        "[LEAD] (imagem recebida; o conteudo nao esta visivel para voce)"
    )


def test_imagem_com_legenda_leva_marcador_e_legenda() -> None:
    assert _texto_da(_linha(MessageContentType.IMAGEM, "esse aqui ta disponivel?")) == (
        "[LEAD] (imagem recebida; o conteudo nao esta visivel para voce) esse aqui ta disponivel?"
    )


def test_documento_sem_legenda() -> None:
    assert _texto_da(_linha(MessageContentType.DOCUMENTO, None)) == (
        "[LEAD] (documento recebido; o conteudo nao esta visivel para voce)"
    )


def test_audio_nao_muda() -> None:
    assert _texto_da(_linha(MessageContentType.AUDIO, None)) == "[LEAD] (audio, sem transcricao)"


def test_texto_nao_muda() -> None:
    assert _texto_da(_linha(MessageContentType.TEXTO, "oi")) == "[LEAD] oi"

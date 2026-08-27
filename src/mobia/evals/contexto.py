import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

CANAL = "eval"
CONVERSA = "eval-0000"


def mensagem_transiente(texto: str, *, papel: MessageRole) -> Message:
    """Uma linha de mensagem que nunca vai ao banco.

    O `id` e gerado aqui e nao pelo default da coluna porque o AAD da cifra
    depende dele: `encrypt(texto, aad_de(id, "text_body"))`. Cifrar antes de
    ter o id produziria um blob que `decrypt` devolve como None, e a montagem
    trocaria a fala do lead por "(mensagem sem texto)" sem levantar nada.
    """
    identificador = uuid.uuid4()
    entrada = papel is MessageRole.LEAD
    return Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"eval.{identificador.hex[:10]}",
        sender_external_id=CONVERSA if entrada else None,
        recipient_external_id=None if entrada else CONVERSA,
        conversation_key=CONVERSA,
        role=papel,
        direction=MessageDirection.INBOUND if entrada else MessageDirection.OUTBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSED,
        created_at=datetime.now(UTC),
    )


def contexto_do_historico(
    historico: Sequence[tuple[MessageRole, str]], *, sistema: str
) -> ContextoMontado:
    """Monta o contexto direto, sem resumo e sem estado de qualificacao.

    Sem resumo porque as conversas do corpus sao curtas -- a regeneracao so
    dispara a cada ~40 mensagens. Sem estado porque a extracao de campos
    (TEC-145) nao existe, entao nao ha o que preencher.
    """
    literais = [mensagem_transiente(texto, papel=papel) for papel, texto in historico]
    # Estimativa de tokens: len(sistema) + soma dos textos divido por 4.
    # Mesmo calculo que em montagem._estimar, adaptado para o caso sem resumo/estado.
    estimativa = len(sistema) + sum(len(texto) for _, texto in historico)
    tokens = estimativa // 4
    return ContextoMontado(
        sistema=sistema,
        resumo=None,
        literais=literais,
        estado=None,
        tokens=tokens,
        degradado=False,
    )

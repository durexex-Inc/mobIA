"""O turno espera a transcricao do audio da rajada. TEC-131, D1.

A pergunta e a de `process_message`, antes do claim: existe, na rajada que este
turno vai responder, um audio cuja transcricao ainda nao tem desfecho? Se
existe, o turno nao roda agora -- rodaria sem o que o lead falou, e o audio,
mais antigo, fecharia "agrupado" sem resposta nenhuma. Quem acorda o turno
depois e o proprio `transcrever_audio`, ao gravar o desfecho.

Sem estado proprio, como `domain/messages/rajada.py`: "esta esperando" nao e
gravado em lugar nenhum. E recomputado de `messages` e `midias_recebidas`.
"""

from datetime import UTC, datetime

from sqlalchemy import func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import MessageContentType, MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.midia.audio import PRAZO_DA_TRANSCRICAO
from mobia.domain.midia.models import MidiaRecebida


async def ha_audio_sem_transcricao(
    session: AsyncSession, message: Message, *, agora: datetime | None = None
) -> bool:
    """Ha audio do lead, nesta rajada, ainda sem desfecho de transcricao?

    **A rajada inclui a propria mensagem.** O turno do audio sozinho tambem
    espera: o debounce o poe na fila junto com a transcricao, e sem esta
    checagem ele quase sempre rodaria antes dela.

    **A fronteira de tras e a ultima fala do agente**, a mesma de
    `ha_fala_pendente_antes`: um audio anterior a ela ja foi respondido, bem ou
    mal, e esperar por ele nao muda a resposta de agora.

    **So audio com linha em `midias_recebidas`.** Envelope sem `id` nao gera
    linha (`linha_pendente`), e nenhum job vai transcreve-lo: esperar por ele
    seria esperar o prazo inteiro por nada.

    **E so dentro de `PRAZO_DA_TRANSCRICAO`**, contado do nascimento da linha de
    midia. Passado o prazo, o job se perdeu, e segurar o turno para sempre
    trocaria um audio sem transcricao por um lead sem resposta. `agora` e
    parametro para o teste fixar o relogio.
    """
    instante = agora or datetime.now(UTC)
    ultima_do_agente = (
        select(func.max(Message.created_at))
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.OUTBOUND,
        )
        .scalar_subquery()
    )
    pendente = await session.scalar(
        select(Message.id)
        .join(MidiaRecebida, MidiaRecebida.message_id == Message.id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.INBOUND,
            Message.content_type == MessageContentType.AUDIO,
            tuple_(Message.created_at, Message.id)
            <= tuple_(literal(message.created_at), literal(message.id)),
            or_(ultima_do_agente.is_(None), Message.created_at > ultima_do_agente),
            MidiaRecebida.status_da_transcricao.is_(None),
            MidiaRecebida.criado_em > instante - PRAZO_DA_TRANSCRICAO,
        )
        .limit(1)
    )
    return pendente is not None

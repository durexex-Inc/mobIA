"""Quem, na rajada, e o turno.

A RN-01.6 com a emenda E-01: a ultima mensagem do lead responde por todas. Este
modulo responde a unica pergunta que essa regra exige -- "chegou algo mais novo
deste lead?" -- e nao guarda estado nenhum. "A janela ainda esta aberta" nao e
gravado em lugar nenhum: e recomputado de `messages`, que e onde ja esta.
"""

from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message


async def superada_por_mais_nova(session: AsyncSession, message: Message) -> bool:
    """Chegou INBOUND mais nova deste lead depois de `message`?

    **O desempate por `id` nao e zelo, e obrigatorio.** Um envelope da Meta pode
    trazer varias mensagens, e `IngestionService._persist` as insere num `INSERT`
    so, numa transacao so. Como `created_at` e `server_default=func.now()` e o
    `now()` do Postgres e o instante da TRANSACAO, as irmas do mesmo envelope
    nascem com `created_at` identico. Comparar so por `created_at` faria cada uma
    se considerar superada pelas outras, e NENHUMA responderia -- o lead ficaria
    sem resposta, que e pior que as tres respostas que esta card veio corrigir.

    O par ordenado e o mesmo de `literais_apos` (`context/janela.py`), e pela
    mesma razao; casa com `ix_messages_timeline (channel, conversation_key,
    created_at DESC)`.

    O filtro de direcao existe porque a fala do proprio agente vai para esta
    tabela com o mesmo `conversation_key` da conversa. Sem ele, a resposta de um
    turno superaria a mensagem seguinte do lead e ela nunca seria respondida.
    """
    mais_nova = await session.scalar(
        select(Message.id)
        .where(
            Message.channel == message.channel,
            Message.conversation_key == message.conversation_key,
            Message.direction == MessageDirection.INBOUND,
            tuple_(Message.created_at, Message.id)
            > tuple_(literal(message.created_at), literal(message.id)),
        )
        .limit(1)
    )
    return mais_nova is not None

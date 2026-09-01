"""Grava, reverte e consulta o estado de opt-out de um lead.

As duas escritas recebem `session_factory` e commitam sozinhas, como
`marcar_bloqueada`: sao atos completos em si, e quem chama nao tem transacao
para compartilhar. As duas leituras recebem `session` porque rodam dentro da
sessao de quem pergunta -- a guarda na porta de saida ja tem uma aberta.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.optout.models import EVENTO_OPT_OUT, EVENTO_REATIVACAO, OptoutEvent


async def registrar_optout(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    message_id: uuid.UUID,
) -> None:
    """Acrescenta o evento de opt-out. Nunca atualiza nada."""
    async with session_factory() as session:
        session.add(
            OptoutEvent(
                id=uuid.uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                evento=EVENTO_OPT_OUT,
                message_id=message_id,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def reativar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    autor: str,
    motivo: str,
) -> None:
    """Acrescenta o evento de reativacao, com quem mandou e por que.

    `autor` e `motivo` nao tem default: a RN-14.3 exige justificativa, e um
    default vazio a tornaria decorativa.
    """
    async with session_factory() as session:
        session.add(
            OptoutEvent(
                id=uuid.uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                evento=EVENTO_REATIVACAO,
                autor=autor,
                motivo=motivo,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def esta_em_optout(session: AsyncSession, *, channel: str, conversation_key: str) -> bool:
    """O ultimo evento deste lead e um opt-out.

    Sem evento nenhum, nao esta -- o estado default e "pode receber".
    """
    ultimo = (
        await session.execute(
            select(OptoutEvent.evento)
            .where(
                OptoutEvent.channel == channel,
                OptoutEvent.conversation_key == conversation_key,
            )
            .order_by(OptoutEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ultimo == EVENTO_OPT_OUT


async def esta_em_optout_por_mensagem(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """A mesma pergunta, para quem so tem o id da mensagem.

    E o caso da guarda em `GuardedOutbound.send`, cuja assinatura nao carrega o
    par do lead. Mensagem inexistente devolve False: se nao ha lead, nao ha
    opt-out a respeitar, e recusar o envio por isso esconderia o defeito real.
    """
    lead = (
        await session.execute(
            select(Message.channel, Message.conversation_key).where(Message.id == message_id)
        )
    ).one_or_none()
    if lead is None:
        return False
    return await esta_em_optout(
        session, channel=lead.channel, conversation_key=lead.conversation_key
    )

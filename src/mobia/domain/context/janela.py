import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.repositorio import ResumoDaConversa
from mobia.domain.messages.models import Message


@dataclass(frozen=True)
class Marca:
    """Ate onde o resumo cobre.

    Par ordenavel em vez de contagem: contagem quebra quando uma linha e apagada
    ou quando duas mensagens chegam no mesmo instante.
    """

    created_at: datetime
    message_id: uuid.UUID


def marca_de(resumo: ResumoDaConversa | None) -> Marca | None:
    if resumo is None:
        return None
    return Marca(
        created_at=resumo.watermark_created_at,
        message_id=resumo.watermark_message_id,
    )


async def literais_apos(
    session: AsyncSession,
    channel: str,
    conversation_key: str,
    marca: Marca | None,
) -> list[Message]:
    """Tudo o que ainda nao foi dobrado no resumo, em ordem cronologica.

    A comparacao e de tupla e nao de timestamp sozinho: duas mensagens no mesmo
    `created_at` fariam a janela pular uma ou repetir a outra. O par casa com
    `ix_messages_timeline (channel, conversation_key, created_at DESC)`.
    """
    condicoes = [
        Message.channel == channel,
        Message.conversation_key == conversation_key,
    ]
    if marca is not None:
        condicoes.append(
            tuple_(Message.created_at, Message.id)
            > tuple_(literal(marca.created_at), literal(marca.message_id))
        )

    resultado = await session.scalars(
        select(Message).where(*condicoes).order_by(Message.created_at, Message.id)
    )
    return list(resultado)


def deve_regenerar(quantidade: int, gatilho: int) -> bool:
    return quantidade >= gatilho


def dividir(literais: list[Message], minimas: int) -> tuple[list[Message], list[Message]]:
    """Separa o que vira resumo do que fica literal.

    O piso manda: por mais que se acumule, `minimas` mensagens sempre ficam na
    integra. E o que faz "as 20 mais recentes na integra" valer no turno logo
    apos uma regeneracao, e nao so no turno que a disparou.
    """
    if len(literais) <= minimas:
        return [], literais
    corte = len(literais) - minimas
    return literais[:corte], literais[corte:]

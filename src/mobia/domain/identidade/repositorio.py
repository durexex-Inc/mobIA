"""Gravar e ler o vinculo sessao web -> telefone. TEC-129, D3."""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.identidade.models import VinculoDeSessao


async def vincular_sessao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    telefone: str,
    message_id: uuid.UUID,
) -> bool:
    """Grava o vinculo se a sessao ainda nao tem um. Devolve se gravou.

    `ON CONFLICT DO NOTHING` e nao upsert: o primeiro telefone vale. Trocar o
    numero de uma sessao ja vinculada moveria o que ela disse de um lead para
    outro no meio da conversa, e o segundo numero tem menos chance de ser o da
    pessoa que o primeiro -- "o meu e X; anota tambem o do meu marido, Y".
    """
    async with session_factory() as session:
        resultado = cast(
            CursorResult[Any],
            await session.execute(
                pg_insert(VinculoDeSessao)
                .values(
                    channel=channel,
                    conversation_key=conversation_key,
                    telefone=telefone,
                    message_id=message_id,
                )
                .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
            ),
        )
        await session.commit()
    return resultado.rowcount == 1


async def sessoes_vinculadas(session: AsyncSession, telefone: str) -> list[tuple[str, str]]:
    """Os pares das sessoes que apontam para este telefone, do mais antigo ao mais novo."""
    linhas = await session.execute(
        select(VinculoDeSessao.channel, VinculoDeSessao.conversation_key)
        .where(VinculoDeSessao.telefone == telefone)
        .order_by(VinculoDeSessao.criado_em, VinculoDeSessao.conversation_key)
    )
    return [(channel, chave) for channel, chave in linhas.all()]

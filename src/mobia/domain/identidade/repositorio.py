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


# Teto de sessoes vinculadas que um turno do WhatsApp usa -- na absorcao e na
# janela de literais (revisao final da TEC-129, D4). O vinculo nao e
# verificado (D1): qualquer um que saiba o numero de outra pessoa abre sessoes
# no site, digita o numero e vincula quantas quiser. Sem teto, cada uma
# plantaria criterios e texto no contexto do WhatsApp dela, e o custo do turno
# (uma consulta, uma janela maior) cresceria com o abuso. Tres cobre o uso
# legitimo -- celular, notebook, o computador do trabalho -- e sao as MAIS
# RECENTES porque a sessao que continua viva e a que importa.
MAXIMO_DE_SESSOES_VINCULADAS = 3


async def sessoes_vinculadas(
    session: AsyncSession, telefone: str, *, limite: int | None = None
) -> list[tuple[str, str]]:
    """Os pares das sessoes que apontam para este telefone, do mais antigo ao mais novo.

    Com `limite`, so as `limite` vinculadas por ultimo (`criado_em`) -- e a
    ordem devolvida continua cronologica.
    """
    recentes = (
        select(VinculoDeSessao.channel, VinculoDeSessao.conversation_key, VinculoDeSessao.criado_em)
        .where(VinculoDeSessao.telefone == telefone)
        .order_by(VinculoDeSessao.criado_em.desc(), VinculoDeSessao.conversation_key.desc())
        .limit(limite)
        .subquery()
    )
    linhas = await session.execute(
        select(recentes.c.channel, recentes.c.conversation_key).order_by(
            recentes.c.criado_em, recentes.c.conversation_key
        )
    )
    return [(channel, chave) for channel, chave in linhas.all()]

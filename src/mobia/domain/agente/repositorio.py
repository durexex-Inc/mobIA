from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.models import ConversationIntent
from mobia.domain.agente.schemas import Intencao


@dataclass(frozen=True)
class IntencaoDaConversa:
    intencao: Intencao
    confianca: Decimal
    modelo: str


async def ler_intencao(
    session: AsyncSession, channel: str, conversation_key: str
) -> IntencaoDaConversa | None:
    linha = await session.get(ConversationIntent, (channel, conversation_key))
    if linha is None:
        return None
    return IntencaoDaConversa(
        intencao=Intencao(linha.intencao),
        confianca=linha.confianca,
        modelo=linha.modelo,
    )


async def gravar_intencao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    confianca: Decimal,
    modelo: str,
) -> None:
    """Upsert. **Nao commita** -- o chamador e dono da transacao.

    Mesma fronteira que `gravar_resumo` da TEC-127 passou a respeitar depois de
    uma review: quem abre a sessao e quem a finaliza.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": str(intencao),
        "confianca": confianca,
        "modelo": modelo,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationIntent).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                chave: statement.excluded[chave]
                for chave in ("intencao", "confianca", "modelo", "updated_at")
            },
        )
    )

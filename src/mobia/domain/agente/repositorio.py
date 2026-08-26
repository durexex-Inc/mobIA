from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.desambiguacao import intencao_efetiva
from mobia.domain.agente.models import ConversationIntent
from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao


@dataclass(frozen=True)
class IntencaoDaConversa:
    intencao: Intencao
    confianca: Decimal
    modelo: str
    desambiguado_em: datetime | None

    @property
    def efetiva(self) -> Intencao:
        """A intencao que se pode usar para rotear. **Leia por aqui.**

        `intencao` e o palpite cru, que abaixo do limiar nao sustenta decisao
        nenhuma. Ver `intencao_efetiva`.
        """
        return intencao_efetiva(self.intencao, self.confianca)


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
        desambiguado_em=linha.desambiguado_em,
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
        # Linha nova comeca sem episodio em aberto: a primeira ambiguidade de
        # uma conversa tem de poder perguntar.
        "desambiguado_em": None,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationIntent).values(valores)

    atualizacoes: dict[str, Any] = {
        chave: statement.excluded[chave]
        for chave in ("intencao", "confianca", "modelo", "updated_at")
    }
    if confianca >= LIMIAR_DE_DESAMBIGUACAO:
        # Classificacao confiante encerra o episodio de ambiguidade: o proximo
        # trecho vago da conversa tem direito a uma pergunta nova.
        atualizacoes["desambiguado_em"] = None
    # Abaixo do limiar o marcador **nao** entra no set_: a ambiguidade e a
    # mesma, e a pergunta dela ja foi gasta.

    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_=atualizacoes,
        )
    )


async def marcar_desambiguacao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    quando: datetime | None = None,
) -> None:
    """Registra que a pergunta de desambiguacao ja foi feita. **Nao commita.**

    Chamada **depois** da entrega confirmada, nunca antes: o marcador afirma
    "eu ja perguntei", e isso so e verdade se a pergunta chegou. Escrito antes,
    um 5xx da Meta queimaria a unica chance de desambiguar -- o sweeper
    reprocessa, encontra o marcador, e o lead fica em INDEFINIDA sem ninguem
    ter perguntado nada.

    A linha sempre existe neste ponto: `gravar_intencao` rodou e commitou mais
    cedo no mesmo turno.
    """
    await session.execute(
        update(ConversationIntent)
        .where(
            ConversationIntent.channel == channel,
            ConversationIntent.conversation_key == conversation_key,
        )
        .values(desambiguado_em=quando or datetime.now(UTC))
    )

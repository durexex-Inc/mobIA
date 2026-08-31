"""A marca de bloqueio na linha da mensagem (TEC-236).

Mora fora de `MessageRecorder` de proposito. O contrato daquele e explicito --
*"nenhum metodo propaga excecao. Quem chama esta no meio de responder ao
lead"* -- e ele esta certo para telemetria: perder uma linha de custo nao pode
derrubar a resposta.

**Aqui a escolha e a oposta, e a inversao e o ponto.** Se a marca falhar em
silencio, a fala bloqueada continua elegivel para o contexto do proximo turno e
para o resumo permanente. O desfecho seguro nao e "responda assim mesmo": e
falhar o turno, deixar a linha em FAILED e o sweeper retentar -- pagando de
novo a moderacao, que e barata perto de vazar a fala para dentro do prompt.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message


async def marcar_bloqueada(
    session_factory: async_sessionmaker[AsyncSession],
    message_id: UUID,
) -> None:
    """Carimba `bloqueada_em` na linha, e propaga se nao conseguir.

    `UPDATE` direto e nao leitura-e-grava: a linha ja existe (a ingestao a
    gravou antes de o worker existir) e nao ha nada nela para ler antes de
    decidir. Uma segunda passada do sweeper sobre a mesma mensagem reescreve o
    carimbo com a hora nova, e isso e inofensivo -- o que importa e a coluna
    deixar de ser NULL, nao o instante exato.
    """
    async with session_factory() as session:
        await session.execute(
            update(Message).where(Message.id == message_id).values(bloqueada_em=datetime.now(UTC))
        )
        await session.commit()

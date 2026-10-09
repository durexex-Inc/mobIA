"""O pedido de interesse num imovel, feito pelo portal publico. TEC-389.

Guarda so o que o handoff (TEC-174) nao guarda: QUAL imovel o cliente pediu.
O handoff e por (channel, conversation_key) -- um por lead aberto, nao um por
imovel -- entao um segundo pedido, de um imovel diferente, enquanto o
primeiro handoff ainda esta aberto nao deixaria rastro nenhum do segundo
imovel se este registro nao existisse (D2 do desenho).
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, DateTime, ForeignKey, Index, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.catalogo.models import Imovel
from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_do_email_de_interesse(solicitacao_id: uuid.UUID) -> str:
    """Amarra o e-mail cifrado a linha do pedido (TEC-404, D3). Molde de
    `handoff/models.py::aad_do_resumo_de_handoff`: a identidade da linha e um
    UUID, e `aad_de` basta."""
    return aad_de(solicitacao_id, "email_interesse")


class SolicitacaoDeInteresse(Base):
    __tablename__ = "solicitacoes_de_interesse"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    imovel_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Imovel.id), nullable=False
    )

    # O par que identifica o lead do portal -- mesmo par que o handoff grava.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    nome: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # TEC-404, D3. Cifrado; nulo nos pedidos anteriores a 0071 (sem backfill) e
    # em quem nao informou. Zerado pela anonimizacao junto com `nome`.
    email_cifrado: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # CA-04 (duplicidade): o mesmo lead pedindo o mesmo imovel de novo nao
        # vira uma segunda linha -- `registrar_interesse` depende deste indice
        # para o `ON CONFLICT DO NOTHING` ser idempotente.
        Index(
            "uq_solicitacoes_de_interesse_lead_imovel",
            "channel",
            "conversation_key",
            "imovel_id",
            unique=True,
        ),
    )


async def registrar_interesse(
    session: AsyncSession,
    *,
    imovel_id: uuid.UUID,
    channel: str,
    conversation_key: str,
    nome: str | None,
    agora: datetime,
) -> bool:
    """Grava o pedido. Nao commita -- quem chama decide a transacao.

    Devolve se a linha foi de fato inserida. `False` so acontece quando o
    MESMO lead ja pediu o MESMO imovel antes (CA-04) -- e nao e erro: quem
    chama devolve a mesma resposta de sucesso de um pedido novo (L3 do
    desenho -- o portal nunca revela "voce ja tinha pedido isso").
    """
    resultado = cast(
        CursorResult[Any],
        await session.execute(
            pg_insert(SolicitacaoDeInteresse)
            .values(
                id=uuid.uuid4(),
                imovel_id=imovel_id,
                channel=channel,
                conversation_key=conversation_key,
                nome=nome,
                criado_em=agora,
            )
            .on_conflict_do_nothing(index_elements=["channel", "conversation_key", "imovel_id"])
        ),
    )
    return resultado.rowcount == 1

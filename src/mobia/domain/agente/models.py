from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class ConversationIntent(Base):
    """Intencao corrente da conversa, com a confianca que a produziu.

    Fica em tabela propria e nao em `lead_qualification`, apesar de aquela ja
    ter uma coluna `intencao`: a TEC-127 registrou que a dona de
    lead_qualification e a TEC-145, e confianca e artefato do classificador,
    nao criterio de qualificacao -- nao faz sentido ao lado de quartos e vagas.
    """

    __tablename__ = "conversation_intent"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    intencao: Mapped[str] = mapped_column(String(20), nullable=False)

    # Autoavaliacao do modelo, nao probabilidade calibrada. Ver o spec: os
    # limiares de 0,8 e 0,6 sao provisorios ate a TEC-210 medir contra as 50
    # conversas anotadas.
    confianca: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    modelo: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

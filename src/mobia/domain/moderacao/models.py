"""O registro de recusa da moderacao, append-only (TEC-142).

Uma linha por bloqueio, nas duas direcoes e em todas as categorias. Quem
distingue discriminacao das demais e a coluna `categoria`, nao a existencia da
linha: auditar so um eixo deixaria ameaca e assedio sem registro consultavel,
e a consulta por discriminacao custa um WHERE de qualquer jeito.

**Nunca o texto julgado.** O corpo ja esta cifrado em `messages`, e a RN-04.5
pede o registro do evento, nao do conteudo. Copiar o texto criaria em claro
exatamente aquilo que o quarto criterio de aceite da card manda nao existir --
o mesmo argumento que `optout_events` faz para a RN-14.2.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification` e
    # `optout_events`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    direcao: Mapped[str] = mapped_column(String(8), nullable=False)
    categoria: Mapped[str] = mapped_column(String(32), nullable=False)

    # Referencia, nunca copia -- e SEM FK, pelo motivo da migration 0010: a
    # retencao de `messages` (12 meses, RNF-22) e mais curta que a do registro
    # de conformidade, e uma FK apagaria evidencia por cascata. Na direcao
    # SAIDA aponta para a mensagem de ENTRADA que originou o turno: e a ancora
    # que existe, e o texto barrado nao e persistido em lugar nenhum.
    message_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_moderation_events_lead",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )

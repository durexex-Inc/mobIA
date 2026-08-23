import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class OutboundDispatch(Base):
    """Reserva do direito de emitir um efeito externo para uma mensagem.

    A UNIQUE (message_id, kind) e o que torna o reprocessamento seguro: a segunda
    tentativa colide e vira no-op.
    """

    __tablename__ = "outbound_dispatches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("message_id", "kind", name="uq_outbound_message_kind"),)

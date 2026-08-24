import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mobia.domain.messages.status import MessageStatus


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MessageStatus.RECEIVED
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contexto do envelope da Meta -- `change.value` sem o array `messages`.
    # Coluna reservada pelo TEC-217; nada escreve nela ainda.
    envelope_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Instante da reivindicacao, para o lease de exclusao mutua entre workers.
    # Coluna reservada pelo TEC-218; nada escreve nela ainda.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_messages_status_received_at", "status", "received_at"),
        # Composta com `channel` de proposito: o widget web (TEC-124) tem espaco
        # de ids proprio e nao deve colidir com o wamid da Meta. O indice desta
        # constraint tambem serve as buscas que o indice simples servia.
        UniqueConstraint(
            "channel",
            "provider_message_id",
            name="uq_messages_channel_provider_message_id",
        ),
    )

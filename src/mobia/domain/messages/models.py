import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Id externo do lead, invariante a direcao: e por ele que a conversa e
    # agrupada, porque sender e recipient se invertem entre entrada e saida.
    # `conversations` de verdade e TEC-129/TEC-130.
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)

    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Cifrados com AES-GCM, AAD `{id}:{coluna}`. A cifra e explicita nos dois
    # escritores em vez de um TypeDecorator porque o bind do decorator nao
    # conhece o id da linha, e sem o id no AAD o ciphertext pode ser movido de
    # um lead para outro.
    text_body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # NULL significa "nao participa do pipeline de ingestao" -- e o que a linha
    # de saida grava. Ver a docstring do sweeper.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
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
        Index("ix_messages_status_created_at", "status", "created_at"),
        # A consulta que TEC-127 faz a cada turno: as N mensagens mais recentes
        # de uma conversa, nas duas direcoes.
        Index(
            "ix_messages_timeline",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
        UniqueConstraint(
            "channel",
            "provider_message_id",
            name="uq_messages_channel_provider_message_id",
        ),
    )


class MessageTelemetry(Base):
    """Tokens, custo e latencia de uma resposta do agente.

    Fica ao lado e nao dentro de `messages` porque as duas tabelas respondem a
    perguntas diferentes: TEC-127 le a linha do tempo e nao quer saber de custo;
    o painel de custo soma dolares e nao deve tocar em conteudo de lead.
    """

    __tablename__ = "message_telemetry"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    subagent: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)

    # NULL = modelo sem preco cadastrado. Gravar 0.00 somaria silenciosamente no
    # painel e faria o custo parecer menor do que foi; NULL aparece como lacuna.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

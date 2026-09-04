"""A trilha dos follow-ups que a cadencia disparou.

TEC-183. Append-only: uma linha por tentativa vencida e registrada. Nao ha
estado PENDENTE nem CANCELADO -- a cadencia e derivada, e o que nao aconteceu
nao tem linha. Ver a emenda a RN-13.4 no SRS.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class FollowUp(Base):
    __tablename__ = "followups"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # 1-based. Zero seria indistinguivel de "nenhuma disparou", que e o que a
    # ausencia de linha ja significa -- por isso o CHECK.
    tentativa_numero: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # A temperatura NO MOMENTO do disparo, e nao a de agora. Redundante com
    # `lead_qualification` de proposito: e ela que explica por que foram N
    # tentativas, e a coluna viva ja tera mudado quando alguem ler a trilha.
    temperatura: Mapped[str] = mapped_column(String(8), nullable=False)

    # A ultima fala do lead que gerou este disparo -- o `created_at` daquela
    # mensagem, exato e nao aproximado. E contra a igualdade nesta coluna que
    # se conta ate onde a cadencia ja foi; quando o lead responde, a ancora
    # muda e a contagem zera sozinha.
    ancora_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # `ancora_em + CADENCIA[temperatura][n-1]`. Calculado, nao agendado -- e
    # **nao** esta ajustado a janela de 9h-20h, ao contrario do que o modelo de
    # dados do SRS diz sobre `agendado_para`. Isso e a TEC-185.
    devido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint("tentativa_numero > 0", name="ck_followups_tentativa"),
        # Duas varreduras concorrentes veriam o mesmo candidato devido e ambas
        # inseririam. Nao da para usar FOR UPDATE SKIP LOCKED sobre a agregacao
        # que produz os candidatos, entao a exclusao mora aqui.
        UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_followups_tentativa_por_ancora",
        ),
        Index("ix_followups_lead", "channel", "conversation_key", "ancora_em"),
    )

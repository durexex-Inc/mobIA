"""O registro de opt-out, append-only.

Uma linha por evento, e o estado atual de um lead e o ULTIMO evento por
`(channel, conversation_key)`. Nao e coluna booleana de proposito: com booleano
a reativacao APAGA a evidencia do opt-out, que e o contrario do que a RN-14.2
pede -- ela exige o registro como prova de conformidade.

A linha referencia `message_id` e NAO copia o texto que disparou. O corpo ja
esta cifrado em `messages`; copia-lo criaria uma segunda copia em claro da fala
do lead. A RN-14.2 pede "o conteudo original que o disparou", e a referencia
**e** o conteudo original -- na versao que nao duplica dado pessoal.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base

EVENTO_OPT_OUT = "OPT_OUT"
EVENTO_REATIVACAO = "REATIVACAO"


class OptoutEvent(Base):
    __tablename__ = "optout_events"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    # `conversation_key` e o id externo do lead, invariante a direcao.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    evento: Mapped[str] = mapped_column(String(16), nullable=False)

    # Nulo na reativacao: ela nao vem de mensagem nenhuma.
    message_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Nulos no opt-out: o ato e do lead, nao de um humano nosso.
    autor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # A consulta quente e "qual o ultimo evento deste lead?", uma vez por
        # envio. DESC no indice para o LIMIT 1 nao ordenar em memoria. Mesmo
        # formato do `ix_messages_timeline`.
        Index(
            "ix_optout_events_lead",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )

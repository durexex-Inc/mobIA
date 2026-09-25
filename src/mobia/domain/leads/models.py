"""O apelido opaco do lead. TEC-195, D2 do desenho.

**O identificador do lead e o dado pessoal dele**, e essa e a razao desta
tabela: no WhatsApp a `conversation_key` E o telefone. Esta linha da a API do
dashboard outra coisa para devolver no lugar do par -- um UUID estavel, sem
atributo proprio, que nao diz nada sobre quem o lead e.

**Reversivel de proposito**, e e o que a separa do `lead_ref` da trilha
(`auditoria/referencia.py`): aquele e HMAC porque a trilha nunca precisa voltar
ao par; este precisa, porque `POST /leads/{leadId}/revelar` tem de ler o
telefone para devolve-lo.

O lead continua sendo o par `(channel, conversation_key)`, como em `handoffs`,
`optout_events` e `agendamentos`: nao existe tabela de lead, e esta nao e uma.
Ver a docstring da migration 0056.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class ReferenciaDeLead(Base):
    __tablename__ = "referencias_de_lead"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("channel", "conversation_key", name="uq_referencias_de_lead_conversa"),
    )

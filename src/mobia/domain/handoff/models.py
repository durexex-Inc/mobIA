"""O handoff: a tarefa que o lead pronto vira para o corretor.

TEC-174. Ver `alembic/versions/0023_handoffs.py` para o porque do par como
identidade e do UNIQUE parcial. A FK de `corretor_id` para `corretores.id`
entrou na TEC-196, em `alembic/versions/0024_corretores.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # O gatilho que CRIOU o handoff. Os que chegarem depois vao para
    # `gatilhos_adicionais` -- a etiqueta nao muda, porque e por ela que a fila
    # do dashboard e filtrada (TEC-192) e etiqueta movel embaralha filtro salvo.
    gatilho: Mapped[str] = mapped_column(String(32), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(32), nullable=False)

    # Escala para ALTA e nunca desce -- emenda E-01 da RN-16.1. Sem isso, um
    # pedido explicito de humano sobre um handoff aberto ficaria NORMAL, o que
    # contraria a RN-04.6.
    prioridade: Mapped[str] = mapped_column(String(8), nullable=False)

    # Nasce e permanece PENDENTE nesta card. ACEITO/ESCALADO vem da TEC-178 e
    # CONCLUIDO da TEC-179 -- o enum nasce completo porque mudar valor de enum
    # depois custa migration, e o `IN` do CHECK e o unico lugar a mexer.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # FK para `corretores.id` desde a TEC-196 (ver a migration 0024). Continua
    # NULAVEL, mas agora por outra razao -- nao falta mais tabela alvo, falta
    # quem aloque, e alocar e a TEC-166.
    corretor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("corretores.id"), nullable=True
    )

    gatilhos_adicionais: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("prioridade IN ('ALTA', 'NORMAL')", name="ck_handoffs_prioridade"),
        CheckConstraint(
            "status IN ('PENDENTE', 'ACEITO', 'ESCALADO', 'CONCLUIDO')",
            name="ck_handoffs_status",
        ),
        Index(
            "uq_handoffs_conversa_pendente",
            "channel",
            "conversation_key",
            unique=True,
            postgresql_where=text("status = 'PENDENTE'"),
        ),
    )

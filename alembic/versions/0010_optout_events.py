"""registro append-only de opt-out e reativacao

TEC-182. Append-only de proposito: o estado atual e o ultimo evento, e a
reativacao acrescenta em vez de sobrescrever. Uma coluna booleana apagaria a
evidencia do opt-out no momento da reativacao, que e exatamente o que um
registro de conformidade nao pode fazer.

Sem FK para `messages`: a retencao de mensagens (RNF-22, 12 meses) e mais curta
que a do registro de conformidade, e uma FK faria a limpeza de mensagens
apagar evidencia de LGPD por cascata ou travar por restricao. O id fica como
referencia solta, e quem ler resolve o que existir.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "optout_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("evento", sa.String(16), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("autor", sa.String(120), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_optout_events_lead",
        "optout_events",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_optout_events_lead", table_name="optout_events")
    op.drop_table("optout_events")

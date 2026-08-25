"""intencao corrente da conversa

TEC-134. Chaveada por (channel, conversation_key) como conversation_summaries,
ja que `conversations` de primeira classe continua sendo TEC-129/TEC-130.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_intent",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("intencao", sa.String(20), nullable=False),
        sa.Column("confianca", sa.Numeric(3, 2), nullable=False),
        sa.Column("modelo", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("conversation_intent")

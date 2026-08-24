"""cria a tabela messages

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=False),
        sa.Column("sender_external_id", sa.String(64), nullable=False),
        sa.Column("recipient_external_id", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_messages_status_received_at", "messages", ["status", "received_at"])
    op.create_index("ix_messages_provider_message_id", "messages", ["provider_message_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_provider_message_id", table_name="messages")
    op.drop_index("ix_messages_status_received_at", table_name="messages")
    op.drop_table("messages")

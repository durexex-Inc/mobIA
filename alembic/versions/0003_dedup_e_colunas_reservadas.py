"""dedup por provider_message_id e colunas reservadas

Uma migration para tres historias, porque as tres mexem na mesma tabela:

* TEC-125 -- UNIQUE (channel, provider_message_id), com comportamento nesta entrega.
* TEC-217 -- coluna `envelope_context`, reservada, ainda sem escritor.
* TEC-218 -- coluna `claimed_at`, reservada, ainda sem escritor.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A UNIQUE composta cria seu proprio indice, que cobre as buscas que o
    # indice simples cobria -- manter os dois seria indice duplicado.
    op.drop_index("ix_messages_provider_message_id", table_name="messages")
    op.create_unique_constraint(
        "uq_messages_channel_provider_message_id",
        "messages",
        ["channel", "provider_message_id"],
    )

    op.add_column("messages", sa.Column("envelope_context", postgresql.JSONB(), nullable=True))
    op.add_column(
        "messages", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("messages", "claimed_at")
    op.drop_column("messages", "envelope_context")
    op.drop_constraint(
        "uq_messages_channel_provider_message_id", "messages", type_="unique"
    )
    op.create_index(
        "ix_messages_provider_message_id", "messages", ["provider_message_id"]
    )

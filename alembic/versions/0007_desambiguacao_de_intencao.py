"""marcador de desambiguacao na intencao da conversa

TEC-135. NULL = nenhum episodio de ambiguidade em aberto.

Nullable e sem backfill de proposito: uma conversa que ja existe e que nunca
desambiguou tem exatamente a semantica de NULL, entao o default correto para
todas as linhas antigas ja e o que o add_column deixa.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_intent",
        sa.Column("desambiguado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_intent", "desambiguado_em")

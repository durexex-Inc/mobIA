"""os campos que o lead se negou a informar

TEC-148, RN-05.7. Coluna nulavel e sem backfill: `NULL` significa "linha
anterior a esta card, ninguem registrava recusa", e isso e informacao que um
backfill para `{}` apagaria. Ver o comentario da coluna no modelo.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("campos_recusados", postgresql.ARRAY(sa.String(32)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "campos_recusados")

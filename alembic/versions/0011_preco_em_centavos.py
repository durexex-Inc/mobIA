"""preco em centavos, como inteiro

TEC-146. `numeric(12,2)` guardava reais e deixava a ordem de grandeza a cargo
do modelo. Centavos como inteiro tiram a virgula da conta e fecham a RN-05.6.

BIGINT e nao INTEGER: o teto da banda de compra e R$ 1 bilhao, ou 10^11
centavos. `int32` para em ~2,1x10^9 -- R$ 21 milhoes -- e truncaria a faixa
que ja existe.

O backfill e lossless por construcao, nao por sorte: `numeric(12,2) * 100` e
inteiro exato, entao o ROUND nunca tem o que arredondar.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_min_centavos", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_max_centavos", sa.BigInteger(), nullable=True),
    )
    op.execute(
        "UPDATE lead_qualification SET "
        "faixa_preco_min_centavos = ROUND(faixa_preco_min * 100)::bigint, "
        "faixa_preco_max_centavos = ROUND(faixa_preco_max * 100)::bigint"
    )
    op.drop_column("lead_qualification", "faixa_preco_min")
    op.drop_column("lead_qualification", "faixa_preco_max")


def downgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_min", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("faixa_preco_max", sa.Numeric(12, 2), nullable=True),
    )
    # Cabe para todo valor dentro da banda da D3; fora dela nada e gravavel.
    op.execute(
        "UPDATE lead_qualification SET "
        "faixa_preco_min = faixa_preco_min_centavos / 100.0, "
        "faixa_preco_max = faixa_preco_max_centavos / 100.0"
    )
    op.drop_column("lead_qualification", "faixa_preco_min_centavos")
    op.drop_column("lead_qualification", "faixa_preco_max_centavos")

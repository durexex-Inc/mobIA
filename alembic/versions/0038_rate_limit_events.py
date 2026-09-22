"""registro append-only de bloqueio por rate limit

TEC-205, RNF-16. Uma linha por chave por janela -- a unicidade e garantida
por chave em Redis e nao por UNIQUE, porque o banco nao tem como saber onde
uma janela deslizante comeca.

`limite` fica na linha porque o limite e configuravel: sem ele ao lado, o
volume nao diz se houve abuso depois que alguem mudar a configuracao.

Sem FK para `messages`, pelo mesmo motivo da 0010 e da 0020: a retencao de
mensagens (12 meses, RNF-22) e mais curta que a do registro de conformidade.
`message_id` e nulo no escopo `ip`, onde o bloqueio antecede a rota e nao ha
mensagem nenhuma.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("escopo", sa.String(8), nullable=False),
        sa.Column("chave", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("limite", sa.Integer(), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_rate_limit_events_chave",
        "rate_limit_events",
        ["escopo", "chave", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_events_chave", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")

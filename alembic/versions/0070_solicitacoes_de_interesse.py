"""solicitacao de interesse pelo portal publico existe

TEC-389. `solicitacoes_de_interesse` guarda so o que o handoff (0023) nao
guarda: QUAL imovel o cliente pediu. `imovel_id` tem FK para `imoveis.id`;
`channel`/`conversation_key` sao o mesmo par que `handoffs` usa para
identificar o lead. O indice unico por (channel, conversation_key,
imovel_id) e o que torna `registrar_interesse` idempotente -- o mesmo
telefone pedindo o mesmo imovel de novo nao vira uma segunda linha (CA-04).

Revision ID: 0070
Revises: 0069
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "solicitacoes_de_interesse",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "imovel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imoveis.id"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("nome", sa.String(160), nullable=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_solicitacoes_de_interesse_lead_imovel",
        "solicitacoes_de_interesse",
        ["channel", "conversation_key", "imovel_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_solicitacoes_de_interesse_lead_imovel", table_name="solicitacoes_de_interesse"
    )
    op.drop_table("solicitacoes_de_interesse")

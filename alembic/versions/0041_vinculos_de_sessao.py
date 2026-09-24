"""a sessao web vinculada ao telefone que o visitante digitou

TEC-129, D3. Tabela nova e vazia: nao ha backfill porque nenhum telefone foi
extraido de fala nenhuma antes desta card, e reprocessar o historico web
vincularia sessoes a numeros sem que a pessoa estivesse ali para isso.

O indice em `telefone` e o caminho da unica leitura: o turno do WhatsApp
perguntando quais sessoes apontam para o seu numero.

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vinculos_de_sessao",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("telefone", sa.String(16), nullable=False),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_vinculos_de_sessao_telefone", "vinculos_de_sessao", ["telefone"])


def downgrade() -> None:
    op.drop_index("ix_vinculos_de_sessao_telefone", table_name="vinculos_de_sessao")
    op.drop_table("vinculos_de_sessao")

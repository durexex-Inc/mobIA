"""resumo da conversa e estado de qualificacao

TEC-127. Duas tabelas, ambas chaveadas por (channel, conversation_key) -- a
mesma chave denormalizada da TEC-126, ja que `conversations` de primeira classe
continua sendo TEC-129/TEC-130.

`conversation_summaries.resumo` e bytea cifrado; `lead_qualification` fica em
claro de proposito, porque TEC-147, TEC-150 e TEC-158 filtram por esses campos
em SQL.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("resumo", sa.LargeBinary(), nullable=False),
        sa.Column("watermark_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("watermark_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mensagens_cobertas", sa.Integer(), nullable=False),
        sa.Column("modelo", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "lead_qualification",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("intencao", sa.String(16), nullable=True),
        sa.Column("faixa_preco_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("faixa_preco_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("regiao", sa.String(120), nullable=True),
        sa.Column("tipo_imovel", sa.String(32), nullable=True),
        sa.Column("quartos", sa.Integer(), nullable=True),
        sa.Column("vagas", sa.Integer(), nullable=True),
        sa.Column("urgencia", sa.String(32), nullable=True),
        sa.Column("forma_pagamento", sa.String(32), nullable=True),
        sa.Column("tem_imovel_para_vender", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("lead_qualification")
    op.drop_table("conversation_summaries")

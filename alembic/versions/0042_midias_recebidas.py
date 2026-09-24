"""a linha por midia recebida, com o ponteiro e o estado do download

TEC-132, D2. Uma linha por mensagem IMAGEM ou DOCUMENTO -- so essas duas tem
o que baixar (D3); audio e a TEC-131, e video/figurinha/localizacao continuam
DESCONHECIDO, sem download.

Sem CHECK em `status`/`motivo`: ver a docstring de `MidiaRecebida`
(`domain/midia/models.py`) para o porque -- a 0037 criou CHECK para o
vocabulario de `messages` por um risco especifico (comparacao de literal cru
em SQL) que nao existe aqui, e nenhuma tabela nova depois dela repetiu o
CHECK so por ter vocabulario.

O indice parcial e o unico caminho de leitura por status: a varredura
periodica (`pendentes_para_reenfileirar`, `expirar_pendentes`) le so
PENDENTE, e as tres outras linhas terminais nunca entram nesse WHERE.

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "midias_recebidas",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("media_id_da_meta", sa.String(128), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("chave_no_armazem", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("motivo", sa.String(32), nullable=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_midias_recebidas_pendentes",
        "midias_recebidas",
        ["criado_em"],
        postgresql_where=sa.text("status = 'PENDENTE'"),
    )


def downgrade() -> None:
    op.drop_index("ix_midias_recebidas_pendentes", table_name="midias_recebidas")
    op.drop_table("midias_recebidas")

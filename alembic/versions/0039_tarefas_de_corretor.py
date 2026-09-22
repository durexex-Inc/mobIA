"""a trilha append-only das tarefas para o corretor

TEC-186, RN-13.6. Uma linha por tentativa de follow-up que, fora da janela de
24h e sem template aprovado aplicavel ao contexto, nao pode virar envio e vira
trabalho manual para o corretor. Molde de `followups` (0015): append-only, sem
estado, com a MESMA UNIQUE por ancora -- a idempotencia por tentativa herda
dela.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0015 e da
0010: a retencao desta trilha nao pode ser encurtada por cascata da limpeza de
outra tabela.

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tarefas_de_corretor",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("ancora_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tentativa_numero", sa.SmallInteger(), nullable=False),
        sa.Column("categoria", sa.String(24), nullable=False),
        sa.Column("motivo", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint("tentativa_numero > 0", name="ck_tarefas_de_corretor_tentativa"),
        sa.UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_tarefas_de_corretor_por_ancora",
        ),
    )
    op.create_index(
        "ix_tarefas_de_corretor_lead",
        "tarefas_de_corretor",
        ["channel", "conversation_key", "ancora_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_tarefas_de_corretor_lead", table_name="tarefas_de_corretor")
    op.drop_table("tarefas_de_corretor")

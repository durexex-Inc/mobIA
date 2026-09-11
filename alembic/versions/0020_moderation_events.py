"""registro append-only de recusa da moderacao

TEC-142. Uma linha por bloqueio, nas duas direcoes e em todas as categorias:
quem distingue discriminacao das demais e a coluna `categoria`, nao a
existencia da linha.

Sem o texto julgado, em nenhuma coluna. O corpo ja esta cifrado em `messages`,
e a RN-04.5 pede o registro do evento e nao do conteudo -- copia-lo criaria em
claro exatamente o que o quarto criterio de aceite da card manda nao existir.

Sem FK para `messages`, pelo mesmo motivo da 0010: a retencao de mensagens
(12 meses, RNF-22) e mais curta que a do registro de conformidade, e uma FK
faria a limpeza apagar evidencia por cascata ou travar por restricao.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("direcao", sa.String(8), nullable=False),
        sa.Column("categoria", sa.String(32), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_moderation_events_lead",
        "moderation_events",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_events_lead", table_name="moderation_events")
    op.drop_table("moderation_events")

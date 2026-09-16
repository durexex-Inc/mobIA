"""a conversa ganha status, e a intencao ganha contador de fora de escopo

TEC-138, RN-03.5 e RN-02.3.

`conversas` e a entidade que a TEC-130 ia criar e que esta card precisou
antes. A TEC-130 estende: acrescenta motivo e escritor, nao tabela.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0010 e da
0012: a retencao desta tabela nao pode ser encurtada por cascata da limpeza de
outra.

O `server_default='0'` do contador existe para as linhas que ja estao la: a
coluna e NOT NULL e `conversation_intent` tem linha para toda conversa ja
atendida. Sem o default o ALTER falha.

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_intent",
        sa.Column("fora_de_escopo_seguidas", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "conversas",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ATIVA"),
        sa.Column("motivo_do_encerramento", sa.String(16), nullable=True),
        sa.Column("encerrada_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("conversas")
    op.drop_column("conversation_intent", "fora_de_escopo_seguidas")

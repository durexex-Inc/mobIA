"""a trilha append-only dos follow-ups disparados

TEC-183, RN-13.1 e RN-13.4. Uma linha por tentativa que venceu e foi
registrada. Nao ha linha PENDENTE: a cadencia e derivada da ancora a cada
varredura, e o SRS descrevia um agendamento persistido -- ver a emenda a
RN-13.4.

**`ancora_em` e a coluna que torna a trilha legivel.** Ela guarda a ultima
fala do lead que gerou este disparo, entao "ate que tentativa a cadencia ja
foi desde que o lead falou pela ultima vez" e um MAX filtrado por igualdade
nela. Quando o lead responde, a ancora muda e a regua recomeca sozinha -- o
reinicio da RN-13.4 fica auditavel, com as duas series lado a lado, em vez de
implicito.

**`temperatura` e redundante com `lead_qualification` de proposito.** Ela
explica POR QUE foram N tentativas, e a coluna viva ja tera mudado quando
alguem for ler a trilha. Mesmo raciocinio dos cinco fatores em
`lead_score_audit`.

**O UNIQUE e a defesa contra varredura concorrente.** Duas passagens veriam o
mesmo candidato devido e ambas inseririam; nao da para usar FOR UPDATE SKIP
LOCKED sobre a agregacao que produz os candidatos, entao a exclusao mora na
restricao.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0010 e da
0012: a retencao da trilha nao pode ser encurtada por cascata da limpeza de
outra tabela.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("tentativa_numero", sa.SmallInteger(), nullable=False),
        sa.Column("temperatura", sa.String(8), nullable=False),
        sa.Column("ancora_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("devido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint("tentativa_numero > 0", name="ck_followups_tentativa"),
        sa.UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_followups_tentativa_por_ancora",
        ),
    )
    op.create_index(
        "ix_followups_lead",
        "followups",
        ["channel", "conversation_key", "ancora_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_followups_lead", table_name="followups")
    op.drop_table("followups")

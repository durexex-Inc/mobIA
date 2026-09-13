"""o estado da notificacao ao corretor, ao lado do handoff que ela avisa

TEC-177, RF-16 e RN-16.2.

**Duas colunas, e nenhuma tabela de historico.** Nada nesta card le tentativa
passada: o que a E8 e a TEC-178 vao querer e o estado CORRENTE, e e isso que
as duas dizem. Uma tabela append-only sem leitor seria o peso morto que a D1
da TEC-174 recusou.

**`aviso_manual_pendente` nasce FALSO.** Verdadeiro faria todo handoff nascer
pedindo intervencao humana, e o painel mostraria a fila inteira como problema.
O estado "ainda nao tentei" e este par: falso, com `notificado_em` nulo.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("handoffs", sa.Column("notificado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "handoffs",
        sa.Column(
            "aviso_manual_pendente",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("handoffs", "aviso_manual_pendente")
    op.drop_column("handoffs", "notificado_em")

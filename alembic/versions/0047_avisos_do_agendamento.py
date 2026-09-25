"""o registro de cada aviso da confirmacao do agendamento

TEC-170, D2 e D7. Tres passos independentes -- lead, corretor, calendario --
e uma coluna por passo como marca de feito: nula e o registro de que o passo
nao aconteceu (falhou, foi recusado pela guarda ou a integracao esta
desligada), preenchida e o que impede a reexecucao de repeti-lo.

`calendar_event_id` com o nome e o tamanho do modelo de dados do SRS.

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agendamentos", sa.Column("calendar_event_id", sa.String(120), nullable=True))
    op.add_column(
        "agendamentos", sa.Column("corretor_avisado_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agendamentos", sa.Column("lead_avisado_em", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agendamentos", "lead_avisado_em")
    op.drop_column("agendamentos", "corretor_avisado_em")
    op.drop_column("agendamentos", "calendar_event_id")

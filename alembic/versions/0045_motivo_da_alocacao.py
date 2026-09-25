"""o motivo da alocacao do corretor, gravado no agendamento

TEC-166, RN-11.2. A gerente precisa entender por que aquele corretor foi
escolhido; a categoria mora ao lado do agendamento que ela vai olhar.

**NOT NULL sem valor padrao, e sem backfill.** Nenhum caminho de producao
grava em `agendamentos` ate esta card -- `reservar` nao tem chamador fora dos
testes --, entao nao ha linha antiga para receber um motivo inventado. Se um
dia esta migration encontrar linha, o `ADD COLUMN` reprova, e isso e o certo:
motivo inventado seria pior que a falha.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agendamentos", sa.Column("motivo_da_alocacao", sa.String(24), nullable=False))
    op.create_check_constraint(
        "ck_agendamentos_motivo_da_alocacao",
        "agendamentos",
        "motivo_da_alocacao IN ('MATCH_EXATO','SEM_MATCH','MATCH_SEM_CAPACIDADE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agendamentos_motivo_da_alocacao", "agendamentos", type_="check")
    op.drop_column("agendamentos", "motivo_da_alocacao")

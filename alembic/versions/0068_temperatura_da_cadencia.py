"""a temperatura da cadencia de reengajamento, sem a penalidade de no-show

TEC-385, Emenda E-02 a RN-12.4 e a RN-13.1. `lead_qualification` ganha
`temperatura_da_cadencia`, que `registrar_recalculo` grava junto com
`temperatura`: a mesma conta sobre o score sem a penalidade de nao
comparecimento.

**O preenchimento e exato so onde nao ha penalidade.** Sem penalidade as duas
temperaturas sao a mesma por construcao, e a subida copia uma para a outra.
Com penalidade, a temperatura sem ela depende do `qualificado` e do score
recalculado -- regra de dominio, que migration nao reescreve em SQL. Essas
linhas ficam NULL, a varredura le `COALESCE(temperatura_da_cadencia,
temperatura)` e se comporta como antes para elas, e
`scripts/preencher_temperatura_da_cadencia.py` as recalcula pelo caminho do
dominio.

Revision ID: 0068
Revises: 0067
"""

import sqlalchemy as sa

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura_da_cadencia", sa.String(8), nullable=True),
    )
    op.execute(
        "UPDATE lead_qualification SET temperatura_da_cadencia = temperatura"
        " WHERE COALESCE(penalidade_pontos, 0) = 0"
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "temperatura_da_cadencia")

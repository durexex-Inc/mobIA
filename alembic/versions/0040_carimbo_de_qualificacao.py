"""quando o lead cruzou a borda da qualificacao

TEC-190, RN-17.1 e RN-17.2. Coluna nulavel e sem backfill: o instante nunca
foi gravado em lugar nenhum, entao nao ha de onde o backfill sair. `NULL`
significa "nao qualificou" ou "qualificou antes desta card", e as duas se leem
igual na metrica -- fora da contagem. Lacuna L1 do desenho.

Sem indice nesta card. O predicado do funil e
`qualificado_em >= :de AND qualificado_em < :ate`, e o teste de latencia da
Tarefa 8 e quem decide se ele precisa de indice -- medir antes, e nao criar
indice por precaucao sobre uma tabela que o painel varre uma vez por minuto.

Revision ID: 0040
Revises: 0039
"""

import sqlalchemy as sa

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("qualificado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "qualificado_em")

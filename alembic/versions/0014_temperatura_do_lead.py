"""a temperatura do lead, e o forcamento que sobrevive ao recalculo

TEC-151, RN-06.2 e RN-06.3. Tres colunas nulaveis e sem backfill: `NULL` em
`temperatura` significa "linha anterior a esta card, nunca recalculada", e e
contra esse `NULL` que a borda da notificacao da RN-06.5 compara. Um backfill
para FRIO apagaria a distincao entre "nunca calculei" e "ja era FRIO", e o
lead cuja primeira travessia caisse em QUENTE perderia a unica que tem.

**Aqui e nao em `lead_score_audit`.** Duas razoes, e a segunda e a grave: a
trilha grava so quando o score muda (D3 da TEC-152), e um gatilho dispara em
turno em que nenhum dos cinco fatores se move -- nao haveria linha onde
guardar o forcamento; e a trilha tem retencao de 12 meses (RNF-18) e e
expurgavel, entao um lead cujo ultimo registro fosse expurgado voltaria a
parecer nunca-calculado e reemitiria a notificacao de esquentou como se
tivesse acabado de esquentar. E o "carga viva do produto" que a propria
TEC-152 nomeou ao deferir esta decisao.

**Os dois CHECK sao as duas metades da mesma invariante**, no molde dos dois
da 0012: forcado implica QUENTE, e forcado sem motivo nomeado e a mesma forma
de mentira que uma linha da trilha sem causa. Os dois sao condicionais ao
carimbo, entao toda linha anterior a esta card passa com os tres NULL.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura", sa.String(8), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura_forcada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lead_qualification",
        sa.Column("temperatura_forcada_motivos", postgresql.ARRAY(sa.String(16)), nullable=True),
    )
    op.create_check_constraint(
        "ck_lead_qualification_forcada_quente",
        "lead_qualification",
        "temperatura_forcada_em IS NULL OR temperatura = 'QUENTE'",
    )
    op.create_check_constraint(
        "ck_lead_qualification_forcada_motivos",
        "lead_qualification",
        "temperatura_forcada_em IS NULL OR cardinality(temperatura_forcada_motivos) > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_lead_qualification_forcada_motivos", "lead_qualification")
    op.drop_constraint("ck_lead_qualification_forcada_quente", "lead_qualification")
    op.drop_column("lead_qualification", "temperatura_forcada_motivos")
    op.drop_column("lead_qualification", "temperatura_forcada_em")
    op.drop_column("lead_qualification", "temperatura")

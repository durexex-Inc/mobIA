"""marca dos campos perguntados sem resposta na qualificacao do lead

TEC-257. NULL = linha anterior a esta card, quando ninguem marcava.

Nullable e sem backfill de proposito, pela mesma razao da 0007 e da 0008: uma
linha que ja existe nunca teve marca, e nao ha como reconstruir a de ontem. O
que foi perguntado esta no texto das respostas do agente, cifrado em
`messages`, e sabe-lo exigiria rodar deteccao sobre historico -- que e
justamente o proxy que esta card recusou usar para decidir comportamento.

**O default nao e `{}`, e a diferenca importa.** `{}` significa "esta linha
marcava e nao havia nada a marcar", que e afirmacao sobre um turno que rodou
com o codigo novo. `NULL` significa "ninguem media". Um `server_default` de
`{}` apagaria a distincao em toda linha antiga.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column(
            "perguntados_sem_resposta",
            postgresql.ARRAY(sa.String(32)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "perguntados_sem_resposta")

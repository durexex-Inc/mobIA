"""o resumo em seis blocos, cifrado, ao lado do handoff que ele descreve

TEC-175, RF-15 e RN-15.1.

**Cifrada, ao contrario de `lead_qualification`.** O argumento e o do
`conversation_summaries` e vale palavra por palavra: um resumo destila as
mesmas frases que `messages.text_body` guarda, e deixa-lo em claro ao lado de
uma coluna cifrada seria manter a fechadura e tirar a porta. A assimetria com
`lead_qualification` -- que fica legivel -- se sustenta: aquela tabela e o que
o SISTEMA concluiu, e TEC-150 e TEC-158 a filtram em SQL. Ninguem filtra por
este texto.

**Nulavel, e isso nao contradiz a D1 da TEC-174.** O que aquela card recusou
foi coluna nulavel SEM escritor nenhum; esta tem o seu. A nulabilidade e
consequencia de a geracao ser assincrona: todo handoff existe por alguns
segundos sem resumo, e NULL e o nome desse intervalo. E tambem o estado em que
um handoff fica quando a geracao falha, que e o que a TEC-176 vai ler para
decidir o que entregar no lugar.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("handoffs", sa.Column("resumo", sa.LargeBinary(), nullable=True))
    op.add_column(
        "handoffs", sa.Column("resumo_gerado_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("handoffs", sa.Column("resumo_modelo", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("handoffs", "resumo_modelo")
    op.drop_column("handoffs", "resumo_gerado_em")
    op.drop_column("handoffs", "resumo")

"""o desfecho da transcricao do audio, na linha de midia

TEC-131, D3. Quatro colunas nulaveis em `midias_recebidas`, usadas so por
AUDIO: `status_da_transcricao` (nula ate o desfecho -- e o que a espera do
turno procura), `motivo_da_transcricao`, `duracao_segundos` e `transcrita_em`.
O texto transcrito nao entra aqui: vai para `messages.text_body`, cifrado com o
AAD que a coluna ja usa.

Sem CHECK nos dois vocabularios, pela mesma razao da 0048: nenhuma leitura
compara literal cru contra elas.

Sem indice novo: a unica leitura por status da transcricao (a espera, em
`domain/midia/espera.py`) chega a esta tabela pela PK, a partir das mensagens
da conversa que `ix_messages_timeline` ja acha.

Revision ID: 0067
Revises: 0066
"""

import sqlalchemy as sa

from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "midias_recebidas", sa.Column("status_da_transcricao", sa.String(16), nullable=True)
    )
    op.add_column(
        "midias_recebidas", sa.Column("motivo_da_transcricao", sa.String(32), nullable=True)
    )
    op.add_column("midias_recebidas", sa.Column("duracao_segundos", sa.Float(), nullable=True))
    op.add_column(
        "midias_recebidas",
        sa.Column("transcrita_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("midias_recebidas", "transcrita_em")
    op.drop_column("midias_recebidas", "duracao_segundos")
    op.drop_column("midias_recebidas", "motivo_da_transcricao")
    op.drop_column("midias_recebidas", "status_da_transcricao")

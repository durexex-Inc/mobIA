"""a recomendacao: o imovel apresentado, e o que o lead fez com ele

TEC-163, RN-10.3 e RN-10.4.

**Chaveada pelo par `(channel, conversation_key)`.** O SRS pede
`conversa_id UUID FK -> Conversa`, e `Conversa` nao existe neste sistema:
`conversation_summaries`, `lead_qualification` e `conversation_intent` usam
todas o par, desde as respectivas cards. A emenda E-01 da RN-10.3 declara a
divergencia -- que e do sistema e nao desta tabela, e estava tres tabelas
atrasada.

**O UNIQUE nao esta no SRS, e e de proposito.** Ele faz o cenario 4 do Gherkin
("os ja apresentados nao sao repetidos") ser garantia de schema em vez de
disciplina de consulta.

**Sem indice alem do UNIQUE.** As duas consultas desta card -- linhas
pendentes da conversa, e descartes por distancia da conversa -- filtram por
`(channel, conversation_key)`, que e o prefixo do UNIQUE e portanto ja e
servido por ele. Um indice a mais seria custo de escrita sem retorno de
leitura, que e exatamente a TEC-266.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recomendacoes",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("imovel_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("score_match", sa.Numeric(4, 3), nullable=False),
        sa.Column("motivo_match", sa.Text(), nullable=False),
        sa.Column("reacao_lead", sa.String(16), nullable=True),
        sa.Column("motivo_descarte", sa.String(80), nullable=True),
        sa.Column("apresentado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_recomendacoes"),
        sa.ForeignKeyConstraint(["imovel_id"], ["imoveis.id"], name="fk_recomendacoes_imovel"),
        sa.UniqueConstraint(
            "channel", "conversation_key", "imovel_id", name="uq_recomendacoes_conversa_imovel"
        ),
    )


def downgrade() -> None:
    op.drop_table("recomendacoes")

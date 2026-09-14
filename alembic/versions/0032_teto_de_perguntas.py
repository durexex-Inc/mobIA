"""o contador do teto de perguntas

TEC-149, RN-05.5. O SRS pede este contador em `conversa.perguntas_feitas`, e
nao ha tabela `conversa`: a Emenda E-01 da RN-05.7 (TEC-148) ja estabeleceu
que `conversation_key` e o id externo do lead e deferiu a criacao da
entidade. O contador vive aqui, na mesma chave -- e o teto passa a valer por
LEAD, sem fronteira de conversa e sem expirar. Ver a Emenda E-01 da RN-05.5.

`NOT NULL DEFAULT 0`, e nao nulavel como as colunas vizinhas desta tabela.
Ali `NULL` distingue "linha anterior a card" de "a card rodou e nao havia
nada"; para um contador essa distincao nao paga. `0` numa linha antiga nao
afirma "ninguem perguntou" -- afirma "ninguem contava", e o lead antigo ganha
orcamento cheio. Erra na direcao de continuar atendendo como hoje, em vez de
cortar alguem que nunca foi avisado.

`smallint` porque o teto e 8: o tipo vem do dicionario de dados do SRS, e
nem o maior exagero de contagem chega perto de 32.767.

Revision ID: 0032
Revises: 0031
"""

import sqlalchemy as sa

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_qualification",
        sa.Column("perguntas_feitas", sa.SmallInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("lead_qualification", "perguntas_feitas")

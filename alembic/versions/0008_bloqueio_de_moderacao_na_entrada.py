"""marca de bloqueio da moderacao de entrada na linha da mensagem

TEC-236. NULL = a moderacao de entrada nao bloqueou esta fala.

Nullable e sem backfill de proposito, pela mesma razao da 0007: uma linha que
ja existe e que nunca foi bloqueada tem exatamente a semantica de NULL, entao o
default correto para todas as linhas antigas ja e o que o `add_column` deixa.

**Uma ressalva que o NULL esconde, e por isso fica escrita aqui.** As falas que
a moderacao bloqueou *antes* desta migration existem no banco sem marca, e nao
ha como distingui-las: o bloqueio nao deixava rastro na linha -- e esse era o
defeito. Elas continuam elegiveis para contexto e para resumo. Backfill exigiria
re-moderar historico (pago) ou cruzar com o log de `moderacao.entrada_bloqueada`,
que retem por tempo limitado. Nao foi feito; se alguem precisar, o log e o unico
caminho e ele tem prazo.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("bloqueada_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "bloqueada_em")

"""o orcamento mensal de IA entra na configuracao do agente

TEC-191, D3 do desenho. Uma coluna nula em `configuracoes_do_agente`: o
orcamento mensal, em dolares, contra o qual o painel de custo acende o alerta
de 80%. **Nula nas linhas que ja existem**, e nao preenchida com um valor
qualquer: essas versoes foram gravadas sem orcamento, e e isso que elas dizem.

O CHECK recusa zero e negativo mesmo para quem grava por fora da rota --
com orcamento zero, todo centavo seria "acima de 80%". O teto fino (100.000)
e da aplicacao, que o explica em texto.

Revision ID: 0060
Revises: 0059
"""

import sqlalchemy as sa

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracoes_do_agente",
        sa.Column("orcamento_mensal_usd", sa.Numeric(10, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_configuracoes_do_agente_orcamento",
        "configuracoes_do_agente",
        "orcamento_mensal_usd IS NULL OR orcamento_mensal_usd > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_configuracoes_do_agente_orcamento", "configuracoes_do_agente", type_="check"
    )
    op.drop_column("configuracoes_do_agente", "orcamento_mensal_usd")

"""a aparencia do chat web entra na configuracao do agente

TEC-344, D1 do desenho. Duas colunas em `configuracoes_do_agente`: a cor
primaria do botao e o canto do site em que ele fica. **Nao nulas, com o
padrao da aplicacao nas linhas que ja existem**: ao contrario do orcamento da
`0060`, aqui "nenhum" nao e valor legitimo -- o botao sempre tem uma cor e um
lado --, e o padrao e exatamente o que essas versoes passam a valer.

Os CHECKs repetem `vigente.validar` para quem grava por fora da rota.

Revision ID: 0064
Revises: 0063
"""

import sqlalchemy as sa

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracoes_do_agente",
        sa.Column("cor_primaria", sa.String(7), nullable=False, server_default="#1D4ED8"),
    )
    op.add_column(
        "configuracoes_do_agente",
        sa.Column("posicao_do_botao", sa.String(8), nullable=False, server_default="DIREITA"),
    )
    op.create_check_constraint(
        "ck_configuracoes_do_agente_cor",
        "configuracoes_do_agente",
        "cor_primaria ~ '^#[0-9A-Fa-f]{6}$'",
    )
    op.create_check_constraint(
        "ck_configuracoes_do_agente_posicao",
        "configuracoes_do_agente",
        "posicao_do_botao IN ('DIREITA', 'ESQUERDA')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_configuracoes_do_agente_posicao", "configuracoes_do_agente", type_="check"
    )
    op.drop_constraint("ck_configuracoes_do_agente_cor", "configuracoes_do_agente", type_="check")
    op.drop_column("configuracoes_do_agente", "posicao_do_botao")
    op.drop_column("configuracoes_do_agente", "cor_primaria")

"""os dominios em que o chat web pode ser embutido

TEC-345, D1 do desenho. Uma coluna em `configuracoes_do_agente`: os sites
que o `frame-ancestors` de `/embed/*` passa a aceitar. **Nao nula, com a
lista vazia nas linhas que ja existem**, e vazia quer dizer que nenhum site
embute o chat -- o lado seguro, no lugar do `*` provisorio da TEC-344.

O CHECK repete o teto de `vigente.validar`. O formato de cada entrada fica
so na aplicacao: uma regex por elemento de array exigiria funcao propria no
banco, e quem interpola na CSP (o Next) confere o formato de novo.

Revision ID: 0065
Revises: 0064
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracoes_do_agente",
        sa.Column(
            "dominios_do_chat",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.create_check_constraint(
        "ck_configuracoes_do_agente_dominios",
        "configuracoes_do_agente",
        "cardinality(dominios_do_chat) <= 5",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_configuracoes_do_agente_dominios", "configuracoes_do_agente", type_="check"
    )
    op.drop_column("configuracoes_do_agente", "dominios_do_chat")

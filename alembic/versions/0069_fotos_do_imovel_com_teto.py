"""teto de 15 fotos por imovel

TEC-335, D1 e a secao "Migration" do desenho. O teto de 15 fotos vira
invariante de banco, e nao so validacao de rota: a rota de upload
(`POST /api/v1/imoveis/{id}/fotos`) e hoje a unica escritora que SOMA fotos,
mas o `PATCH /api/v1/imoveis/{id}` generico (TEC-197) tambem escreve `fotos`
livremente -- sem o `CHECK` ele poderia gravar 20 de uma vez so colando URLs.

Revision ID: 0069
Revises: 0068
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_imoveis_fotos_teto",
        "imoveis",
        "cardinality(fotos) <= 15",
    )


def downgrade() -> None:
    op.drop_constraint("ck_imoveis_fotos_teto", "imoveis", type_="check")

"""a indexacao vetorial do catalogo

TEC-157, RN-08.2 e RN-08.3. Fecha a divida que a `0016` declarou: ela deixou
`embedding` de fora porque a imagem do compose nao tinha pgvector, e a troca
de imagem pertence a esta card.

**O indice IVFFlat entra com `lists = 1`, e isso e deliberado.** IVFFlat e um
indice treinado: `lists` particiona o espaco, e a busca varre apenas as
particoes mais proximas. Com 520 a 2.000 imoveis, `lists = 100` colocaria ~5
vetores por particao e o recall despencaria; `lists = 1` degenera para
varredura da lista unica -- recall perfeito, custo de scan sequencial, que
nesta escala resolve em milissegundos e fica muito abaixo dos 400 ms da
RNF-03. **O indice esta aqui por conformidade com o SRS, nao porque a busca
dependa dele hoje.** Quem revisita `lists`, cobra o SLA ou migra para HNSW e
a TEC-159.

As tres colunas sao nulaveis porque hash nulo E a definicao de pendencia: e
o que faz o catalogo ja importado entrar na fila sem caminho de backfill.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

DIMENSOES = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("imoveis", sa.Column("embedding", Vector(DIMENSOES), nullable=True))
    op.add_column(
        "imoveis",
        sa.Column("embedding_atualizado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("imoveis", sa.Column("documento_hash", sa.Text(), nullable=True))

    op.execute(
        "CREATE INDEX ix_imoveis_embedding ON imoveis "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)"
    )


def downgrade() -> None:
    op.drop_index("ix_imoveis_embedding", table_name="imoveis")
    op.drop_column("imoveis", "documento_hash")
    op.drop_column("imoveis", "embedding_atualizado_em")
    op.drop_column("imoveis", "embedding")
    # A extensao NAO cai no downgrade: outra coisa pode ter passado a
    # depender dela, e `DROP EXTENSION` derrubaria em cascata.

"""o catalogo de imoveis e a trilha de importacoes

TEC-156, RF-08. A raiz do epico do catalogo: sem estas duas tabelas nao ha
o que recomendar.

**Sem `embedding` nem `embedding_atualizado_em`.** Nao e so escopo da card: a
imagem do compose e `postgres:16-alpine`, que nao tem pgvector, entao criar a
coluna hoje exigiria trocar a imagem -- infra que pertence a TEC-157, junto
com a extensao e o indice IVFFlat. Colunas nulas agora antecipariam a troca
sem antecipar nada que a use.

**Sem tipo ENUM.** Nenhuma tabela deste banco usa ENUM do Postgres; o dominio
mora em `StrEnum` sobre `String(n)`. Seguir o SRS ao pe da letra faria desta a
unica tabela cujo dominio so muda por ALTER TYPE.

**O UNIQUE em `codigo` e a chave do upsert**, e nao decoracao. E ele que
impede o duplicado do cenario 3 do Gherkin mesmo com dois lotes correndo
juntos -- a classificacao inserido/atualizado e feita em Python, fora de
transacao unica, entao a exclusao precisa morar na restricao. Mesmo
raciocinio do UNIQUE da 0015.

**Os bytes do arquivo ficam em `importacoes.arquivo`.** Passar 10 MB pelo
payload do ARQ transformaria a fila em armazenamento; gravar em disco exigiria
volume compartilhado entre API e worker, que o compose nao tem. Reler o
arquivo exato que gerou um relatorio e o que torna o relatorio auditavel.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "imoveis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("codigo", sa.String(20), nullable=False),
        sa.Column("titulo", sa.String(160), nullable=False),
        sa.Column("descricao", sa.Text(), nullable=False),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("operacao", sa.String(8), nullable=False),
        sa.Column("preco_venda", sa.BigInteger(), nullable=True),
        sa.Column("preco_aluguel", sa.BigInteger(), nullable=True),
        sa.Column("condominio", sa.BigInteger(), nullable=True),
        sa.Column("iptu_mensal", sa.BigInteger(), nullable=True),
        sa.Column("bairro", sa.String(120), nullable=False),
        sa.Column("cidade", sa.String(120), nullable=False),
        sa.Column("uf", sa.String(2), nullable=False),
        sa.Column("zona", sa.String(8), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("area_util_m2", sa.Integer(), nullable=False),
        sa.Column("quartos", sa.SmallInteger(), nullable=False),
        sa.Column("suites", sa.SmallInteger(), nullable=False),
        sa.Column("banheiros", sa.SmallInteger(), nullable=False),
        sa.Column("vagas", sa.SmallInteger(), nullable=False),
        sa.Column(
            "caracteristicas",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "fotos",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "preco_venda IS NOT NULL OR preco_aluguel IS NOT NULL",
            name="ck_imoveis_ao_menos_um_preco",
        ),
        sa.UniqueConstraint("codigo", name="uq_imoveis_codigo"),
    )
    # A busca da TEC-158 filtra por bairro e cidade antes da similaridade;
    # o indice existe desde ja porque o SRS marca as duas como indexadas.
    op.create_index("ix_imoveis_bairro", "imoveis", ["bairro"])
    op.create_index("ix_imoveis_cidade", "imoveis", ["cidade"])
    op.create_index("ix_imoveis_status", "imoveis", ["status"])

    op.create_table(
        "importacoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("origem", sa.String(8), nullable=False),
        sa.Column("nome_arquivo", sa.String(255), nullable=False),
        sa.Column("arquivo", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("processados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inseridos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atualizados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inalterados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejeitados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "erros",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "criada_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("concluida_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("importacoes")
    op.drop_index("ix_imoveis_status", table_name="imoveis")
    op.drop_index("ix_imoveis_cidade", table_name="imoveis")
    op.drop_index("ix_imoveis_bairro", table_name="imoveis")
    op.drop_table("imoveis")

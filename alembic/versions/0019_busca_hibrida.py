"""a coluna que faz o bairro do lead casar com o do banco

TEC-158, RN-09.1 e a emenda E-01 dela. O lead fala "aclimacao" (dobrado por
`normalizar_regiao`) e o banco guarda "Aclimacao" com til, como veio do
arquivo. Comparar os dois exige dobrar um dos lados.

**Por que uma coluna, e nao `unaccent()` na consulta.** `unaccent()` e STABLE
e nao IMMUTABLE, entao um indice funcional sobre ela exige um wrapper
IMMUTABLE declarado a mao -- uma mentira controlada sobre a funcao, que quebra
em silencio se alguem trocar o dicionario do unaccent. E a regra de dobra
passaria a existir em Python E em SQL: a divergencia se manifestaria como
bairro que o lead nomeia e a busca nao encontra, sem erro. Ver D5.

**Nao e coluna gerada, e a recusa e do Postgres.** `GENERATED ALWAYS AS ...
STORED` seria o desenho ideal -- derivada por construcao, impossivel de
esquecer. A expressao de coluna gerada tem de ser IMMUTABLE, e e justamente
`unaccent` que nao e.

**O backfill roda em Python, chamando a mesma `dobrar()` do caminho normal.**
Importar codigo da aplicacao numa migration nao e padrao novo: a `0004`
importa `mobia.infra.crypto`, e e por isso que `alembic` esta no escopo do
`ruff`. A alternativa era `CREATE EXTENSION unaccent` so para esta escrita
unica, o que instalaria uma extensao permanente e deixaria no schema o
convite a usa-la no caminho de LEITURA que a D5 recusou.

**O composto entra por conformidade, nao por medicao** -- mesma postura que a
`0017` assumiu com o `lists = 1` do IVFFlat. Com 520 a 2.000 imoveis o filtro
resolve em varredura sequencial em milissegundos. E ele so serve metade das
buscas: as colunas que o SRS nomeia incluem `preco_venda`, entao uma busca de
ALUGUEL usa no maximo o prefixo `(status, tipo)`. Quem mede os dois regimes e
decide se isso vira um segundo composto e a TEC-159.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op
from mobia.domain.texto import dobrar

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nulavel primeiro: nao ha valor a escrever antes do backfill, e um
    # server_default de '' faria a linha existente casar a busca por bairro
    # vazio em vez de nao casar nada.
    op.add_column("imoveis", sa.Column("bairro_busca", sa.Text(), nullable=True))

    conexao = op.get_bind()
    linhas = conexao.execute(sa.text("SELECT id, bairro FROM imoveis")).fetchall()
    for identificador, bairro in linhas:
        conexao.execute(
            sa.text("UPDATE imoveis SET bairro_busca = :dobrado WHERE id = :identificador"),
            {"dobrado": dobrar(bairro), "identificador": identificador},
        )

    op.alter_column("imoveis", "bairro_busca", nullable=False)

    op.create_index("ix_imoveis_bairro_busca", "imoveis", ["bairro_busca"])
    op.create_index("ix_imoveis_filtro", "imoveis", ["status", "tipo", "preco_venda", "quartos"])


def downgrade() -> None:
    op.drop_index("ix_imoveis_filtro", table_name="imoveis")
    op.drop_index("ix_imoveis_bairro_busca", table_name="imoveis")
    op.drop_column("imoveis", "bairro_busca")

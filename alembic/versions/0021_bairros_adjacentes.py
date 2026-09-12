"""a tabela de adjacencia de bairros, com a carga junto

TEC-160, RN-09.3. O relaxamento amplia para "bairros adjacentes (tabela de
adjacencia pre-carregada)", e esta e a tabela.

**A carga vem NESTA revisao, e nao de um seed a parte.** Sao duas
consequencias. A boa: a tabela fica FORA de `TABELAS` no `tests/conftest.py`,
sobrevive ao TRUNCATE que a fixture autouse `banco_limpo` da a cada teste, e
todo teste de integracao a tem sem semear -- numa suite de 1200+ testes,
inclui-la em `TABELAS` custaria mais de mil TRUNCATE a mais, e a contencao de
lock que isso produz e a causa conhecida dos flakes de ConnectionResetError.
A contrapartida: mudar a adjacencia passa a exigir migration nova.

A alternativa de criar vazia e semear depois foi recusada porque um ambiente
recem-migrado teria a tabela vazia, e a RN-09.3 silenciosamente nao ampliaria
bairro nenhum -- falha que nao levanta erro e se parece com "nada e
adjacente". Ver D7 do desenho.

**Os nomes sao gravados dobrados, chamando a mesma `dobrar()` do caminho
normal** -- mesmo padrao da `0019`, e e por isso que `alembic` esta no escopo
do `ruff`. Uma segunda definicao da dobra aqui divergiria da de producao e o
sintoma seria bairro que o lead nomeia e a busca nao amplia.

O criterio dos pares e "contiguos ou ligados por via direta", sobre os 12
bairros de Florianopolis do catalogo simulado. Duas escolhas que alguem vai
questionar: Campeche tem um vizinho so, e Centro-Estreito atravessa a baia
(incluido porque a ponte os liga e um lead de Florianopolis os trata como
vizinhos).

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa

from alembic import op
from mobia.domain.texto import dobrar

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# Os 15 pares nao ordenados. A migration grava as DUAS direcoes de cada um --
# escrever so um lado aqui e derivar o outro mantem esta lista curta e torna
# impossivel gravar um par assimetrico por engano.
PARES = (
    ("Centro", "Agronomica"),
    ("Centro", "Trindade"),
    ("Centro", "Estreito"),
    ("Agronomica", "Trindade"),
    ("Agronomica", "Itacorubi"),
    ("Trindade", "Itacorubi"),
    ("Itacorubi", "Lagoa da Conceicao"),
    ("Itacorubi", "Santo Antonio de Lisboa"),
    ("Lagoa da Conceicao", "Campeche"),
    ("Estreito", "Balneario"),
    ("Estreito", "Coqueiros"),
    ("Balneario", "Coqueiros"),
    ("Canasvieiras", "Jurere"),
    ("Canasvieiras", "Santo Antonio de Lisboa"),
    ("Jurere", "Santo Antonio de Lisboa"),
)


def upgrade() -> None:
    op.create_table(
        "bairros_adjacentes",
        sa.Column("bairro_busca", sa.Text(), nullable=False),
        sa.Column("adjacente_busca", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("bairro_busca", "adjacente_busca", name="pk_bairros_adjacentes"),
    )

    linhas = [
        {"bairro_busca": dobrar(esquerda), "adjacente_busca": dobrar(direita)}
        for par in PARES
        for esquerda, direita in (par, (par[1], par[0]))
    ]
    op.bulk_insert(
        sa.table(
            "bairros_adjacentes",
            sa.column("bairro_busca", sa.Text),
            sa.column("adjacente_busca", sa.Text),
        ),
        linhas,
    )


def downgrade() -> None:
    op.drop_table("bairros_adjacentes")

r"""os campos de qualificacao do investidor

TEC-153, RN-05.2 e RN-07.2. Sete colunas nulaveis em `lead_qualification`, e
nao tabela nova: e o mesmo lead, o mesmo momento do turno e o mesmo ciclo de
vida das colunas vizinhas. Tabela separada exigiria join para responder "o
que sabemos deste lead" e entraria no TRUNCATE de todo teste que toca banco.

Tres destas colunas -- `horizonte`, `tolerancia_reforma`,
`ja_investe_em_imoveis` -- nao estao no dicionario de dados do SRS, embora a
RN-05.2 as nomeie. Ver a Emenda E-01 da RN-05.2.

`retorno_esperado_tipo` nao existe no SRS de forma nenhuma: e o campo
QUALITATIVO que a RN-07.2 pressupoe sem nomear, porque `retorno_esperado_pct`
sozinho nao separa renda de valorizacao -- 8% ao ano descreve os dois. Ver a
Emenda E-01 da RN-07.2.

`perfil_investidor` e DERIVADO (`perfil_de`, em `context/qualificacao.py`) e
gravado, nao calculado na leitura: quem le o lead precisa do perfil sem
reexecutar a regra, e a TEC-154 vai le-lo direto.

Revision ID: 0033
Revises: 0032
"""

from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

# `Any` por dentro de proposito: a tupla mistura BigInteger, Numeric, String e
# Boolean, entao nao existe parametro de tipo comum mais estreito. Uma uniao
# dos sete nao pagaria o que custa a ler, para uma tupla que so e iterada em
# `op.add_column`.
_COLUNAS: tuple[sa.Column[Any], ...] = (
    sa.Column("ticket_investimento_centavos", sa.BigInteger(), nullable=True),
    sa.Column("retorno_esperado_pct", sa.Numeric(4, 2), nullable=True),
    sa.Column("retorno_esperado_tipo", sa.String(16), nullable=True),
    sa.Column("horizonte", sa.String(16), nullable=True),
    sa.Column("tolerancia_reforma", sa.String(16), nullable=True),
    sa.Column("ja_investe_em_imoveis", sa.Boolean(), nullable=True),
    sa.Column("perfil_investidor", sa.String(16), nullable=True),
)


def upgrade() -> None:
    for coluna in _COLUNAS:
        op.add_column("lead_qualification", coluna)


def downgrade() -> None:
    for coluna in reversed(_COLUNAS):
        op.drop_column("lead_qualification", coluna.name)

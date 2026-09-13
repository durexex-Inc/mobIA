"""a apresentacao passa a ter dono, preco e kind

TEC-275, D2/D3/D9.

**As tres sao nullable, e nao e frouxidao.** Linha gravada antes desta card
nao tem mensagem dona, preco apresentado nem kind -- e nenhum dos tres e
derivavel depois do fato. `preco_centavos` em especial NAO pode ser
preenchido a partir de `imoveis`: a linha tem `preco_venda` e `preco_aluguel`
e nao diz qual foi mostrado, porque a operacao buscada so existe dentro de
`porta_de_busca` (D7 da TEC-162). Backfill aqui inventaria numero.

A consequencia esta na L2 do desenho: apresentacao anterior ao deploy nao e
continuavel, cai no ramo de turno normal, e o conjunto some sozinho conforme
as conversas avancam.

**`ondelete="SET NULL"` e nao CASCADE.** `outbound_dispatches` usa CASCADE
porque uma reserva sem mensagem nao significa nada. Aqui e o oposto: a linha
e a medida de conversao que a RN-10.3 existe para dar, e ela continua
verdadeira ("este imovel foi apresentado nesta conversa") depois de a
mensagem sumir. Perder o dono custa a continuacao; perder a linha custa o
historico.

O indice e parcial porque so o ramo da continuacao consulta por
`message_id`, e ele so alcanca linha que TEM dono.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recomendacoes", sa.Column("message_id", PgUUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_recomendacoes_message",
        "recomendacoes",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("recomendacoes", sa.Column("preco_centavos", sa.BigInteger(), nullable=True))
    op.add_column("recomendacoes", sa.Column("kind", sa.String(32), nullable=True))
    op.create_index(
        "ix_recomendacoes_message",
        "recomendacoes",
        ["message_id"],
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_recomendacoes_message", table_name="recomendacoes")
    op.drop_column("recomendacoes", "kind")
    op.drop_column("recomendacoes", "preco_centavos")
    op.drop_constraint("fk_recomendacoes_message", "recomendacoes", type_="foreignkey")
    op.drop_column("recomendacoes", "message_id")

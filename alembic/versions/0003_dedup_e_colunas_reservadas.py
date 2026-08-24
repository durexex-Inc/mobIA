"""dedup por provider_message_id e colunas reservadas

Uma migration para tres historias, porque as tres mexem na mesma tabela:

* TEC-125 -- UNIQUE (channel, provider_message_id), com comportamento nesta entrega.
* TEC-217 -- coluna `envelope_context`, reservada, ainda sem escritor.
* TEC-218 -- coluna `claimed_at`, reservada, ainda sem escritor.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # O esquema anterior permitia duplicata de proposito, e reentrega da Meta e
    # exatamente o que as produz -- entao um banco com trafego real pode ja ter
    # linhas que violam a constraint que vem a seguir. Sem esta limpeza o
    # `upgrade` aborta com "Key ... is duplicated"; os testes nao pegariam,
    # porque migram um banco recem-truncado.
    #
    # Mantem a linha de `received_at` mais antigo por (channel,
    # provider_message_id): a primeira entrega e a que foi processada. O
    # `ondelete=CASCADE` de outbound_dispatches leva junto as reservas das
    # linhas removidas, que e o comportamento certo -- elas nunca deveriam ter
    # existido.
    op.execute(
        """
        DELETE FROM messages
         WHERE id IN (
            SELECT id
              FROM (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY channel, provider_message_id
                               ORDER BY received_at, id
                           ) AS posicao
                      FROM messages
                   ) AS ranqueadas
             WHERE posicao > 1
         )
        """
    )

    # O indice simples sai porque a constraint composta cobre o mesmo prefixo
    # (`channel`) e a busca real e sempre pelo par. Uma consulta so por
    # `provider_message_id` deixa de ter indice -- nenhuma existe hoje, e quem
    # precisar de uma que crie o indice junto com ela.
    op.drop_index("ix_messages_provider_message_id", table_name="messages")
    op.create_unique_constraint(
        "uq_messages_channel_provider_message_id",
        "messages",
        ["channel", "provider_message_id"],
    )

    op.add_column("messages", sa.Column("envelope_context", postgresql.JSONB(), nullable=True))
    op.add_column("messages", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "claimed_at")
    op.drop_column("messages", "envelope_context")
    op.drop_constraint("uq_messages_channel_provider_message_id", "messages", type_="unique")
    op.create_index("ix_messages_provider_message_id", "messages", ["provider_message_id"])

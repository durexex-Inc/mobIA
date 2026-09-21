"""o vocabulario de role, direction, content_type e status vira CHECK

TEC-223.

As quatro colunas sao `String` livre desde a TEC-126: o vocabulario vivia so
nos enums Python. Duas garantias do sistema comparam literal em SQL cru --
`WHERE direction = 'INBOUND'` no sweeper e na ancora do follow-up --, e uma
linha gravada como `'inbound'` as burla em silencio: ela seria varrida, e a
fala do proprio agente voltaria para `process_message`, que emitiria efeito
externo por uma mensagem que ninguem enviou.

Hoje ha dois escritores e ambos passam pelos enums. Isto e para o terceiro,
que a TEC-124 traz com o canal web.

`status` admite NULL, e isso e deliberado: NULL significa "nao participa do
pipeline de ingestao" e e o que a linha de saida grava. O `IS NULL` explicito
e redundante -- `IN` com NULL da UNKNOWN, que nao viola CHECK -- e esta ali
para dizer que o NULL e permitido de proposito.

Revision ID: 0037
Revises: 0036
"""

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_messages_role",
        "messages",
        "role IN ('LEAD', 'AGENTE', 'CORRETOR', 'SISTEMA')",
    )
    op.create_check_constraint(
        "ck_messages_direction",
        "messages",
        "direction IN ('INBOUND', 'OUTBOUND')",
    )
    op.create_check_constraint(
        "ck_messages_content_type",
        "messages",
        "content_type IN ('TEXTO', 'AUDIO', 'IMAGEM', 'DOCUMENTO', 'DESCONHECIDO')",
    )
    op.create_check_constraint(
        "ck_messages_status",
        "messages",
        "status IS NULL OR status IN ('RECEIVED', 'QUEUED', 'PROCESSING', 'PROCESSED', 'FAILED')",
    )


def downgrade() -> None:
    # Ordem inversa da criacao, como a 0014 faz.
    op.drop_constraint("ck_messages_status", "messages")
    op.drop_constraint("ck_messages_content_type", "messages")
    op.drop_constraint("ck_messages_direction", "messages")
    op.drop_constraint("ck_messages_role", "messages")

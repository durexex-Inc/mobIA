"""o registro append-only de consentimento, comecando pelo chat web

TEC-363, RN-FE-20.2. Tabela nova e vazia: nao ha backfill porque consentimento
nunca foi coletado em lugar nenhum deste sistema -- nem no web, nem no
WhatsApp. Inventar linhas seria inventar prova.

`channel` ja nasce generico apesar de so o `web` escrever hoje: a coluna e o
mesmo par `(channel, conversation_key)` que identifica o lead em
`optout_events` e `lead_qualification`, e um `web` fixo obrigaria migration
quando o WhatsApp passar a perguntar.

O indice e o caminho da unica leitura: "qual o ultimo consentimento desta
sessao?".

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consentimentos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("marketing", sa.Boolean(), nullable=False),
        # O texto que a visitante VIU. E nosso, nao dela -- e por isso e
        # copiado aqui, ao contrario do que `optout_events` faz com a fala do
        # lead. Sem ele o registro diz "aceitou" sem dizer aceitou o que, e
        # nao vale como evidencia.
        sa.Column("texto_exibido", sa.Text(), nullable=False),
        # Relogio do CLIENTE: diagnostico, nunca evidencia. Anulavel porque um
        # cliente pode nao mandar, e recusar o consentimento inteiro por causa
        # de um carimbo opcional seria perder o registro que importa.
        sa.Column("exibido_em", sa.DateTime(timezone=True), nullable=True),
        # Relogio do POSTGRES, e e esta a data que responde "quando ela
        # consentiu". Mesmo argumento que `optout_events` faz para o dele.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_consentimentos_lead",
        "consentimentos",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_consentimentos_lead", table_name="consentimentos")
    op.drop_table("consentimentos")

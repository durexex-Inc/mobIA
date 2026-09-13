"""quem assumiu qual conversa, para o agente calar

TEC-179, RF-16 e RN-16.4.

**Uma linha por conversa, com UNIQUE -- e nao um log append-only.** O
`optout_events` resolve o problema vizinho pelo caminho oposto, e a D1 do
desenho explica a divergencia: la o append-only existe porque a LGPD exige o
registro como prova, e nada precisa recusar um segundo opt-out. Aqui o SRS
especifica 409 "ja assumida por outro", e essa recusa tem de ser arbitrada
pelo banco. O UNIQUE abaixo e o arbitro.

**Nao ha coluna `ativo`.** Silenciada e `devolvido_em IS NULL`. Uma booleana
ao lado dos carimbos seria uma segunda representacao do mesmo fato -- e duas
colunas que dizem o mesmo divergem, como `notificado_em` e
`aviso_manual_pendente` divergiam antes da revisao final da TEC-177.

**`assumido_por` e NOT NULL, `devolvido_por` e nulavel.** Nao ha linha sem
alguem tendo assumido: a linha nasce do ato de assumir. Devolver e o ato
posterior que pode nao ter acontecido ainda.

As duas FK apontam para `corretores.id` (TEC-196). Sem `ondelete`: apagar
corretor com conversa atribuida deve reprovar, nao apagar o registro de quem
atendeu.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "atendimento_humano",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column(
            "assumido_por",
            PgUUID(as_uuid=True),
            sa.ForeignKey("corretores.id", name="fk_atendimento_assumido_por"),
            nullable=False,
        ),
        sa.Column("assumido_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "devolvido_por",
            PgUUID(as_uuid=True),
            sa.ForeignKey("corretores.id", name="fk_atendimento_devolvido_por"),
            nullable=True,
        ),
        sa.Column("devolvido_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("channel", "conversation_key", name="uq_atendimento_conversa"),
    )


def downgrade() -> None:
    op.drop_table("atendimento_humano")

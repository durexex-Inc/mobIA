"""o registro de handoff: o ponto de juncao entre o agente e o time humano

TEC-174, RF-16 e RN-16.1.

**Chaveada pelo par `(channel, conversation_key)`.** O modelo da secao 5 do SRS
pede `conversa_id UUID FK -> Conversa`, e `Conversa` nao existe: a entidade foi
deferida para a TEC-130, e `lead_qualification`, `followups`, `optout_events`,
`moderation_events` e `recomendacoes` usam todas o par. A emenda E-03 da secao 5
declara a divergencia.

**Primeira tabela mutavel do repo.** `followups`, `optout_events` e
`moderation_events` sao append-only. Esta nao pode ser: a regra de deduplicacao
da card manda ATUALIZAR o handoff aberto em vez de criar outro. Dai
`atualizado_em`, que as append-only nao tem.

**O UNIQUE e PARCIAL, e e o coracao da card.** `WHERE status = 'PENDENTE'` faz
"um handoff aberto por conversa" ser invariante de schema em vez de disciplina
de consulta -- e deixa um handoff CONCLUIDO nao bloquear um novo, porque um lead
atendido meses atras que volta merece handoff proprio. E o primeiro indice
parcial do repo.

**`corretor_id` sem FK, e sem tabela alvo.** `corretores` nasce na TEC-196; a
restricao entra junto com ela. E ausencia de FK PROVISORIA, ao contrario da de
`moderation_events` e `lead_score_audit`, que e permanente e tem outra causa --
la a FK e dispensada porque a retencao da trilha nao pode ser encurtada pela
cascata da limpeza de `messages`. Ver a emenda E-02 da RN-16.1.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "handoffs",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("gatilho", sa.String(32), nullable=False),
        sa.Column("etiqueta", sa.String(32), nullable=False),
        sa.Column("prioridade", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("corretor_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column(
            "gatilhos_adicionais",
            sa.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_handoffs"),
        sa.CheckConstraint("prioridade IN ('ALTA', 'NORMAL')", name="ck_handoffs_prioridade"),
        sa.CheckConstraint(
            "status IN ('PENDENTE', 'ACEITO', 'ESCALADO', 'CONCLUIDO')",
            name="ck_handoffs_status",
        ),
    )
    op.create_index(
        "uq_handoffs_conversa_pendente",
        "handoffs",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDENTE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_handoffs_conversa_pendente", table_name="handoffs")
    op.drop_table("handoffs")

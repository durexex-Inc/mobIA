"""trilha append-only e imutavel dos recalculos de score

TEC-152, RN-06.4. Uma linha por recalculo que mudou o resultado.

Sem FK para `messages` nem para `lead_qualification`, pela razao da 0010: a
retencao da trilha (12 meses, RNF-18) nao pode ser encurtada por cascata da
limpeza de outra tabela.

O CHECK existe porque `total_novo` e denormalizado de proposito -- e por ele
que se ordena e se filtra --, e sem a restricao um fator esquecido na soma
produz uma trilha que parece consistente e nao e.

**`clock_timestamp()` e nao `now()`.** `now()` e `transaction_timestamp()`,
congelado no primeiro statement da transacao; o INSERT desta tabela acontece no
fim de um turno longo, varios statements depois desse primeiro. Dois turnos
concorrentes da mesma conversa seriam entao carimbados pela ordem em que
COMECARAM, e nao pela ordem em que gravaram -- o que a linha de `FOR UPDATE`
serializa --, e a trilha sairia ao contrario. Como o INSERT ocorre com o lock
de `lead_qualification` na mao, `clock_timestamp()` da uma ordem total igual a
ordem do lock.

**A trigger recusa UPDATE e nao DELETE.** Imutavel significa "nao se altera o
que foi registrado"; expurgo por politica de retencao e ato deliberado, nao
alteracao -- e a RNF-18, que pede 12 meses, pede que apagar seja possivel.
Bloquear os dois obrigaria a retencao a passar por um caminho privilegiado que
nao existe neste repo.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_FUNCAO_DA_TRIGGER = """
CREATE FUNCTION lead_score_audit_recusa_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'lead_score_audit e imutavel: UPDATE recusado';
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER = """
CREATE TRIGGER lead_score_audit_imutavel
    BEFORE UPDATE ON lead_score_audit
    FOR EACH ROW EXECUTE FUNCTION lead_score_audit_recusa_update()
"""


def upgrade() -> None:
    op.create_table(
        "lead_score_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("total_anterior", sa.Integer(), nullable=True),
        sa.Column("total_novo", sa.Integer(), nullable=False),
        sa.Column("completude", sa.Integer(), nullable=False),
        sa.Column("urgencia", sa.Integer(), nullable=False),
        sa.Column("catalogo", sa.Integer(), nullable=False),
        sa.Column("engajamento", sa.Integer(), nullable=False),
        sa.Column("capacidade", sa.Integer(), nullable=False),
        sa.Column("causas", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("autor", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "total_novo = completude + urgencia + catalogo + engajamento + capacidade",
            name="ck_lead_score_audit_total",
        ),
    )
    op.create_index(
        "ix_lead_score_audit_lead",
        "lead_score_audit",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )
    op.execute(_FUNCAO_DA_TRIGGER)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS lead_score_audit_imutavel ON lead_score_audit")
    op.execute("DROP FUNCTION IF EXISTS lead_score_audit_recusa_update()")
    op.drop_index("ix_lead_score_audit_lead", table_name="lead_score_audit")
    op.drop_table("lead_score_audit")

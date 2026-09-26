"""trilha append-only das mudancas de intencao acumulada

TEC-136, RN-03.3. Uma linha por mudanca de `lead_qualification.intencao`.

Sem FK para `lead_qualification`, pela razao da 0010 e da 0012: a retencao
desta trilha nao pode ser encurtada por cascata da limpeza de outra tabela.

`clock_timestamp()` e nao `now()` pelo argumento que a 0012 escreve por
extenso -- o INSERT acontece com o lock de `lead_qualification` na mao, varios
statements depois do primeiro da transacao, e `now()` carimbaria pela ordem em
que os turnos COMECARAM.

A trigger recusa UPDATE e nao DELETE, como a da 0012 e pela mesma razao:
imutavel significa "nao se altera o que foi registrado", e expurgo por politica
de retencao e ato deliberado.

Sem CHECK ligando `faixa_descartada` a `de`/`para`: a regra de banda mora em
`dinheiro.py` e transcreve-la para uma restricao do banco criaria a segunda
copia que o proprio `mudou_de_banda` existe para evitar.

**Excecao (TEC-203):** a reindexacao do lead desliga esta trigger na propria
transacao para trocar o pseudonimo do lead -- ver `domain/identidade/reindexacao.py`.
Trocar o pseudonimo nao altera o fato registrado.

E aqui a troca e tambem a que tira o telefone em claro da trilha: antes
da 0058, `conversation_key` guardava o `wa_id`.

Revision ID: 0035
Revises: 0034
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_FUNCAO_DA_TRIGGER = """
CREATE FUNCTION conversation_intent_audit_recusa_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'conversation_intent_audit e imutavel: UPDATE recusado';
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER = """
CREATE TRIGGER conversation_intent_audit_imutavel
    BEFORE UPDATE ON conversation_intent_audit
    FOR EACH ROW EXECUTE FUNCTION conversation_intent_audit_recusa_update()
"""


def upgrade() -> None:
    op.create_table(
        "conversation_intent_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("de", sa.String(16), nullable=True),
        sa.Column("para", sa.String(16), nullable=False),
        sa.Column("faixa_descartada", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
    )
    op.create_index(
        "ix_conversation_intent_audit_conversa",
        "conversation_intent_audit",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )
    op.execute(_FUNCAO_DA_TRIGGER)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS conversation_intent_audit_imutavel ON conversation_intent_audit"
    )
    op.execute("DROP FUNCTION IF EXISTS conversation_intent_audit_recusa_update()")
    op.drop_index("ix_conversation_intent_audit_conversa", table_name="conversation_intent_audit")
    op.drop_table("conversation_intent_audit")

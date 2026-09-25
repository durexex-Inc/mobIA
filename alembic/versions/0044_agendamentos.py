"""os agendamentos, e a exclusao por intervalo que impede dois no mesmo horario

TEC-168, RN-11.4, RT-07.

**A garantia do RT-07 e esta constraint, e nao o codigo.** `EXCLUDE USING
gist` recusa, na mesma transacao que tenta gravar, qualquer par de linhas do
mesmo corretor cujos intervalos se sobreponham -- inclusive duas transacoes
concorrentes: a segunda espera a primeira e reprova se ela commitar.

**`'[)'`: encostar nao conflita.** 10h-11h convive com 11h-12h, a mesma regra
do motor de janelas da TEC-165.

**O WHERE tira EXPIRADO, e nao olha o relogio.** Predicado de constraint tem
de ser imutavel e `now()` nao e; a reserva vencida sai da exclusao quando o
repositorio a marca EXPIRADO, antes de gravar por cima (D3 do desenho).

**`btree_gist` e o que deixa `corretor_id WITH =` entrar num indice gist.**
Como o `vector` da 0017, o downgrade nao a remove: outra coisa pode ter
passado a depender dela.

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "agendamentos",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("corretor_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("imovel_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("tipo", sa.String(24), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reservado_ate", sa.DateTime(timezone=True), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmado_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_agendamentos"),
        sa.ForeignKeyConstraint(
            ["corretor_id"], ["corretores.id"], name="fk_agendamentos_corretor"
        ),
        sa.ForeignKeyConstraint(["imovel_id"], ["imoveis.id"], name="fk_agendamentos_imovel"),
        sa.CheckConstraint(
            "tipo IN ('VISITA_PRESENCIAL','REUNIAO_REMOTA')", name="ck_agendamentos_tipo"
        ),
        sa.CheckConstraint(
            "status IN ('RESERVADO','CONFIRMADO','EXPIRADO')", name="ck_agendamentos_status"
        ),
        sa.CheckConstraint("inicio < fim", name="ck_agendamentos_intervalo"),
    )
    op.execute(
        "ALTER TABLE agendamentos ADD CONSTRAINT ex_agendamentos_sem_sobreposicao"
        " EXCLUDE USING gist (corretor_id WITH =, tstzrange(inicio, fim, '[)') WITH &&)"
        " WHERE (status IN ('RESERVADO', 'CONFIRMADO'))"
    )
    op.create_index("ix_agendamentos_conversa", "agendamentos", ["channel", "conversation_key"])


def downgrade() -> None:
    op.drop_table("agendamentos")

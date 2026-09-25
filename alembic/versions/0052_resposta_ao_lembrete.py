"""a presenca que o lead confirma, e a remarcacao em curso

TEC-372, D3 e D4. Duas colunas nulas, uma em cada tabela do agendamento.

**`presenca_confirmada_em` nao e status, e nao muda `status`.** `CONFIRMADO`
ja e o estado do compromisso; presenca confirmada e fato sobre o LEAD. Junta-
los exigiria um `PRESENCA_CONFIRMADA` no CHECK que toda consulta teria de
lembrar de incluir -- a mesma entrada morta de vocabulario que a 0050 recusou
para `PROPOSTO`.

**Nulo e "o lead nao respondeu", e nao "nao vai".** Mesma distincao das
colunas de aviso da 0047: ausencia de fato, nao fato negativo. Quem contar
no-show precisa dos dois separados -- quem confirmou e faltou e outra
historia que quem nunca respondeu.

**`remarcando_id` e o que da destino a uma rodada de propostas.** Nula, a
escolha do lead vira reserva (TEC-371); preenchida, vira
`ciclo.py::remarcar` sobre aquele agendamento. Uma coluna na tabela que ja
existe, e nao uma tabela nova: sao as mesmas propostas, com outro desfecho.

**Nenhuma das duas entra na exclusao por intervalo** (0044): presenca e
remarcacao em curso nao disputam horario com ninguem.

Revision ID: 0052
Revises: 0051
"""

import sqlalchemy as sa

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agendamentos",
        sa.Column("presenca_confirmada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("janelas_propostas", sa.Column("remarcando_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_janelas_propostas_remarcando",
        "janelas_propostas",
        "agendamentos",
        ["remarcando_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_janelas_propostas_remarcando", "janelas_propostas", type_="foreignkey")
    op.drop_column("janelas_propostas", "remarcando_id")
    op.drop_column("agendamentos", "presenca_confirmada_em")

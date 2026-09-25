"""o registro de cada lembrete ja resolvido do agendamento

TEC-171, D3. Uma coluna por lembrete da RN-12.2 -- 24 horas antes e 2 horas
antes --, e e ela que a varredura le para nao mandar o mesmo lembrete duas
vezes.

**Nula quer dizer "ainda nao resolvido", e nao "nao entregue".** Quem registra
entrega e a linha em `outbound_dispatches`, com o kind deste agendamento e
deste lembrete. A coluna e gravada em dois desfechos -- o envio aceito e o
envio recusado pela guarda (opt-out, atendimento humano) --, e fica nula so
quando o canal falhou, que e o caso em que a passagem seguinte deve tentar de
novo.

**E aqui esta a divergencia deliberada em relacao a 0047** (TEC-170), cujas
tres colunas ficam nulas tambem na recusa da guarda. La o job roda uma vez por
enfileiramento e o nulo nao custa nada; aqui quem chama e um `cron` de cinco em
cinco minutos, e deixar nulo produziria uma tentativa barrada a cada cinco
minutos por ate vinte e duas horas -- centenas de linhas de
`outbound.optout_bloqueou` por um lembrete que nunca vai sair. A guarda ja
respondeu; repetir a pergunta nao muda a resposta.

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agendamentos", sa.Column("lembrete_24h_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agendamentos", sa.Column("lembrete_2h_em", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agendamentos", "lembrete_2h_em")
    op.drop_column("agendamentos", "lembrete_24h_em")

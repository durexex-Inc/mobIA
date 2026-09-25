"""o ciclo de vida inteiro do agendamento, e a penalidade de score

TEC-172, D9. Quatro status novos (`CANCELADO`, `REAGENDADO`, `REALIZADO`,
`NO_SHOW`), o vinculo da remarcacao, os carimbos de cada desfecho, e a
penalidade que o nao comparecimento cobra do lead.

**A constraint de exclusao NAO aparece aqui, e a ausencia e o ponto.** Parece
que `ex_agendamentos_sem_sobreposicao` (migration 0044) precisaria crescer com
o vocabulario, e o contrario e que e verdade: ela ja e allowlist --
`WHERE (status IN ('RESERVADO','CONFIRMADO'))` --, entao cada status novo
nasce FORA dela sem que ninguem decida nada. E e isso que libera o slot: o
UPDATE que poe `CANCELADO` tira a linha do indice no mesmo statement, e o
horario fica livre no commit. Quem "consertar" aquele WHERE para incluir os
status novos mata a CA-12.2 em silencio.

`REALIZADO` e `NO_SHOW` tambem ficam de fora dela, e tambem esta certo: sao
fatos do passado, e compromisso passado nao disputa horario com ninguem.

**`DEFAULT 0` nas duas colunas de penalidade significa FATO, e nao ausencia de
fato** -- e a distincao oposta a das colunas nulaveis da 0047 e da 0049, onde
nulo e o registro de que o passo nao aconteceu. Aqui a linha antiga quer dizer
"nunca foi penalizado", que e exatamente zero; um nulo obrigaria todo leitor a
decidir o que ele significa, e `Score.total` teria de tratar o caso.

Revision ID: 0050
Revises: 0049
"""

import sqlalchemy as sa

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

# O CHECK e recriado inteiro: o Postgres nao altera constraint no lugar.
_STATUS_ANTIGOS = "'RESERVADO','CONFIRMADO','EXPIRADO'"
_STATUS_NOVOS = "'RESERVADO','CONFIRMADO','EXPIRADO','CANCELADO','REAGENDADO','REALIZADO','NO_SHOW'"


def upgrade() -> None:
    op.add_column("agendamentos", sa.Column("origem_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agendamentos_origem", "agendamentos", "agendamentos", ["origem_id"], ["id"]
    )
    for coluna in (
        "cancelado_em",
        "realizado_em",
        "nao_compareceu_em",
        "remarcacao_convidada_em",
        "corretor_avisado_do_cancelamento_em",
    ):
        op.add_column("agendamentos", sa.Column(coluna, sa.DateTime(timezone=True), nullable=True))

    op.drop_constraint("ck_agendamentos_status", "agendamentos", type_="check")
    op.create_check_constraint(
        "ck_agendamentos_status", "agendamentos", f"status IN ({_STATUS_NOVOS})"
    )

    op.add_column(
        "lead_qualification",
        sa.Column("penalidade_pontos", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "lead_score_audit",
        sa.Column("penalidade", sa.Integer(), nullable=False, server_default="0"),
    )
    # O CHECK da 0012 afirmava que o total e a soma dos cinco fatores, e
    # deixou de ser verdade: o sexto SUBTRAI, e `Score.total` corta em zero.
    # **Recriar em vez de apagar** -- a garantia que ele da e que o total
    # gravado e DERIVAVEL dos fatores gravados, e e justamente ela que a
    # penalidade poderia quebrar em silencio se a coluna fosse esquecida em
    # algum caminho de escrita. O `GREATEST` espelha o piso de `Score.total`.
    op.drop_constraint("ck_lead_score_audit_total", "lead_score_audit", type_="check")
    op.create_check_constraint(
        "ck_lead_score_audit_total",
        "lead_score_audit",
        "total_novo = GREATEST(0, completude + urgencia + catalogo"
        " + engajamento + capacidade - penalidade)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_lead_score_audit_total", "lead_score_audit", type_="check")
    op.execute("DELETE FROM lead_score_audit WHERE penalidade <> 0")
    op.create_check_constraint(
        "ck_lead_score_audit_total",
        "lead_score_audit",
        "total_novo = completude + urgencia + catalogo + engajamento + capacidade",
    )
    op.drop_column("lead_score_audit", "penalidade")
    op.drop_column("lead_qualification", "penalidade_pontos")

    # As linhas com status novo nao cabem no CHECK antigo. Voltam para
    # CANCELADO -> EXPIRADO e o resto -> CONFIRMADO, que e o estado mais
    # proximo que o vocabulario antigo sabe dizer. A volta perde informacao,
    # e nao ha como nao perder: o downgrade desfaz o vocabulario que a
    # distinguia.
    op.execute("UPDATE agendamentos SET status = 'EXPIRADO' WHERE status = 'CANCELADO'")
    op.execute(
        "UPDATE agendamentos SET status = 'CONFIRMADO'"
        " WHERE status IN ('REAGENDADO','REALIZADO','NO_SHOW')"
    )
    op.drop_constraint("ck_agendamentos_status", "agendamentos", type_="check")
    op.create_check_constraint(
        "ck_agendamentos_status", "agendamentos", f"status IN ({_STATUS_ANTIGOS})"
    )

    for coluna in (
        "corretor_avisado_do_cancelamento_em",
        "remarcacao_convidada_em",
        "nao_compareceu_em",
        "realizado_em",
        "cancelado_em",
    ):
        op.drop_column("agendamentos", coluna)
    op.drop_constraint("fk_agendamentos_origem", "agendamentos", type_="foreignkey")
    op.drop_column("agendamentos", "origem_id")

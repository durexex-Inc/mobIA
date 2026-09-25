"""a fila de quem pediu visita numa semana sem horario livre

TEC-169, RN-11.5. Sem janela nas proximas 72 horas o agente oferece a lista de
espera; aceita, o lead entra nesta tabela e um handoff abre para o corretor
propor horario a mao.

**Quatro marcas nulas, e nenhuma coluna de status.** E o molde que a TEC-170, a
TEC-171 e a TEC-372 firmaram: nula significa "nao aconteceu", nunca um fato
negativo. Um `status` de quatro valores teria de ser mantido em sincronia com
as datas -- e dois relogios divergem, que e o argumento que a 0051 escreve por
extenso sobre `expira_em`.

**`aceita_em` e o que ordena a fila, e nao `oferecida_em`.** A card diz que o
lead "entra na lista com o momento de entrada registrado", e entrar e ACEITAR:
quem recebeu a oferta e nao respondeu nao esta na fila. Ordenar pela oferta
poria na frente quem nunca disse sim.

**`avisada_em` tira da fila, tenha o lead respondido ou nao.** E o que impede o
primeiro da fila de trava-la: o slot seguinte vai para o proximo. Quem foi
avisado e ainda quer visita pede de novo e entra com `aceita_em` de agora,
atras de quem esperou mais.

Revision ID: 0054
Revises: 0053
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lista_de_espera",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        # O par que identifica o lead, o mesmo de `lead_qualification`.
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        # Nulo: o lead pode pedir visita sem ter imovel em vista, e a fila
        # continua valendo -- o corretor e quem propoe o que mostrar.
        sa.Column("imovel_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("oferecida_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aceita_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recusada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("avisada_em", sa.DateTime(timezone=True), nullable=True),
        # QUAL slot liberado gerou o aviso. E o que pareia cancelamento e lead
        # um-para-um: a varredura so usa um cancelamento que ainda nao
        # aparece nesta coluna, e por isso um slot avisa UM lead, e nao a
        # fila inteira (D7). A marca mora aqui, e nao em `agendamentos`,
        # porque e um fato sobre a fila e nao sobre o compromisso cancelado.
        sa.Column("avisada_por_agendamento_id", PgUUID(as_uuid=True), nullable=True),
        # Preenchida no aceite, e so entao: a oferta sozinha nao abre handoff,
        # porque um lead que nao respondeu nao pediu nada ao corretor.
        sa.Column("handoff_id", PgUUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_lista_de_espera"),
        sa.ForeignKeyConstraint(["imovel_id"], ["imoveis.id"], name="fk_lista_de_espera_imovel"),
        sa.ForeignKeyConstraint(["handoff_id"], ["handoffs.id"], name="fk_lista_de_espera_handoff"),
        sa.ForeignKeyConstraint(
            ["avisada_por_agendamento_id"],
            ["agendamentos.id"],
            name="fk_lista_de_espera_avisada_por",
        ),
        # Um slot liberado avisa no maximo um lead. O UNIQUE e o que
        # transforma a D7 em garantia de schema em vez de disciplina de
        # consulta -- duas passagens concorrentes da varredura nao podem
        # gastar o mesmo cancelamento em dois leads.
        sa.UniqueConstraint(
            "avisada_por_agendamento_id", name="uq_lista_de_espera_um_aviso_por_slot"
        ),
        # Aceitar o que nunca foi oferecido, ou recusar e aceitar a mesma
        # oferta, sao estados que o codigo nao produz -- e o CHECK e o que
        # impede que passem a existir sem ninguem notar.
        sa.CheckConstraint(
            "NOT (aceita_em IS NOT NULL AND recusada_em IS NOT NULL)",
            name="ck_lista_de_espera_desfecho_unico",
        ),
        sa.CheckConstraint(
            "avisada_em IS NULL OR aceita_em IS NOT NULL",
            name="ck_lista_de_espera_aviso_pressupoe_aceite",
        ),
    )

    # Uma linha VIVA por conversa: a oferta ainda de pe, ou o lugar na fila.
    # Sem isto, um lead que pede visita tres vezes numa semana lotada ocupa
    # tres posicoes da mesma fila.
    #
    # O predicado tem de casar EXATAMENTE com o `postgresql_where` do Index em
    # `domain/agendamento/models.py` -- e ele que diz ao Postgres qual indice
    # parcial usar, e a licao esta escrita por extenso no `ON CONFLICT` de
    # `domain/handoff/repositorio.py`.
    op.create_index(
        "uq_lista_de_espera_conversa_viva",
        "lista_de_espera",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("recusada_em IS NULL AND avisada_em IS NULL"),
    )

    # A consulta da varredura do slot liberado, que roda a cada passagem: o
    # primeiro da fila por ordem de entrada, entre os que ainda nao foram
    # avisados.
    op.create_index(
        "ix_lista_de_espera_fila",
        "lista_de_espera",
        ["aceita_em"],
        postgresql_where=sa.text("aceita_em IS NOT NULL AND avisada_em IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_lista_de_espera_fila", table_name="lista_de_espera")
    op.drop_index("uq_lista_de_espera_conversa_viva", table_name="lista_de_espera")
    op.drop_table("lista_de_espera")

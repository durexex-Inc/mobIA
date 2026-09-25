"""as janelas que o agente ofereceu ao lead, para que o ordinal tenha a que se referir

TEC-371, D4. A conversa que marca visita leva tres turnos -- oferecer,
escolher, confirmar --, e o turno da escolha precisa saber o que o turno da
oferta disse.

**Recalcular no lugar de gravar parece equivalente e nao e.** As janelas sao
funcao de `agora`: a grade e de 30 minutos e a antecedencia minima e de 3
horas, entao a rodada das 10h00 propoe 13h00 e a das 10h03 propoe 13h30. Tres
minutos de digitacao depois, o lead que responde "13h" receberia "nao
encontrei esse horario" sobre um horario que NOS acabamos de oferecer.
Gravar e o que faz o ordinal e a hora se referirem ao que foi dito.

E o mesmo problema que `recomendacoes` (TEC-163) resolve do mesmo jeito: o
imovel apresentado fica gravado para que "gostei do segundo" (CA-10.1) tenha
a que se referir.

**Sem coluna de validade, e a ausencia e deliberada.** Quem valida e o relogio
contra `inicio`: proposta cujo comeco ja passou de `agora + ANTECEDENCIA_MINIMA`
e tratada como inexistente, e a resposta e uma rodada nova. Uma coluna
`expira_em` seria um segundo relogio para manter em sincronia com o primeiro,
e dois relogios divergem.

**Nao entra na exclusao por intervalo da 0044, e nao deve entrar.** Proposta
nao reserva nada: tres leads podem receber a mesma janela, e quem chegar
primeiro no `reservar` fica com ela. E a CA-11.2 funcionando, nao um furo.

Revision ID: 0051
Revises: 0050
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "janelas_propostas",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        # 1..3, a posicao na frase que o lead leu. O teto e `MAXIMO_DE_JANELAS`
        # (`agendamento/janelas.py`), e o CHECK o repete em SQL porque o banco
        # nao importa Python -- ordinal 0 ou 4 seria um ordinal que nenhum
        # texto ao lead produziu.
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("corretor_id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("imovel_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("tipo", sa.String(24), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=False),
        # O que `alocar` (TEC-166) deu a este corretor. Viaja com a proposta
        # para que a reserva o grave sem realocar: realocar na hora de
        # reservar trocaria o corretor entre o que o lead leu e o que ele
        # recebe.
        sa.Column("motivo_da_alocacao", sa.String(24), nullable=False),
        sa.Column("proposto_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_janelas_propostas"),
        sa.ForeignKeyConstraint(
            ["corretor_id"], ["corretores.id"], name="fk_janelas_propostas_corretor"
        ),
        sa.ForeignKeyConstraint(["imovel_id"], ["imoveis.id"], name="fk_janelas_propostas_imovel"),
        sa.CheckConstraint(
            "tipo IN ('VISITA_PRESENCIAL','REUNIAO_REMOTA')", name="ck_janelas_propostas_tipo"
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 3", name="ck_janelas_propostas_ordinal"),
        sa.CheckConstraint("inicio < fim", name="ck_janelas_propostas_intervalo"),
        # Uma rodada substitui a anterior, e este UNIQUE e o que transforma
        # essa regra em garantia de schema em vez de disciplina de consulta --
        # o mesmo papel do UNIQUE de `recomendacoes`. Duas rodadas vivas ao
        # mesmo tempo dariam dois significados ao ordinal 2.
        sa.UniqueConstraint(
            "channel", "conversation_key", "ordinal", name="uq_janelas_propostas_conversa_ordinal"
        ),
    )


def downgrade() -> None:
    op.drop_table("janelas_propostas")

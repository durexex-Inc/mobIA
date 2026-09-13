"""o corretor, e a chave estrangeira que a TEC-174 prometeu por escrito

TEC-196, RF-19 e RN-19.2.

**O contato fica EM CLARO, contra a regra dos campos DP do SRS.** Ver a
emenda E-01 do modelo Corretor. Duas razoes: este repo cifra CONTEUDO e nao
IDENTIFICADOR -- `messages.conversation_key` guarda o telefone do proprio
titular em claro --, e cifrar destruiria o `uq_corretores_email`, porque o
nonce aleatorio do AES-GCM faz a busca por igualdade deixar de existir, por
desenho. Sem esse UNIQUE nao ha defesa contra corretor duplicado, e a
notificacao da RN-16.2 sairia dobrada.

**A jornada e uma janela de horas inteiras, e nao `jsonb` por dia.** Emenda
E-02 do mesmo modelo: e a forma que `app/config.py` ja usa para janela de
atendimento. Sabado meio periodo nao cabe, e isso esta declarado.

**A FK de `handoffs.corretor_id` entra aqui.** A emenda E-02 da RN-16.1
escreveu, na TEC-174, que "a TEC-196 acrescenta a restricao quando criar a
tabela". Esta e a card. `ON DELETE RESTRICT` (o default) porque corretor se
desativa por `ativo = false` e nunca se apaga: a cascata nao tem caso de uso,
e apagar por engano deve doer. A coluna continua NULAVEL, agora por outra
razao -- nao falta mais tabela alvo, falta quem aloque, e alocar e a TEC-166.

Revision ID: 0025
Revises: 0024

**Renumerada de 0024 para 0025 na TEC-177.** Esta migration e a
`0024_resumo_do_handoff` nasceram em branches irmas, as duas com
`down_revision = "0023"`, porque as duas sairam da mesma `main`. Duas
cabecas fazem `alembic upgrade head` reprovar. A ordem escolhida segue a dos
PRs: o resumo (TEC-175) entra primeiro, o cadastro de corretores depois.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corretores",
        sa.Column("id", PgUUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("email", sa.String(160), nullable=False),
        sa.Column("telefone", sa.String(20), nullable=False),
        sa.Column("creci", sa.String(20), nullable=True),
        sa.Column("especialidades", sa.ARRAY(sa.String(28)), nullable=False),
        sa.Column("regioes_atuacao", sa.ARRAY(sa.String(120)), nullable=False),
        sa.Column("horario_inicio", sa.SmallInteger(), nullable=False),
        sa.Column("horario_fim", sa.SmallInteger(), nullable=False),
        sa.Column("capacidade_diaria", sa.SmallInteger(), nullable=False),
        sa.Column("plantao", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_corretores"),
        sa.UniqueConstraint("email", name="uq_corretores_email"),
        sa.CheckConstraint(
            "horario_inicio >= 0 AND horario_fim <= 23 AND horario_inicio < horario_fim",
            name="ck_corretores_jornada",
        ),
        sa.CheckConstraint("capacidade_diaria >= 1", name="ck_corretores_capacidade"),
        sa.CheckConstraint(
            "cardinality(especialidades) > 0 AND especialidades <@ ARRAY["
            "'COMPRA','ALUGUEL','INVESTIMENTO','INVESTIMENTO_ALTO_TICKET']::varchar[]",
            name="ck_corretores_especialidades",
        ),
        sa.CheckConstraint("cardinality(regioes_atuacao) > 0", name="ck_corretores_regioes"),
    )
    op.create_foreign_key("fk_handoffs_corretor", "handoffs", "corretores", ["corretor_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_handoffs_corretor", "handoffs", type_="foreignkey")
    op.drop_table("corretores")

"""o prazo e o aceite do handoff, e a marcacao de gerente no corretor

TEC-178, RF-16 e RN-16.3.

**`sla_limite_em` e NULAVEL, contra o "Sim" do modelo da secao 5 do SRS.** A
emenda E-01 da RN-16.3 declara o porque: o prazo conta dentro da JORNADA do
corretor DESTINATARIO (`handoff.sla.limite_de_aceite`), e esse destinatario
so e conhecido no job de notificacao (TEC-177) -- nao na criacao do handoff,
que e sincrona com o turno do lead. A coluna e gravada alguns segundos
depois, no mesmo job que grava `notificado_em`, e fica nula nesse intervalo.
Fica nula PARA SEMPRE no handoff sem destinatario, que escala na hora e nao
tem prazo porque nao ha a quem cobrar (emenda E-02 da mesma RN). NULO
significa "ainda nao notificado" ou "nao havia a quem cobrar" -- NUNCA
"prazo zero". Mesmo raciocinio de `notificado_em` na 0026, que tambem fica
nulo por construcao e nao por defeito.

**`aceito_em` e NULAVEL** pela razao mais simples: so existe depois que
alguem aceita, e a maioria dos handoffs passa a maior parte da vida sem
essa linha preenchida -- PENDENTE, ESCALADO e CONCLUIDO-sem-aceite-formal
nunca a tem.

**`gerente` nasce FALSO**, mesma razao de `plantao` na 0025_corretores.py:
verdadeiro faria todo corretor cadastrado virar gerente, e a fila de
escalonamento (consumidora futura desta coluna) trataria o cadastro inteiro
como alvo de cobranca.

**`gerente` e `plantao` sao INDEPENDENTES, nao excludentes -- de proposito,
sem CHECK impedindo a combinacao.** Uma imobiliaria pequena tem a mesma
pessoa nos dois papeis: quem cobre plantao tambem pode ser quem recebe a
escalada de SLA. Um CHECK de exclusividade inventaria uma regra que nem o
SRS nem a RN-16.3 escrevem.

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("handoffs", sa.Column("sla_limite_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("handoffs", sa.Column("aceito_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "corretores",
        sa.Column(
            "gerente",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("corretores", "gerente")
    op.drop_column("handoffs", "aceito_em")
    op.drop_column("handoffs", "sla_limite_em")

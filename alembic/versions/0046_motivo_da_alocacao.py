"""o motivo da alocacao do corretor, gravado no agendamento

TEC-166, RN-11.2. A gerente precisa entender por que aquele corretor foi
escolhido; a categoria mora ao lado do agendamento que ela vai olhar.

**NOT NULL sem valor padrao, e sem backfill.** Nenhum caminho de producao
grava em `agendamentos` ate esta card -- `reservar` nao tem chamador fora dos
testes --, entao nao ha linha antiga para receber um motivo inventado. Se um
dia esta migration encontrar linha, o `ADD COLUMN` reprova, e isso e o certo:
motivo inventado seria pior que a falha.

**Nasceu 0045 e virou 0046 na TEC-370, e a razao fica aqui.** A TEC-166
(esta) e a TEC-201 (`0045_usuarios_e_sessoes.py`) sairam de `0044` em branches
paralelas e as duas se numeraram `0045` -- a segunda vez que isso acontece em
dois dias, depois da colisao de `0044` entre a TEC-168 e a TEC-201. Esta e a
renumerada por ter mergeado por ultimo (PR #171, depois do #170).

Apontar para `0045` em vez de `0044` nao muda nada do que esta migration faz:
ela so acrescenta coluna em `agendamentos`, que a `0044` criou, e a `0045`
mexe em outras tabelas. O que muda e a arvore ter uma cabeca so.

Desde a TEC-370, `tests/unit/test_uma_cabeca_de_migration.py` reprova quando
duas migrations dividem revisao ou cabeca -- no PR, e nao depois do merge.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agendamentos", sa.Column("motivo_da_alocacao", sa.String(24), nullable=False))
    op.create_check_constraint(
        "ck_agendamentos_motivo_da_alocacao",
        "agendamentos",
        "motivo_da_alocacao IN ('MATCH_EXATO','SEM_MATCH','MATCH_SEM_CAPACIDADE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agendamentos_motivo_da_alocacao", "agendamentos", type_="check")
    op.drop_column("agendamentos", "motivo_da_alocacao")

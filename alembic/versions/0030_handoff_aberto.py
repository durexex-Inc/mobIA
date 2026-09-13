"""o handoff bloqueia a conversa ate ser concluido, nao ate sair de PENDENTE

TEC-278, RF-16.

**Por que o predicado muda.** O indice nasceu na 0023 cobrindo
`status = 'PENDENTE'`, e a L4 do desenho da TEC-174 registrou o porque: nada
tirava handoff de PENDENTE, entao o indice "nunca libera a conversa enquanto a
TEC-178 nao existir -- e e o comportamento certo". A TEC-178 e a TEC-179
chegaram. Um handoff que vira ACEITO ou ESCALADO passou a liberar a chave, e o
proximo gatilho de intencao -- que dispara em TODO turno com a classificacao
certa -- inseria um handoff novo, com resumo novo (chamada paga ao provedor) e
prazo novo. Cinco minutos depois a varredura cobrava a gerente de novo, pelo
mesmo lead.

**Por que `<> 'CONCLUIDO'` e nao um UNIQUE simples.** Um lead atendido meses
atras que volta merece handoff novo. O que separa "aberto" de "encerrado"
passa a ser CONCLUIDO -- que ate a TEC-278 nao tinha escritor nenhum, e ganha
o primeiro em `POST /api/v1/conversas/devolver`. Sem aquele escritor este
indice prenderia cada conversa ao primeiro handoff dela para sempre.

**Drop e create, porque o Postgres nao altera predicado de indice parcial.** O
nome fica como estava: ele aparece em comentario e na migration 0023, e
renomear seria churn.

**A criacao REPROVA se existir conversa com dois handoffs abertos**, e isso e
deliberado (L4 do desenho). Esse estado e o que esta card declara impossivel;
descobri-lo aqui e melhor que descobri-lo depois. Nao ha limpeza silenciosa.
"""

import sqlalchemy as sa

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_NOME = "uq_handoffs_conversa_pendente"


def upgrade() -> None:
    op.drop_index(_NOME, table_name="handoffs")
    op.create_index(
        _NOME,
        "handoffs",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'CONCLUIDO'"),
    )


def downgrade() -> None:
    op.drop_index(_NOME, table_name="handoffs")
    op.create_index(
        _NOME,
        "handoffs",
        ["channel", "conversation_key"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDENTE'"),
    )

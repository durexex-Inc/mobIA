"""o modelo que gerou o vetor vira coluna

TEC-157, RN-08.3. A `0017` deixou a pendencia derivavel do estado da linha
para mudanca de TEXTO; esta fecha a mesma pergunta para mudanca de
CONFIGURACAO.

**O buraco que ela tapa.** O hash do documento passou a cobrir modelo e
dimensao, mas o pre-filtro da varredura seleciona por `embedding IS NULL OR
documento_hash IS NULL OR embedding_atualizado_em IS NULL OR updated_at >
embedding_atualizado_em` -- nenhuma clausula de hash, de proposito (D3: a
lista de campos nao se duplica em SQL). Uma linha ja indexada cuja UNICA
mudanca e o modelo na configuracao tem as tres colunas preenchidas e
`updated_at <= embedding_atualizado_em`: ela nunca vira candidata, o hash
dela nunca e recalculado, e a comparacao em Python nunca roda. Depois de uma
troca de modelo o catalogo ficaria indefinidamente com vetores do espaco
velho, e cosseno entre dois espacos e ruido.

Com a coluna, o pre-filtro ganha `OR embedding_modelo IS DISTINCT FROM
:modelo` e a troca de modelo dispara a reindexacao sozinha -- sem
`UPDATE imoveis SET documento_hash = NULL` que alguem precise lembrar de
rodar, que e exatamente o modo de falha que a D2 existe para eliminar.

**Nulavel, e sem backfill.** Nao ha valor certo a escrever aqui: a migration
nao sabe qual modelo gerou os vetores que ja existem. NULL e
`IS DISTINCT FROM` de qualquer modelo configurado, entao toda linha ja
indexada entra como candidata na proxima passagem; la o hash decide. Se o
modelo nao mudou, o hash bate, NENHUMA chamada e feita ao provedor e a
varredura so carimba a coluna -- uma passagem de conciliacao, sem caminho de
backfill proprio. E o mesmo raciocinio das tres nulaveis da `0017`.

Nenhum indice: a coluna so aparece no `OR` de um pre-filtro que ja varre
`imoveis` inteira nesta escala.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("imoveis", sa.Column("embedding_modelo", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("imoveis", "embedding_modelo")

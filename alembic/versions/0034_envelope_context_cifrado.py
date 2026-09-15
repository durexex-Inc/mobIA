"""TEC-221 -- `messages.envelope_context` passa a bytea cifrado.

A coluna nasceu JSONB em claro na 0003, reservada pelo TEC-217, e ficou de fora
da cifra da 0004 porque nao tinha escritor. O TEC-217 vai gravar ali o
`change.value` do envelope da Meta sem o array `messages` -- trecho que carrega
`contacts[].profile.name` e `wa_id`, isto e, nome e telefone do lead. Cifrar
antes do escritor custa esta migracao; depois dele, custaria backfill.

**Por que aqui cabe `USING` e na 0004 nao cabia.** O comentario da 0004 diz que
a cifra acontece em Python e o banco nao tem a chave, entao la foi preciso
coluna nova, backfill em lote e troca. Aqui nao ha o que cifrar: a coluna esta
vazia por construcao. A guarda abaixo e que torna essa afirmacao verificavel em
vez de suposta.

**Consequencia que quem procura "como reverter isto" precisa saber de antemao:**
no dia em que o TEC-217 gravar a primeira linha, o `downgrade` desta revisao
para de ser executavel -- a mesma guarda o aborta, de proposito, porque descer
para JSONB descartaria o conteudo. A partir dali, reverter a decisao de cifrar
exige uma migracao nova no padrao da 0004, que decifra em Python antes de
trocar o tipo. Isso e falhar fechado: preferir a reversao travada a uma que
apaga dado pessoal em silencio.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def _exigir_coluna_vazia(coluna: str) -> None:
    """Aborta se alguem passou a gravar na coluna desde que isto foi escrito.

    A conversao descarta o conteudo (`USING NULL`), e descartar dado pessoal em
    silencio seria o oposto do que esta migracao existe para fazer. Se um
    escritor apareceu, o caminho certo e o backfill da 0004 -- coluna nova,
    cifra em Python, troca --, e nao esta migracao.
    """
    pendentes = op.get_bind().scalar(
        sa.text(f"SELECT count(*) FROM messages WHERE {coluna} IS NOT NULL")
    )
    if pendentes:
        raise RuntimeError(
            f"{pendentes} linha(s) com {coluna} preenchido: esta migracao descartaria o "
            "conteudo. Ela pressupoe a coluna vazia (nenhum escritor ate o TEC-217). "
            "Com dado gravado, use o padrao de backfill da 0004."
        )


def upgrade() -> None:
    _exigir_coluna_vazia("envelope_context")
    op.alter_column(
        "messages",
        "envelope_context",
        type_=sa.LargeBinary(),
        existing_type=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="NULL",
    )


def downgrade() -> None:
    # Simetrico: descer tambem so e seguro com a coluna vazia. Um ciphertext
    # convertido para JSONB nao volta a ser JSON legivel de jeito nenhum.
    _exigir_coluna_vazia("envelope_context")
    op.alter_column(
        "messages",
        "envelope_context",
        type_=postgresql.JSONB(),
        existing_type=sa.LargeBinary(),
        existing_nullable=True,
        postgresql_using="NULL",
    )

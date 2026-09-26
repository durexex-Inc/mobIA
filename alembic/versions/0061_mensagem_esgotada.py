"""o status ESGOTADA: a dead-letter queue de mensagens

TEC-209, D5 do desenho. O CHECK de `messages.status` e recriado com o valor
novo -- o Postgres nao estende CHECK, pela razao que a 0056 escreve para a
trilha. O vocabulario anterior e o da 0037, que o escreveu.

**Nenhuma linha e migrada.** As FAILED que ja esgotaram as tentativas
continuam FAILED: elas ja estao fora da varredura pelo `attempts`, e
reclassifica-las aqui seria afirmar que cada uma teve o handoff por erro, o
que o dado nao prova (a TEC-174 so existe desde 13/09). A lista da DLQ as
inclui pelo mesmo criterio que as faz terminais.

**O downgrade recria o CHECK antigo como `NOT VALID`**: uma linha ja gravada
como ESGOTADA reprovaria um CHECK validado, e apaga-la para voltar o schema
seria perder a mensagem que a DLQ existe para guardar.

Revision ID: 0061
Revises: 0060
"""

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_STATUS = ("RECEIVED", "QUEUED", "PROCESSING", "PROCESSED", "FAILED", "ESGOTADA")
_STATUS_ANTERIORES = _STATUS[:-1]


def _check(valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"status IS NULL OR status IN ({literais})"


def upgrade() -> None:
    op.drop_constraint("ck_messages_status", "messages", type_="check")
    op.create_check_constraint("ck_messages_status", "messages", _check(_STATUS))


def downgrade() -> None:
    op.drop_constraint("ck_messages_status", "messages", type_="check")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT ck_messages_status "
        f"CHECK ({_check(_STATUS_ANTERIORES)}) NOT VALID"
    )

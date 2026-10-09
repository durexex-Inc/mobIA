"""o pedido de interesse guarda o e-mail, e a trilha aprende a atribuicao

TEC-404. Duas coisas:

- **`solicitacoes_de_interesse.email_cifrado`** (bytea, nulo). Cifrado com
  `aad_do_email_de_interesse`. Sem backfill: pedidos anteriores ficam nulos (D3).
- **`HANDOFF_ATRIBUIDO`** em `eventos_auditoria.acao`. Como a 0057, a 0059 e a
  0063, o CHECK e RECRIADO -- o Postgres nao estende CHECK. `_ACOES` parte da
  tupla da 0063, a ultima que a redefine. O downgrade recria o antigo como
  `NOT VALID`, pela razao da 0057: linha de trilha nao sai.

Copia literal de `domain/auditoria/vocabulario.py::Acao`, e nao import.

Revision ID: 0071
Revises: 0070
"""

import sqlalchemy as sa

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

_ACOES = (
    "DADO_PESSOAL_ACESSADO",
    "QUALIFICACAO_ALTERADA",
    "HANDOFF_CRIADO",
    "OPTOUT_REGISTRADO",
    "OPTOUT_REATIVADO",
    "PROMPT_PUBLICADO",
    "ACESSO_NEGADO",
    "INJECAO_DETECTADA",
    "CONFIGURACAO_ALTERADA",
    "PROMPT_REVERTIDO",
    "TITULAR_SOLICITOU",
    "DADOS_EXPORTADOS",
    "LEAD_ANONIMIZADO",
    "TITULAR_RECUSADO",
    "HANDOFF_ATRIBUIDO",
)
_ACOES_ANTERIORES = _ACOES[:-1]
_CHECK = "ck_eventos_auditoria_acao"


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.add_column(
        "solicitacoes_de_interesse", sa.Column("email_cifrado", sa.LargeBinary(), nullable=True)
    )
    op.drop_constraint(_CHECK, "eventos_auditoria", type_="check")
    op.create_check_constraint(_CHECK, "eventos_auditoria", _em("acao", _ACOES))


def downgrade() -> None:
    op.drop_constraint(_CHECK, "eventos_auditoria", type_="check")
    op.execute(
        f"ALTER TABLE eventos_auditoria ADD CONSTRAINT {_CHECK} "
        f"CHECK ({_em('acao', _ACOES_ANTERIORES)}) NOT VALID"
    )
    op.drop_column("solicitacoes_de_interesse", "email_cifrado")

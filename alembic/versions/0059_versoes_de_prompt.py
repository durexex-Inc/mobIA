"""as versoes de prompt, as ativacoes, e a trilha aprende o rollback

TEC-199, D4 e D7 do desenho. Tres coisas, e as tres sao da mesma card:

- **`versoes_de_prompt`**, so de acrescimo: cada texto publicado, numerado por
  agente, com o diff contra a versao que valia na publicacao.
- **`ativacoes_de_prompt`**, so de acrescimo: cada vez que uma versao passou a
  valer, por publicacao ou por rollback. A vigente e a ativacao mais recente,
  e sem ativacao vale o padrao do codigo -- por isso nada e semeado, pela
  razao que a `0058` escreve.
- **`PROMPT_REVERTIDO` no CHECK de `acao`**, recriado e nao estendido, como a
  `0056`, a `0057` e a `0058` fizeram. `_ACOES` parte da tupla da `0058`, a
  ultima que o escreveu. `PROMPT_PUBLICADO` ja estava la desde a `0053`, sem
  chamador ate esta card.

As tuplas sao COPIA literal dos enums, e nao import -- migration aplicada nao
muda quando o codigo muda. `tests/unit/test_auditoria_vocabulario.py` compara
o codigo com a migration mais recente que redefine cada CHECK.

**O downgrade recria o CHECK antigo como `NOT VALID`**, pela razao da `0057`:
a trilha recusa DELETE de linha com menos de 12 meses.

Revision ID: 0059
Revises: 0058
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0059"
down_revision = "0058"
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
)
_ACOES_ANTERIORES = _ACOES[:-1]

# Copia literal de `domain/prompts/modelo.py::AgenteDoPrompt`.
_AGENTES = ("AGENTE", "INVESTIDOR")


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.create_table(
        "versoes_de_prompt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agente", sa.String(16), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("anterior", sa.Integer(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("autor", sa.String(120), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(_em("agente", _AGENTES), name="ck_versoes_de_prompt_agente"),
        # A 0 e o padrao e nao tem linha; uma versao gravada comeca na 1, e a
        # anterior dela e sempre menor.
        sa.CheckConstraint(
            "numero >= 1 AND anterior >= 0 AND anterior < numero",
            name="ck_versoes_de_prompt_numero",
        ),
        sa.UniqueConstraint("agente", "numero", name="uq_versoes_de_prompt_numero"),
    )

    op.create_table(
        "ativacoes_de_prompt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agente", sa.String(16), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(12), nullable=False),
        sa.Column("autor", sa.String(120), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(_em("agente", _AGENTES), name="ck_ativacoes_de_prompt_agente"),
        sa.CheckConstraint(
            _em("motivo", ("PUBLICACAO", "ROLLBACK")), name="ck_ativacoes_de_prompt_motivo"
        ),
        # Publicacao sempre ativa uma versao gravada; so o rollback pode voltar
        # para a 0, o padrao.
        sa.CheckConstraint(
            "numero >= 1 OR (numero = 0 AND motivo = 'ROLLBACK')",
            name="ck_ativacoes_de_prompt_numero",
        ),
    )
    op.create_index(
        "ix_ativacoes_de_prompt_agente_criado_em",
        "ativacoes_de_prompt",
        ["agente", sa.text("criado_em DESC")],
    )

    op.drop_constraint("ck_eventos_auditoria_acao", "eventos_auditoria", type_="check")
    op.create_check_constraint(
        "ck_eventos_auditoria_acao", "eventos_auditoria", _em("acao", _ACOES)
    )


def downgrade() -> None:
    op.drop_constraint("ck_eventos_auditoria_acao", "eventos_auditoria", type_="check")
    op.execute(
        "ALTER TABLE eventos_auditoria ADD CONSTRAINT ck_eventos_auditoria_acao "
        f"CHECK ({_em('acao', _ACOES_ANTERIORES)}) NOT VALID"
    )
    op.drop_index("ix_ativacoes_de_prompt_agente_criado_em", table_name="ativacoes_de_prompt")
    op.drop_table("ativacoes_de_prompt")
    op.drop_table("versoes_de_prompt")

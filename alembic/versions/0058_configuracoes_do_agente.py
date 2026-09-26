"""as versoes da configuracao do agente, e a trilha aprende a alteracao

TEC-198, D1 do desenho. Duas coisas, e as duas sao da mesma card:

- **`configuracoes_do_agente`**, so de acrescimo: uma linha por alteracao, com
  a configuracao INTEIRA. A vigente e a mais recente, e sem linha nenhuma vale
  o padrao escrito no codigo -- por isso esta migration nao semeia nada. Semear
  o padrao aqui congelaria o padrao de HOJE numa linha, e a proxima mudanca de
  constante no codigo nao valeria para quem nunca editou nada.
- **`CONFIGURACAO_ALTERADA` no CHECK de `acao`**, que e recriado e nao
  estendido, pela razao da 0056 e da 0057: o Postgres nao estende CHECK.
  `_ACOES` parte da tupla da 0057, que e a ultima que o escreveu; partir da
  0053 apagaria `INJECAO_DETECTADA`. O de `entidade` nao muda: a
  `configuracao_agente` ja esta la desde a 0053.

As tuplas sao COPIA literal do enum de `domain/auditoria/vocabulario.py`, e nao
import -- migration aplicada nao muda quando o codigo muda.
`tests/unit/test_auditoria_vocabulario.py` compara o codigo com a migration
mais recente que redefine cada CHECK, que passa a ser esta para `acao`.

**O downgrade recria o CHECK antigo como `NOT VALID`**, pela razao que a 0057
escreve: a trilha recusa DELETE de linha com menos de 12 meses, e um
`CONFIGURACAO_ALTERADA` ja gravado reprovaria um CHECK validado.

Revision ID: 0058
Revises: 0057
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0058"
down_revision = "0057"
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
)
_ACOES_ANTERIORES = _ACOES[:-1]


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.create_table(
        "configuracoes_do_agente",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nome_do_assistente", sa.String(30), nullable=True),
        sa.Column("tom", sa.String(16), nullable=False),
        sa.Column("teto_de_perguntas", sa.SmallInteger(), nullable=False),
        sa.Column("peso_completude", sa.SmallInteger(), nullable=False),
        sa.Column("peso_urgencia", sa.SmallInteger(), nullable=False),
        sa.Column("peso_catalogo", sa.SmallInteger(), nullable=False),
        sa.Column("peso_engajamento", sa.SmallInteger(), nullable=False),
        sa.Column("peso_capacidade", sa.SmallInteger(), nullable=False),
        sa.Column("cadencia", postgresql.JSONB(), nullable=False),
        sa.Column("autor", sa.String(120), nullable=False),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        # O vocabulario do tom e as faixas mais grossas ficam no banco tambem,
        # e nao so na validacao: uma linha gravada por fora da rota (script,
        # SQL cru) com peso negativo pontuaria todo lead do sistema errado.
        # As faixas finas -- soma dos pesos, cadencia crescente -- sao da
        # aplicacao, que as explica em texto.
        sa.CheckConstraint(
            "tom IN ('CORDIAL', 'FORMAL', 'DESCONTRAIDO')", name="ck_configuracoes_do_agente_tom"
        ),
        sa.CheckConstraint(
            "teto_de_perguntas BETWEEN 1 AND 20", name="ck_configuracoes_do_agente_teto"
        ),
        sa.CheckConstraint(
            "LEAST(peso_completude, peso_urgencia, peso_catalogo, peso_engajamento, "
            "peso_capacidade) >= 0",
            name="ck_configuracoes_do_agente_pesos",
        ),
    )
    op.create_index(
        "ix_configuracoes_do_agente_criado_em",
        "configuracoes_do_agente",
        [sa.text("criado_em DESC")],
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
    op.drop_index("ix_configuracoes_do_agente_criado_em", table_name="configuracoes_do_agente")
    op.drop_table("configuracoes_do_agente")

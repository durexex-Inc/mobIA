"""a solicitacao de titular existe, com prazo, e a trilha a nomeia

TEC-207, D2 e D6 do desenho. Duas coisas:

- **`solicitacoes_de_titular`**. `lead_ref` (HMAC do par, como em
  `eventos_auditoria`) sobrevive a anonimizacao do lead; `channel` e
  `conversation_key` SO existem enquanto a solicitacao esta ABERTA -- o CHECK
  `ck_solicitacoes_de_titular_par_com_status` amarra os dois, porque e por eles
  que se localiza a conversa para responder enquanto o pedido espera, e a
  linha nao tem por que continuar carregando o identificador do lead depois de
  atendida ou recusada. `lead_ref` fica de qualquer jeito, porque e ele que
  identifica de quem foi o pedido mesmo depois de o par sumir -- inclusive
  depois de `anonimizar_lead` apagar o par de toda outra tabela.
  `uq_solicitacao_aberta` (parcial, sobre `status = 'ABERTA'`) e o que torna o
  registro idempotente: um segundo pedido do mesmo tipo, do mesmo lead, nao
  cria uma segunda linha enquanto a primeira espera. Ele e sobre o PAR, e nao
  sobre `lead_ref`: a rotacao de chave da TEC-203 arrasta o par e so recalcula
  `lead_ref` em `eventos_auditoria`, e um indice sobre `lead_ref` deixaria o
  pedido repetido depois de uma rotacao abrir uma segunda linha.
  `ck_solicitacoes_de_titular_par_completo` amarra os dois lados do par entre
  si -- `ck_solicitacoes_de_titular_par_com_status` sozinho so liga a
  presenca do par ao status, e deixaria passar `channel` preenchido com
  `conversation_key` nulo.

- **A trilha aprende quatro acoes novas** (`TITULAR_SOLICITOU`,
  `DADOS_EXPORTADOS`, `LEAD_ANONIMIZADO`, `TITULAR_RECUSADO`) e uma entidade
  nova (`solicitacao_de_titular`). Como a 0057 e a 0059, os CHECKs de
  `eventos_auditoria` sao RECRIADOS e nao estendidos -- o Postgres nao estende
  CHECK. `_ACOES` parte da tupla da 0059, a ultima que a redefine; `_ENTIDADES`
  parte da tupla da 0057, a ultima que a redefine.

As tuplas sao COPIA literal dos enums de `domain/auditoria/vocabulario.py` e de
`domain/titular/vocabulario.py`, e nao import: migration aplicada nao muda
quando o codigo muda. `tests/unit/test_auditoria_vocabulario.py` compara o
codigo com a migration mais recente que redefine cada CHECK.

**O downgrade recria os CHECKs antigos como `NOT VALID`**, pela razao da 0057:
a trilha recusa DELETE de linha com menos de 12 meses, entao um
`TITULAR_SOLICITOU` ja gravado nao sai, e um CHECK validado reprovaria o
downgrade por causa dele.

Revision ID: 0063
Revises: 0062
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0063"
down_revision = "0062"
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
)
_ENTIDADES = (
    "handoff",
    "optout_event",
    "rota",
    "lead_qualification",
    "configuracao_agente",
    "lead",
    "mensagem",
    "solicitacao_de_titular",
)

_ACOES_ANTERIORES = _ACOES[:-4]
_ENTIDADES_ANTERIORES = _ENTIDADES[:-1]

_CHECKS = (
    ("ck_eventos_auditoria_acao", "acao"),
    ("ck_eventos_auditoria_entidade", "entidade"),
)

# Copia literal de `domain/titular/vocabulario.py`.
_TIPOS = ("ELIMINACAO", "ACESSO")
_ORIGENS = ("WHATSAPP", "ADMIN", "RETENCAO")
_STATUS = ("ABERTA", "ATENDIDA", "RECUSADA")


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    for (nome, coluna), valores in zip(_CHECKS, (_ACOES, _ENTIDADES), strict=True):
        op.drop_constraint(nome, "eventos_auditoria", type_="check")
        op.create_check_constraint(nome, "eventos_auditoria", _em(coluna, valores))

    op.create_table(
        "solicitacoes_de_titular",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_ref", sa.CHAR(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=True),
        sa.Column("conversation_key", sa.String(64), nullable=True),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("origem", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("motivo_da_recusa", sa.Text(), nullable=True),
        sa.Column(
            "recebida_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("prazo_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atendida_em", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_em("tipo", _TIPOS), name="ck_solicitacoes_de_titular_tipo"),
        sa.CheckConstraint(_em("origem", _ORIGENS), name="ck_solicitacoes_de_titular_origem"),
        sa.CheckConstraint(_em("status", _STATUS), name="ck_solicitacoes_de_titular_status"),
        sa.CheckConstraint(
            "(status = 'ABERTA') = (channel IS NOT NULL)",
            name="ck_solicitacoes_de_titular_par_com_status",
        ),
        sa.CheckConstraint(
            "(channel IS NOT NULL) = (conversation_key IS NOT NULL)",
            name="ck_solicitacoes_de_titular_par_completo",
        ),
    )
    op.create_index(
        "uq_solicitacao_aberta",
        "solicitacoes_de_titular",
        ["channel", "conversation_key", "tipo"],
        unique=True,
        postgresql_where=sa.text("status = 'ABERTA'"),
    )
    op.create_index(
        "ix_solicitacoes_de_titular_status_prazo",
        "solicitacoes_de_titular",
        ["status", "prazo_em"],
    )


def downgrade() -> None:
    op.drop_index("ix_solicitacoes_de_titular_status_prazo", table_name="solicitacoes_de_titular")
    op.drop_index("uq_solicitacao_aberta", table_name="solicitacoes_de_titular")
    op.drop_table("solicitacoes_de_titular")

    for (nome, coluna), valores in zip(
        _CHECKS, (_ACOES_ANTERIORES, _ENTIDADES_ANTERIORES), strict=True
    ):
        op.drop_constraint(nome, "eventos_auditoria", type_="check")
        op.execute(
            f"ALTER TABLE eventos_auditoria ADD CONSTRAINT {nome} "
            f"CHECK ({_em(coluna, valores)}) NOT VALID"
        )

"""a trilha de auditoria imutavel

TEC-206, RNF-18. Uma tabela so de acrescimo para "quem acessou ou alterou o
que, quando e de onde", sem o dado pessoal em claro.

**Dois triggers, e o segundo vai alem dos da 0012 e da 0035.** Aqueles recusam
so UPDATE; este recusa UPDATE sempre e DELETE de linha com menos de 12 meses,
porque a exclusao legitima passou a ter regra (D6 do desenho): 12 meses e o
maximo, e o job `sweep_retencao_auditoria` apaga o que passou. O job nao
decide o que pode ser apagado -- este trigger confere linha por linha.

**O de insercao carimba `criado_em` com `clock_timestamp()`, qualquer que seja
o valor enviado.** Sem ele a regra dos 12 meses tem um furo: inserir uma linha
datada de dois anos atras e apaga-la em seguida. `clock_timestamp()` e nao
`now()` pelo argumento que a 0012 escreve por extenso.

**Limites, declarados.** TRUNCATE nao e bloqueado -- `banco_limpo` trunca
todas as tabelas antes de cada teste de integracao. E o dono da tabela pode
remover o trigger: a aplicacao conecta como dono, e a garantia e contra a
aplicacao, nao contra o operador do banco.

Sem FK para as entidades: o registro sobrevive a exclusao do que descreve, que
e o motivo de ele existir.

Os vocabularios abaixo sao COPIA literal dos enums de
`domain/auditoria/vocabulario.py`, e nao import: migration aplicada nao muda
quando o codigo muda. `tests/unit/test_auditoria_vocabulario.py` prende as
duas copias.

Revision ID: 0053
Revises: 0052

**Nasceu 0052 e foi renumerada para 0053 (TEC-377).** A 0052 da TEC-372 e
esta mergearam com 17 segundos de diferenca, as duas a partir da 0051, e
`alembic upgrade head` passou a reprovar com dois heads. Renumerou-se ESTA, e
nao a irma, porque nenhuma base a tinha aplicado: as nove locais estavam
carimbadas 0052 com `agendamentos.presenca_confirmada_em` e sem
`eventos_auditoria`. Assim o carimbo existente continua verdadeiro e a unica
coisa que falta rodar e esta migration.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_ATORES = ("USUARIO", "AGENTE", "SISTEMA")
_ACOES = (
    "DADO_PESSOAL_ACESSADO",
    "QUALIFICACAO_ALTERADA",
    "HANDOFF_CRIADO",
    "OPTOUT_REGISTRADO",
    "OPTOUT_REATIVADO",
    "PROMPT_PUBLICADO",
    "ACESSO_NEGADO",
)
_ENTIDADES = ("handoff", "optout_event", "rota", "lead_qualification", "configuracao_agente")

_FUNCAO_DO_CARIMBO = """
CREATE FUNCTION eventos_auditoria_carimba() RETURNS trigger AS $$
BEGIN
    NEW.criado_em := clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER_DO_CARIMBO = """
CREATE TRIGGER eventos_auditoria_carimbo
    BEFORE INSERT ON eventos_auditoria
    FOR EACH ROW EXECUTE FUNCTION eventos_auditoria_carimba()
"""

_FUNCAO_DA_PROTECAO = """
CREATE FUNCTION eventos_auditoria_protege() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'eventos_auditoria e imutavel: UPDATE recusado (RNF-18)';
    END IF;
    IF OLD.criado_em >= clock_timestamp() - interval '12 months' THEN
        RAISE EXCEPTION
            'eventos_auditoria: DELETE recusado, o registro tem menos de 12 meses (RNF-18)';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER_DA_PROTECAO = """
CREATE TRIGGER eventos_auditoria_imutavel
    BEFORE UPDATE OR DELETE ON eventos_auditoria
    FOR EACH ROW EXECUTE FUNCTION eventos_auditoria_protege()
"""


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.create_table(
        "eventos_auditoria",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("ator_tipo", sa.String(16), nullable=False),
        sa.Column("ator_id", sa.String(64), nullable=True),
        sa.Column("acao", sa.String(32), nullable=False),
        sa.Column("entidade", sa.String(32), nullable=False),
        sa.Column("entidade_id", sa.String(200), nullable=False),
        sa.Column("campo", sa.String(32), nullable=True),
        sa.Column("lead_ref", sa.CHAR(64), nullable=True),
        sa.Column("detalhes", postgresql.JSONB(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("correlation_id", sa.String(200), nullable=True),
        sa.CheckConstraint(_em("ator_tipo", _ATORES), name="ck_eventos_auditoria_ator_tipo"),
        sa.CheckConstraint(_em("acao", _ACOES), name="ck_eventos_auditoria_acao"),
        sa.CheckConstraint(_em("entidade", _ENTIDADES), name="ck_eventos_auditoria_entidade"),
        sa.CheckConstraint(
            "(ator_tipo = 'USUARIO') = (ator_id IS NOT NULL)",
            name="ck_eventos_auditoria_ator_id",
        ),
    )
    # A paginacao da TEC-343 e a retencao. `id DESC` tambem, para que
    # `ORDER BY criado_em DESC, id DESC` e o cursor usem este indice inteiro.
    op.create_index(
        "ix_eventos_auditoria_pagina",
        "eventos_auditoria",
        [sa.text("criado_em DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_eventos_auditoria_ator", "eventos_auditoria", ["ator_id", sa.text("criado_em DESC")]
    )
    op.create_index(
        "ix_eventos_auditoria_acao", "eventos_auditoria", ["acao", sa.text("criado_em DESC")]
    )
    op.create_index(
        "ix_eventos_auditoria_lead", "eventos_auditoria", ["lead_ref", sa.text("criado_em DESC")]
    )
    op.execute(_FUNCAO_DO_CARIMBO)
    op.execute(_TRIGGER_DO_CARIMBO)
    op.execute(_FUNCAO_DA_PROTECAO)
    op.execute(_TRIGGER_DA_PROTECAO)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS eventos_auditoria_imutavel ON eventos_auditoria")
    op.execute("DROP TRIGGER IF EXISTS eventos_auditoria_carimbo ON eventos_auditoria")
    op.execute("DROP FUNCTION IF EXISTS eventos_auditoria_protege()")
    op.execute("DROP FUNCTION IF EXISTS eventos_auditoria_carimba()")
    op.drop_index("ix_eventos_auditoria_lead", table_name="eventos_auditoria")
    op.drop_index("ix_eventos_auditoria_acao", table_name="eventos_auditoria")
    op.drop_index("ix_eventos_auditoria_ator", table_name="eventos_auditoria")
    op.drop_index("ix_eventos_auditoria_pagina", table_name="eventos_auditoria")
    op.drop_table("eventos_auditoria")

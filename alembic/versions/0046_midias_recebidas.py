"""a linha por midia recebida, com o ponteiro e o estado do download

TEC-132, D2. Uma linha por mensagem IMAGEM ou DOCUMENTO -- so essas duas tem
o que baixar (D3); audio e a TEC-131, e video/figurinha/localizacao continuam
DESCONHECIDO, sem download.

Sem CHECK em `status`/`motivo`: ver a docstring de `MidiaRecebida`
(`domain/midia/models.py`) para o porque -- a 0037 criou CHECK para o
vocabulario de `messages` por um risco especifico (comparacao de literal cru
em SQL) que nao existe aqui, e nenhuma tabela nova depois dela repetiu o
CHECK so por ter vocabulario.

`motivo` e String(32), e nao o String(64) que a D2 da spec dizia antes
(desvio deliberado, registrado na propria D2 de
`docs/superpowers/specs/2026-09-24-tec-132-midia-recebida-design.md`): o
maior literal de `MotivoDaMidia` tem 20 caracteres, e
`tarefas_de_corretor.motivo` (0039) ja usa String(32) para o mesmo tipo de
vocabulario curto.

`tentativas` conta os re-enfileiramentos da varredura, e nao os `Retry` do
ARQ dentro de um job: e o que poe teto no reenvio de uma linha cuja falha
nao passa pelo `Retry` (ver `TETO_DE_REENFILEIRAMENTOS`, em
`workers/jobs/sweep_midias_pendentes.py`). Esta coluna entrou nesta propria
migration, e nao numa seguinte, porque esta ainda nao tinha sido mergeada.

O indice parcial e o unico caminho de leitura por status: a varredura
periodica (`pendentes_para_reenfileirar`, `expirar_pendentes`,
`esgotar_pendentes`) le so
PENDENTE, e as tres outras linhas terminais nunca entram nesse WHERE.

**Esta migration nasceu 0042 e virou 0046 no merge da `main`, ainda na
TEC-132.** A branch saiu de `0041`; enquanto ela corria, a `main` numerou
`0042` a `0045` (TEC-363 `0042_consentimentos`, TEC-180
`0043_exportacao_para_crm`, TEC-168 `0044_agendamentos`, TEC-201/202
`0045_usuarios_e_sessoes`). Duas revisoes "0042" deixariam o alembic com duas
cabecas -- o mesmo "Multiple head revisions are present" que a 0045 registra --,
entao esta, a ultima a entrar, passou para o fim da cadeia. Nada nela depende
das quatro: a tabela so referencia `messages`.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "midias_recebidas",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("media_id_da_meta", sa.String(128), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("chave_no_armazem", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("motivo", sa.String(32), nullable=True),
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "criado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_midias_recebidas_pendentes",
        "midias_recebidas",
        ["criado_em"],
        postgresql_where=sa.text("status = 'PENDENTE'"),
    )


def downgrade() -> None:
    op.drop_index("ix_midias_recebidas_pendentes", table_name="midias_recebidas")
    op.drop_table("midias_recebidas")

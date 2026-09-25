"""o usuario do dashboard e a sessao de refresh

TEC-201, RNF-11. Duas tabelas novas e vazias: nao ha backfill possivel porque
nao existia usuario nenhum -- ate aqui o acesso administrativo era um TOKEN
COMPARTILHADO (`X-Admin-Token`), sem pessoa por tras.

**As duas tabelas nascem sem escritor de producao, e isso e declarado.** Nao ha
rota de cadastro nesta card (lacuna L2 do desenho): o primeiro usuario precisa
ser inserido a mao. Nao e a coluna sem escritor que a D1 da TEC-174 recusou --
e uma tabela cuja porta de entrada e outra card.

`email` e `nome` ficam EM CLARO apesar de o modelo da secao 5.1 do SRS marcar
os dois como DP. E o precedente da TEC-196 para `corretores`: este repo cifra
conteudo e nao identificador, e aqui vale com mais forca -- o e-mail e a chave
de login, e indice unico sobre valor cifrado com nonce aleatorio nao existe.

**Esta migration nasceu 0044 e virou 0045 na TEC-202, e a razao fica aqui.**
A TEC-168 (`0044_agendamentos.py`) e a TEC-201 (esta) sairam de `0043` em
branches paralelas e as duas se numeraram `0044`. Cada PR passou sozinho -- o
conflito so existe na arvore em que os dois estao --, e depois do segundo merge
`alembic upgrade head` parou de funcionar para todo mundo, com "Multiple head
revisions are present". A TEC-202 achou isso na primeira execucao de
integracao dela e renumerou esta, que foi a segunda a ser mergeada.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("email", sa.String(160), nullable=False),
        sa.Column("papel", sa.String(16), nullable=False),
        # Sem `ondelete`: corretor se desativa por `ativo = false` e nunca se
        # apaga (TEC-196), entao a cascata nao tem caso de uso. O default do
        # Postgres (RESTRICT) e o que se quer -- apagar por engano deve doer.
        sa.Column(
            "corretor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("corretores.id"),
            nullable=True,
        ),
        # Argon2id em texto: o formato carrega os parametros junto, e e isso
        # que permite subir o custo sem invalidar os hashes ja gravados.
        sa.Column("senha_hash", sa.String(255), nullable=False),
        # Cifrada com AES-GCM. Nulavel porque usuario sem MFA nao tem semente.
        sa.Column("totp_segredo", sa.LargeBinary(), nullable=True),
        sa.Column("mfa_habilitado", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "papel IN ('ADMIN', 'GERENTE', 'CORRETOR', 'LEITURA')", name="ck_usuarios_papel"
        ),
        # A unica defesa contra usuario duplicado, e a razao de o e-mail nao
        # ser cifrado.
        sa.UniqueConstraint("email", name="uq_usuarios_email"),
    )

    op.create_table(
        "sessoes_de_refresh",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # CASCADE aqui, ao contrario da FK acima: apagar um usuario deve levar
        # as sessoes dele junto -- sessao orfa e credencial viva sem dono.
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("familia", postgresql.UUID(as_uuid=True), nullable=False),
        # SHA-256 em hexadecimal: 64 caracteres, tamanho fixo.
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revogado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("digest", name="uq_sessoes_digest"),
    )
    op.create_index("ix_sessoes_familia", "sessoes_de_refresh", ["familia"])


def downgrade() -> None:
    op.drop_index("ix_sessoes_familia", table_name="sessoes_de_refresh")
    op.drop_table("sessoes_de_refresh")
    op.drop_table("usuarios")

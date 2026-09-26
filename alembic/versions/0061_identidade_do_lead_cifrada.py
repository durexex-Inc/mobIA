"""o telefone do lead sai do conversation_key e passa a morar cifrado

TEC-203, RNF-13, RT-08. Revoga, para o lead, a doutrina da Emenda E-01 ("o que
este sistema cifra e conteudo, nunca identificador").

Cria `identidades_de_lead`, troca o `conversation_key` de todas as tabelas
pelo HMAC do valor (`indice.chave_de`) e cifra o telefone de
`vinculos_de_sessao`. O backfill e em Python pela razao da 0004: o banco nao
tem a chave.

**Lista de tabelas copiada, e nao importada** de `reindexacao.TABELAS_COM_CHAVE_DE_LEAD`:
migration aplicada nao muda quando o codigo muda, e uma tabela criada depois
da 0061 nao existe ainda quando ela roda num banco novo.

**Desliga e religa as triggers de imutabilidade** das tres trilhas -- ver a
docstring de `domain/identidade/reindexacao.py`.

Nasceu 0058 e virou 0061 no merge com a `main`, que ganhou a 0058, a 0059 e a
0060 (TEC-198, TEC-199, TEC-191) antes. Nenhuma das tres cria tabela com
`conversation_key`, entao a lista abaixo nao mudou.

Revision ID: 0061
Revises: 0060
"""

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op
from mobia.app.config import get_settings
from mobia.domain.identidade.indice import chave_de, indice_de_telefone
from mobia.domain.identidade.models import aad_do_vinculo
from mobia.domain.identidade.reindexacao import reindexar
from mobia.infra.crypto import decrypt, encrypt

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_TABELAS = (
    "agendamentos", "atendimento_humano", "consentimentos", "conversas",
    "conversation_intent", "conversation_intent_audit", "conversation_summaries",
    "followups", "handoffs", "janelas_propostas", "lead_qualification",
    "lead_score_audit", "lista_de_espera", "messages", "moderation_events",
    "optout_events", "recomendacoes", "referencias_de_lead", "tarefas_de_corretor",
    "vinculos_de_sessao",
)  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "identidades_de_lead",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("conversation_key", sa.String(64), primary_key=True),
        sa.Column("valor_cifrado", sa.LargeBinary, nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    conn = op.get_bind()
    chave_do_lead = get_settings().auditoria_chave_do_lead
    reindexar(
        conn,
        tabelas=_TABELAS,
        nova_chave=chave_de,
        modo="migracao",
        chave_do_lead_antiga=chave_do_lead,
        chave_do_lead_nova=chave_do_lead,
    )

    # O vinculo muda de forma DEPOIS do loop: o AAD do telefone cifrado usa o
    # par, e o par ja e o definitivo aqui.
    op.add_column(
        "vinculos_de_sessao", sa.Column("telefone_cifrado", sa.LargeBinary, nullable=True)
    )
    op.add_column("vinculos_de_sessao", sa.Column("telefone_indice", sa.String(64), nullable=True))
    for channel, chave, telefone in conn.execute(
        text("SELECT channel, conversation_key, telefone FROM vinculos_de_sessao")
    ).all():
        conn.execute(
            text(
                "UPDATE vinculos_de_sessao SET telefone_cifrado = :t, telefone_indice = :i "
                "WHERE channel = :c AND conversation_key = :k"
            ),
            {
                "t": encrypt(telefone, aad_do_vinculo(channel, chave)),
                "i": indice_de_telefone(telefone),
                "c": channel,
                "k": chave,
            },
        )
    op.alter_column("vinculos_de_sessao", "telefone_cifrado", nullable=False)
    op.alter_column("vinculos_de_sessao", "telefone_indice", nullable=False)
    op.drop_index("ix_vinculos_de_sessao_telefone", table_name="vinculos_de_sessao")
    op.drop_column("vinculos_de_sessao", "telefone")
    op.create_index(
        "ix_vinculos_de_sessao_telefone_indice", "vinculos_de_sessao", ["telefone_indice"]
    )


def downgrade() -> None:
    """Devolve o valor em claro as colunas. E o que um downgrade deve fazer:
    voltar ao estado de antes, e antes o telefone estava em claro.

    A ordem e a inversa da subida: o vinculo volta a ter `telefone` em claro
    ANTES do loop, enquanto o par ainda e o HMAC que o AAD do telefone cifrado
    usa. Sem `telefone_cifrado`, `reindexar` nao tem o que recifrar no vinculo
    -- e e isso que se quer.
    """
    conn = op.get_bind()
    op.add_column("vinculos_de_sessao", sa.Column("telefone", sa.String(16), nullable=True))
    for channel, chave, blob in conn.execute(
        text("SELECT channel, conversation_key, telefone_cifrado FROM vinculos_de_sessao")
    ).all():
        conn.execute(
            text(
                "UPDATE vinculos_de_sessao SET telefone = :t"
                " WHERE channel = :c AND conversation_key = :k"
            ),
            {"t": decrypt(bytes(blob), aad_do_vinculo(channel, chave)), "c": channel, "k": chave},
        )
    op.drop_index("ix_vinculos_de_sessao_telefone_indice", table_name="vinculos_de_sessao")
    op.drop_column("vinculos_de_sessao", "telefone_indice")
    op.drop_column("vinculos_de_sessao", "telefone_cifrado")
    op.alter_column("vinculos_de_sessao", "telefone", nullable=False)
    op.create_index("ix_vinculos_de_sessao_telefone", "vinculos_de_sessao", ["telefone"])

    chave_do_lead = get_settings().auditoria_chave_do_lead
    reindexar(
        conn,
        tabelas=_TABELAS,
        nova_chave=lambda _channel, valor: valor,
        modo="reversao",
        chave_do_lead_antiga=chave_do_lead,
        chave_do_lead_nova=chave_do_lead,
    )
    op.drop_table("identidades_de_lead")

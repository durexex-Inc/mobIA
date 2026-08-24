"""linha do tempo da conversa, telemetria e cifra do conteudo

TEC-126. Tres mudancas na mesma tabela, numa migration so porque nenhuma delas
deixa o esquema coerente sozinha:

* `messages` deixa de ser "o que chegou" e vira a linha do tempo da conversa.
* `text_body` e `raw_payload` passam a bytea cifrado.
* `message_telemetry` nasce.

O `downgrade` **apaga as linhas OUTBOUND**: elas nao cabem no esquema anterior,
onde `provider_message_id` e `status` sao NOT NULL. E perda de dado consciente,
e o motivo de o rollback so ser seguro enquanto o agente do TEC-134 nao existir.

Revision ID: 0004
Revises: 0003
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from mobia.infra.crypto import aad_de, decrypt, decrypt_json, encrypt, encrypt_json

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# O ADD COLUMN anterior ja travou messages em ACCESS EXCLUSIVE, e essa trava so
# solta no fim da transacao da migration inteira -- ela nao piora com o lote.
# O que o lote evita e ler a tabela inteira de uma vez para dentro da memoria
# do processo do alembic (nao do Postgres), que cresce sem limite com o numero
# de linhas, e encurtar cada UPDATE individual para nao alongar por quanto
# tempo mais nada consegue escrever em messages.
_TAMANHO_DO_LOTE = 500


def _em_lotes(conexao: sa.engine.Connection, tamanho: int):
    """Pagina messages por id, em ordem, sem OFFSET.

    Keyset (id > ultimo_id) em vez de OFFSET porque OFFSET teria de reler e
    descartar as linhas dos lotes anteriores a cada volta -- O(n^2) numa
    tabela grande. `id` ja e chave natural de ordenacao, unica e estavel
    durante a migration (a tabela esta com ACCESS EXCLUSIVE, nada mais escreve).
    """
    ultimo_id = None
    while True:
        if ultimo_id is None:
            consulta = sa.text(
                "SELECT id, text_body, raw_payload FROM messages ORDER BY id LIMIT :tamanho"
            )
            parametros: dict[str, object] = {"tamanho": tamanho}
        else:
            consulta = sa.text(
                "SELECT id, text_body, raw_payload FROM messages"
                " WHERE id > :ultimo_id ORDER BY id LIMIT :tamanho"
            )
            parametros = {"ultimo_id": ultimo_id, "tamanho": tamanho}

        linhas = conexao.execute(consulta, parametros).fetchall()
        if not linhas:
            return
        yield linhas
        ultimo_id = linhas[-1].id


_PARA_O_DOMINIO = """
    UPDATE messages SET content_type = CASE content_type
        WHEN 'text' THEN 'TEXTO'
        WHEN 'audio' THEN 'AUDIO'
        WHEN 'image' THEN 'IMAGEM'
        WHEN 'document' THEN 'DOCUMENTO'
        ELSE 'DESCONHECIDO'
    END
"""

_PARA_A_META = """
    UPDATE messages SET content_type = CASE content_type
        WHEN 'TEXTO' THEN 'text'
        WHEN 'AUDIO' THEN 'audio'
        WHEN 'IMAGEM' THEN 'image'
        WHEN 'DOCUMENTO' THEN 'document'
        ELSE 'unknown'
    END
"""


def upgrade() -> None:
    # 1. Colunas da linha do tempo, nullable primeiro para poder preencher.
    op.add_column("messages", sa.Column("role", sa.String(16), nullable=True))
    op.add_column("messages", sa.Column("direction", sa.String(8), nullable=True))
    op.add_column("messages", sa.Column("conversation_key", sa.String(64), nullable=True))
    op.execute(
        """
        UPDATE messages
           SET role = 'LEAD',
               direction = 'INBOUND',
               conversation_key = sender_external_id
        """
    )
    op.alter_column("messages", "role", nullable=False)
    op.alter_column("messages", "direction", nullable=False)
    op.alter_column("messages", "conversation_key", nullable=False)

    # 2. `received_at` mente numa linha de saida.
    op.alter_column("messages", "received_at", new_column_name="created_at")
    op.drop_index("ix_messages_status_received_at", table_name="messages")
    op.create_index("ix_messages_status_created_at", "messages", ["status", "created_at"])

    # 3. O que so a entrada tem passa a nullable.
    op.alter_column("messages", "provider_message_id", nullable=True)
    op.alter_column("messages", "sender_external_id", nullable=True)
    op.alter_column("messages", "recipient_external_id", nullable=True)
    op.alter_column("messages", "status", nullable=True)

    op.execute(_PARA_O_DOMINIO)

    # 4. Cifra. Colunas novas, backfill, troca -- nunca `USING` no ALTER, porque
    # a cifra acontece em Python e o banco nao tem a chave.
    op.add_column("messages", sa.Column("text_body_cifrado", sa.LargeBinary(), nullable=True))
    op.add_column("messages", sa.Column("raw_payload_cifrado", sa.LargeBinary(), nullable=True))

    conexao = op.get_bind()
    for linhas in _em_lotes(conexao, _TAMANHO_DO_LOTE):
        conexao.execute(
            sa.text(
                "UPDATE messages"
                "   SET text_body_cifrado = :texto, raw_payload_cifrado = :payload"
                " WHERE id = :id"
            ),
            [
                {
                    "id": linha.id,
                    "texto": encrypt(linha.text_body, aad_de(linha.id, "text_body")),
                    "payload": encrypt_json(linha.raw_payload, aad_de(linha.id, "raw_payload")),
                }
                for linha in linhas
            ],
        )

    op.drop_column("messages", "text_body")
    op.drop_column("messages", "raw_payload")
    op.alter_column("messages", "text_body_cifrado", new_column_name="text_body")
    op.alter_column("messages", "raw_payload_cifrado", new_column_name="raw_payload")

    # 5. O indice da consulta de TEC-127.
    op.create_index(
        "ix_messages_timeline",
        "messages",
        ["channel", "conversation_key", sa.text("created_at DESC")],
    )

    # 6. Telemetria.
    op.create_table(
        "message_telemetry",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("subagent", sa.String(32), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        # Nullable: nem todo turno usa cache e o agente do TEC-134 ainda nao
        # existe. Nascem aqui para capturar o dado desde a primeira linha --
        # numero nao gravado nao se recupera. Precificacao ciente de cache fica
        # para a historia que liga o agente.
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("message_telemetry")
    op.drop_index("ix_messages_timeline", table_name="messages")

    # A linha de saida nao cabe no esquema anterior. Ver a docstring do modulo.
    op.execute("DELETE FROM messages WHERE direction = 'OUTBOUND'")

    op.add_column("messages", sa.Column("text_body_claro", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("raw_payload_claro", postgresql.JSONB(), nullable=True))

    conexao = op.get_bind()
    for linhas in _em_lotes(conexao, _TAMANHO_DO_LOTE):
        conexao.execute(
            sa.text(
                "UPDATE messages"
                "   SET text_body_claro = :texto,"
                "       raw_payload_claro = CAST(:payload AS jsonb)"
                " WHERE id = :id"
            ),
            [
                {
                    "id": linha.id,
                    "texto": decrypt(linha.text_body, aad_de(linha.id, "text_body")),
                    # O CAST no SQL espera texto JSON ou NULL, entao o dict
                    # decifrado volta a ser string aqui.
                    "payload": None
                    if linha.raw_payload is None
                    else json.dumps(
                        decrypt_json(linha.raw_payload, aad_de(linha.id, "raw_payload"))
                    ),
                }
                for linha in linhas
            ],
        )

    op.drop_column("messages", "text_body")
    op.drop_column("messages", "raw_payload")
    op.alter_column("messages", "text_body_claro", new_column_name="text_body")
    op.alter_column("messages", "raw_payload_claro", new_column_name="raw_payload")
    op.execute("UPDATE messages SET raw_payload = '{}'::jsonb WHERE raw_payload IS NULL")
    op.alter_column("messages", "raw_payload", nullable=False)

    op.execute(_PARA_A_META)

    op.alter_column("messages", "status", nullable=False)
    op.alter_column("messages", "recipient_external_id", nullable=False)
    op.alter_column("messages", "sender_external_id", nullable=False)
    op.alter_column("messages", "provider_message_id", nullable=False)

    # Renomeia antes de indexar: o create_index referencia a coluna pelo nome, e
    # ate o alter_column ela ainda se chama `created_at`.
    op.drop_index("ix_messages_status_created_at", table_name="messages")
    op.alter_column("messages", "created_at", new_column_name="received_at")
    op.create_index("ix_messages_status_received_at", "messages", ["status", "received_at"])

    op.drop_column("messages", "conversation_key")
    op.drop_column("messages", "direction")
    op.drop_column("messages", "role")

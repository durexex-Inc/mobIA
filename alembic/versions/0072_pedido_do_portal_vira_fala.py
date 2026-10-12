"""os pedidos de interesse ja gravados ganham a fala que a lista de leads exige

A lista de `/leads` e a coorte do funil nascem de `messages`, e o portal nao
gravava mensagem: o lead dele nao existia para nenhuma das duas. Daqui para
frente `registrar_interesse` grava a fala junto com o pedido; esta migration
faz o mesmo para os pedidos anteriores, com o `criado_em` do pedido.

Idempotente pelo `provider_message_id` (`interesse:<id do pedido>`), o mesmo que
o codigo novo grava. So o PRIMEIRO pedido de cada lead interessa a `Novo`, mas
cada pedido vira uma fala -- como no caminho novo.

O texto e cifrado com `mobia.infra.crypto`, como a 0004. O downgrade apaga so
as falas que esta migration e o codigo novo criaram, pelo mesmo prefixo.

Revision ID: 0072
Revises: 0071
"""

import uuid

import sqlalchemy as sa

from alembic import op
from mobia.infra.crypto import aad_de, encrypt

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

_TEXTO = "Pedido de interesse em imóvel, feito pelo portal."


def upgrade() -> None:
    conexao = op.get_bind()
    pedidos = conexao.execute(
        sa.text(
            "SELECT s.id, s.channel, s.conversation_key, s.criado_em "
            "FROM solicitacoes_de_interesse s "
            "WHERE NOT EXISTS (SELECT 1 FROM messages m "
            "WHERE m.channel = s.channel "
            "AND m.provider_message_id = 'interesse:' || s.id::text)"
        )
    ).all()
    for pedido in pedidos:
        fala_id = uuid.uuid4()
        conexao.execute(
            sa.text(
                "INSERT INTO messages (id, channel, provider_message_id, sender_external_id, "
                "conversation_key, role, direction, content_type, text_body, status, created_at) "
                "VALUES (:id, :channel, :provider, :chave, :chave, 'LEAD', 'INBOUND', 'TEXTO', "
                ":texto, NULL, :criado_em)"
            ),
            {
                "id": fala_id,
                "channel": pedido.channel,
                "provider": f"interesse:{pedido.id}",
                "chave": pedido.conversation_key,
                "texto": encrypt(_TEXTO, aad_de(fala_id, "text_body")),
                "criado_em": pedido.criado_em,
            },
        )


def downgrade() -> None:
    op.execute("DELETE FROM messages WHERE provider_message_id LIKE 'interesse:%'")

"""o `provider_message_id` do WhatsApp deixa de guardar o wamid cru

TEC-383, RNF-13. O wamid da Meta carrega o `wa_id` do lead em base64, e
`messages.provider_message_id` o guardava em claro em toda mensagem de
entrada do WhatsApp -- o telefone que a TEC-203 tirou do resto da tabela. A
subida troca cada wamid pelo HMAC que o parser passou a gravar
(`identidade/indice.py::chave_de_mensagem`); a UNIQUE continua valendo, porque
o HMAC e deterministico e wamids distintos dao HMACs distintos.

**Em Python, pela razao da 0004 e da 0062: o banco nao tem a chave.**

**Quem ja e HMAC ou pseudonimo fica.** O filtro e `LIKE 'wamid.%'`: o HMAC e
hex puro e o pseudonimo da anonimizacao (TEC-207) comeca por `anon:`, entao
nenhum dos dois casa -- e uma subida interrompida se retoma sem reprocessar
o que ja trocou.

**A descida restaura o wamid a partir do `raw_payload`**, que guarda o objeto
da mensagem com o `id` cru, cifrado. Linha cujo raw ja foi esvaziado pela
retencao ou pela anonimizacao fica como esta: nao ha de onde tirar o wamid, e
o HMAC continua cumprindo a UNIQUE.

**Rode com o webhook parado**, como a 0062. Uma reentrega que chegue entre o
deploy do codigo novo e o fim desta subida gravaria o HMAC enquanto a linha
original ainda tem o wamid cru, e a UNIQUE nao a descartaria.

Revision ID: 0066
Revises: 0065
"""

from sqlalchemy import text

from alembic import op
from mobia.domain.identidade.indice import chave_de_mensagem
from mobia.infra.crypto import aad_de, decrypt_json

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

# Copiado, e nao importado de `messages/canais.py`: migration aplicada nao
# muda quando o codigo muda.
_CANAL = "whatsapp"


def upgrade() -> None:
    conn = op.get_bind()
    linhas = conn.execute(
        text(
            "SELECT id, provider_message_id FROM messages"
            " WHERE channel = :c AND provider_message_id LIKE 'wamid.%'"
        ),
        {"c": _CANAL},
    ).all()
    for identificador, wamid in linhas:
        conn.execute(
            text("UPDATE messages SET provider_message_id = :novo WHERE id = :id"),
            {"novo": chave_de_mensagem(_CANAL, wamid), "id": identificador},
        )


def downgrade() -> None:
    conn = op.get_bind()
    linhas = conn.execute(
        text(
            "SELECT id, raw_payload FROM messages"
            " WHERE channel = :c AND raw_payload IS NOT NULL"
            " AND provider_message_id NOT LIKE 'anon:%'"
        ),
        {"c": _CANAL},
    ).all()
    for identificador, blob in linhas:
        raw = decrypt_json(bytes(blob), aad_de(identificador, "raw_payload")) or {}
        wamid = raw.get("id")
        if isinstance(wamid, str) and wamid.startswith("wamid."):
            conn.execute(
                text("UPDATE messages SET provider_message_id = :w WHERE id = :id"),
                {"w": wamid, "id": identificador},
            )

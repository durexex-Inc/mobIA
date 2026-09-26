"""A referencia ao lead que a trilha guarda no lugar do telefone. TEC-206, D4.

Quando a TEC-206 nasceu, no WhatsApp o `conversation_key` ERA o telefone do
lead, e o lead nao tinha outro identificador. Gravar o par na trilha seria
gravar o dado pessoal que a card proibia; gravar o HMAC dele permite achar os
eventos de um lead sem guarda-lo. Desde a TEC-203 o proprio `conversation_key`
ja e um HMAC do telefone (`identidade/indice.py::chave_de`), e o `lead_ref` e
um HMAC por cima dele, com chave propria.

**A chave e propria** (`AUDITORIA_CHAVE_DO_LEAD`), e nao a de
`infra/crypto.py`: chaves com funcoes diferentes nao se reaproveitam. Trocada
sozinha, ela tornaria a trilha inteira impesquisavel -- todo `lead_ref` antigo
deixaria de bater com o recalculado. Por isso so roda pelo
`scripts/reindexar_leads.py`, com a chave velha em
`AUDITORIA_CHAVE_DO_LEAD_ANTERIOR` e a nova em `AUDITORIA_CHAVE_DO_LEAD`: o
script recalcula cada `lead_ref` dos pares conhecidos da chave velha para a
nova (ver `docs/seguranca/segredos.md`).
"""

import hashlib
import hmac


def lead_ref(channel: str, conversation_key: str, *, chave: str) -> str:
    """HMAC-SHA256 de `channel:conversation_key`, em hex (64 caracteres).

    Estavel, nao reversivel sem a chave, e sobrevive a eliminacao do lead
    (RNF-21) sem guardar nada que o identifique.
    """
    mensagem = f"{channel}:{conversation_key}".encode()
    return hmac.new(chave.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()

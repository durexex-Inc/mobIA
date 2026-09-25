"""A referencia ao lead que a trilha guarda no lugar do telefone. TEC-206, D4.

No WhatsApp, `conversation_key` E o telefone do lead, e o lead nao tem outro
identificador. Gravar o par na trilha seria gravar o dado pessoal que a card
proibe; gravar o HMAC dele permite achar os eventos de um lead sem guarda-lo.

**A chave e propria** (`AUDITORIA_CHAVE_DO_LEAD`), e nao a de
`infra/crypto.py`: chaves com funcoes diferentes nao se reaproveitam, e esta
nao pode rodar sem tornar a trilha inteira impesquisavel -- todo `lead_ref`
antigo deixaria de bater com o recalculado.
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

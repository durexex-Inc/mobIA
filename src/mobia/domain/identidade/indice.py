"""A chave do lead e a porta para o valor cru dele. TEC-203, D2.

O `conversation_key` de toda tabela guarda `chave_de(channel, valor)`, e nao o
valor: no WhatsApp o valor e o telefone. O valor cru mora cifrado em
`identidades_de_lead` e sai so por `revelar`/`telefones_de`, nas bordas que
precisam dele.

**`chave_de` nao normaliza, de proposito.** Antes desta card a chave era o
`wa_id` cru, e dois `wa_id` diferentes (com e sem o 9) eram duas conversas; o
envio vai para o `wa_id` que a Meta mandou. Normalizar aqui juntaria as duas e
mandaria para uma grafia que a Meta talvez nao reconheca. Quem precisa do
TELEFONE -- busca, absorcao, o vinculo do widget -- usa `indice_de_telefone`,
sobre a forma canonica de `telefone.normalizar`.

Unico modulo que conhece `lead_indice_chave`.
"""

import hashlib
import hmac

from mobia.app.config import get_settings


def _hmac(mensagem: str) -> str:
    chave = get_settings().lead_indice_chave.encode("utf-8")
    return hmac.new(chave, mensagem.encode("utf-8"), hashlib.sha256).hexdigest()


def chave_de(channel: str, valor: str) -> str:
    """HMAC-SHA256 de `channel:valor`, em hex. Cabe no `String(64)` de sempre."""
    return _hmac(f"{channel}:{valor}")


def indice_de_telefone(canonico: str) -> str:
    """HMAC de `telefone:{canonico}`. O prefixo o separa de qualquer chave de canal."""
    return _hmac(f"telefone:{canonico}")

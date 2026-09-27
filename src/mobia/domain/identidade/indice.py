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
from collections.abc import Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.identidade.models import (
    IdentidadeDeLead,
    VinculoDeSessao,
    aad_da_identidade,
    aad_do_vinculo,
)
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.infra.crypto import decrypt, encrypt


def _hmac(mensagem: str) -> str:
    chave = get_settings().lead_indice_chave.encode("utf-8")
    return hmac.new(chave, mensagem.encode("utf-8"), hashlib.sha256).hexdigest()


def chave_de(channel: str, valor: str) -> str:
    """HMAC-SHA256 de `channel:valor`, em hex. Cabe no `String(64)` de sempre."""
    return _hmac(f"{channel}:{valor}")


def chave_de_mensagem(channel: str, id_do_provedor: str) -> str:
    """HMAC de `mensagem:{channel}:{id}`: o `provider_message_id` do WhatsApp. TEC-383.

    O wamid da Meta e base64 de um protobuf que carrega o `wa_id` do lead em
    claro (`HBgNNTU0ODk5...` decodifica para `...5548999...`). Gravado cru,
    ele devolvia o telefone que `chave_de` existe para tirar da tabela. O HMAC
    e deterministico, entao a UNIQUE `(channel, provider_message_id)` continua
    descartando a reentrega (TEC-125) -- e o prefixo `mensagem:` o separa de
    qualquer chave de lead ou de telefone.

    O wamid cru continua existindo, cifrado, em `raw_payload`: e de la que o
    indicador de digitacao o le (`outbound/presenca.py`).
    """
    return _hmac(f"mensagem:{channel}:{id_do_provedor}")


def indice_de_telefone(canonico: str) -> str:
    """HMAC de `telefone:{canonico}`. O prefixo o separa de qualquer chave de canal."""
    return _hmac(f"telefone:{canonico}")


class IdentidadeAusente(Exception):
    """Chave sem identidade. E bug de dado, nunca caso de negocio."""


async def registrar(session: AsyncSession, channel: str, valor: str) -> str:
    """Grava a identidade se ainda nao existe; devolve a chave. Nao commita --
    entra na mesma transacao de quem grava a linha que usa a chave."""
    chave = chave_de(channel, valor)
    await session.execute(
        pg_insert(IdentidadeDeLead)
        .values(
            channel=channel,
            conversation_key=chave,
            valor_cifrado=encrypt(valor, aad_da_identidade(channel, chave)),
        )
        .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
    )
    return chave


async def revelar(session: AsyncSession, channel: str, chave: str) -> str:
    """O valor cru por tras da chave. Sem identidade levanta `IdentidadeAusente`
    -- nunca devolve a propria chave como se fosse o valor."""
    blob = await session.scalar(
        select(IdentidadeDeLead.valor_cifrado).where(
            IdentidadeDeLead.channel == channel, IdentidadeDeLead.conversation_key == chave
        )
    )
    if blob is None:
        # Sem o valor na mensagem: a chave nao e o telefone, mas e pseudonimo
        # estavel do lead, e o canal basta para diagnosticar -- o log agregado
        # nao precisa de mais.
        raise IdentidadeAusente(f"sem identidade para uma chave do canal {channel}")
    valor = decrypt(bytes(blob), aad_da_identidade(channel, chave))
    assert valor is not None
    return valor


async def telefones_de(
    session: AsyncSession, pares: Sequence[tuple[str, str]]
) -> dict[tuple[str, str], str | None]:
    """O telefone de cada lead, em digitos, pelas duas origens. TEC-129 e TEC-203.

    No WhatsApp e o `wa_id` na forma canonica de `normalizar` -- ou, quando o
    numero nao e brasileiro e `normalizar` devolve `None`, o proprio `wa_id`,
    que a Meta ja entrega em E.164 sem o `+`: lead estrangeiro continua tendo
    telefone para CRM, e-mail e agenda. No web, o que o lead digitou no
    widget, se digitou. `None` e "nao ha telefone", nunca a chave no lugar --
    inclusive para a chave do WhatsApp sem identidade, que e bug de dado mas
    nao motivo para derrubar uma listagem inteira.
    """
    resultado: dict[tuple[str, str], str | None] = {par: None for par in pares}
    do_whatsapp = [chave for channel, chave in pares if channel == CANAL_WHATSAPP]
    # Cada consulta so roda com lista cheia: com a lista vazia ela seria uma ida
    # ao banco que nao pode achar nada.
    if do_whatsapp:
        linhas = await session.execute(
            select(
                IdentidadeDeLead.channel,
                IdentidadeDeLead.conversation_key,
                IdentidadeDeLead.valor_cifrado,
            ).where(
                IdentidadeDeLead.channel == CANAL_WHATSAPP,
                IdentidadeDeLead.conversation_key.in_(do_whatsapp),
            )
        )
        for channel, chave, blob in linhas:
            valor = decrypt(bytes(blob), aad_da_identidade(channel, chave))
            resultado[(channel, chave)] = (normalizar(valor) or valor) if valor else None
    dos_outros = [par for par in pares if par[0] != CANAL_WHATSAPP]
    if dos_outros:
        vinculos = await session.execute(
            select(
                VinculoDeSessao.channel,
                VinculoDeSessao.conversation_key,
                VinculoDeSessao.telefone_cifrado,
            ).where(
                tuple_(VinculoDeSessao.channel, VinculoDeSessao.conversation_key).in_(dos_outros)
            )
        )
        for channel, chave, blob in vinculos:
            resultado[(channel, chave)] = decrypt(bytes(blob), aad_do_vinculo(channel, chave))
    return resultado

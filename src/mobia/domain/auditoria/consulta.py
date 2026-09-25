"""O que se pede a trilha de auditoria, e onde a pagina seguinte comeca. TEC-206, D8.

Modulo sem I/O, no molde de `leads/consulta.py`, de quem reaproveita
`FiltroInvalido` e os limites de pagina: a convencao de 422 e de pagina e uma
so para as duas listas do painel. O cursor e proprio, porque a ordem aqui e
`(criado_em DESC, id DESC)`, e nao score. Quem toca o banco e `repositorio.py`.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.leads.consulta import LIMITE_MAXIMO, LIMITE_PADRAO, FiltroInvalido


@dataclass(frozen=True)
class CursorDaTrilha:
    """O ULTIMO item da pagina atual. `id` desempata dois eventos no mesmo instante."""

    criado_em: datetime
    id: uuid.UUID

    def codificar(self) -> str:
        """base64 de um JSON, opaco pelo mesmo contrato do cursor da TEC-192."""
        corpo = json.dumps(
            {"t": self.criado_em.isoformat(), "i": str(self.id)}, separators=(",", ":")
        )
        return base64.urlsafe_b64encode(corpo.encode("utf-8")).decode("ascii")


def decodificar_cursor(texto: str) -> CursorDaTrilha:
    """O cursor que `codificar` produziu. Levanta `FiltroInvalido` para o resto.

    `ValueError` cobre base64, UTF-8, JSON, data e uuid malformados (todos
    herdam dele); `KeyError`, `TypeError` e `AttributeError` cobrem o JSON bem
    formado com a forma errada. Cursor sem fuso tambem e recusado: comparar
    `timestamptz` com instante ingenuo o leria no fuso da sessao do banco.
    """
    try:
        corpo = json.loads(base64.urlsafe_b64decode(texto.encode("ascii")))
        criado_em = datetime.fromisoformat(corpo["t"])
        evento_id = uuid.UUID(corpo["i"])
    except (ValueError, KeyError, TypeError, AttributeError) as erro:
        raise FiltroInvalido("cursor invalido") from erro
    if criado_em.tzinfo is None:
        raise FiltroInvalido("cursor invalido")
    return CursorDaTrilha(criado_em=criado_em, id=evento_id)


@dataclass(frozen=True)
class FiltroDaTrilha:
    """O recorte pedido. O lead ja chega como `lead_ref` -- o telefone nao fica."""

    ator_id: str | None = None
    acoes: tuple[str, ...] = ()
    de: datetime | None = None
    ate: datetime | None = None
    lead_ref: str | None = None
    limite: int = LIMITE_PADRAO
    cursor: CursorDaTrilha | None = None


def montar_filtro(
    *,
    ator: str | None = None,
    acoes: tuple[str, ...] = (),
    de: datetime | None = None,
    ate: datetime | None = None,
    channel: str | None = None,
    conversation_key: str | None = None,
    limite: int = LIMITE_PADRAO,
    cursor: str | None = None,
    chave_do_lead: str,
) -> FiltroDaTrilha:
    """Valida na borda o que o SQL nao valida sozinho.

    **O par do lead vai junto ou nao vai.** Metade dele ignorada viraria a
    trilha de todos os leads para quem pediu a de um so. O servidor
    transforma o par em `lead_ref` e nao guarda o telefone que recebeu.

    `ator` e texto exato, e nao UUID: `token-compartilhado` e um `ator_id`
    legitimo e precisa ser pesquisavel.
    """
    if not 1 <= limite <= LIMITE_MAXIMO:
        raise FiltroInvalido(f"limite fora da faixa 1..{LIMITE_MAXIMO}: {limite}")

    desconhecidas = sorted(set(acoes) - {acao.value for acao in Acao})
    if desconhecidas:
        raise FiltroInvalido(f"acao desconhecida: {', '.join(desconhecidas)}")

    for nome, instante in (("de", de), ("ate", ate)):
        if instante is not None and instante.tzinfo is None:
            raise FiltroInvalido(f"{nome} precisa de fuso (ISO-8601 com offset)")
    if de is not None and ate is not None and de >= ate:
        raise FiltroInvalido("de precisa ser anterior a ate")

    if (channel is None) != (conversation_key is None):
        raise FiltroInvalido("channel e conversationKey vao juntos")
    referencia = (
        lead_ref(channel, conversation_key, chave=chave_do_lead)
        if channel is not None and conversation_key is not None
        else None
    )

    return FiltroDaTrilha(
        ator_id=ator,
        acoes=tuple(acoes),
        de=de,
        ate=ate,
        lead_ref=referencia,
        limite=limite,
        cursor=decodificar_cursor(cursor) if cursor else None,
    )

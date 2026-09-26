"""A conversa inteira do lead, em paginas, da mais recente para tras. TEC-193.

D5 do desenho, para a tela da TEC-324: paginas de 100 falas, a rolagem comeca
na mais recente e "carregar anteriores" pagina para tras.

**Uma conversa e o par do endereco, e so ele** (D7). A sessao web e o WhatsApp
da mesma pessoa, que `vinculos_de_sessao` liga desde a TEC-129, continuam sendo
dois leads -- como na lista.

**A fala retida pela moderacao** so aparece para quem `ve_retidas`, e mesmo
assim sem conteudo: a TEC-236 a tirou do contexto e do resumo, e esta seria a
primeira tela a devolve-la. Para os outros ela nao existe -- e o filtro e do
`WHERE`, e nao do laco depois dele, para que a pagina de 100 tenha 100 falas
visiveis.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.leads.consulta import FiltroInvalido
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, decrypt

# O numero da TEC-324 ("carrega as ultimas 100 falas"), e o teto para que
# `?limite=100000` nao decifre a conversa inteira numa resposta so.
LIMITE_PADRAO_DA_TRANSCRICAO = 100
LIMITE_MAXIMO_DA_TRANSCRICAO = 200


@dataclass(frozen=True)
class CursorDaTranscricao:
    """A fala MAIS ANTIGA da pagina atual: as anteriores comecam antes dela.

    **O par `(em, message_id)`, e nao so o instante.** `_persist` grava o lote
    de um envelope num INSERT so, e `created_at` cai no `now()` do statement,
    igual para todas as linhas dele -- a mesma razao que `historico_da_sessao`
    (TEC-124) escreve para desempatar por `id`. So o instante pularia ou
    repetiria falas na fronteira de um lote.

    Ao contrario do cursor da lista antes da TEC-195, este nunca carregou dado
    pessoal: o id de uma mensagem nao diz nada sobre quem falou.
    """

    em: datetime
    message_id: uuid.UUID

    def codificar(self) -> str:
        """base64 de um JSON, opaco pelo mesmo contrato de `consulta.Cursor`."""
        corpo = json.dumps(
            {"t": self.em.isoformat(), "m": str(self.message_id)}, separators=(",", ":")
        )
        return base64.urlsafe_b64encode(corpo.encode("utf-8")).decode("ascii")


def decodificar_cursor_da_transcricao(texto: str) -> CursorDaTranscricao:
    """O cursor que `codificar` produziu. Levanta `FiltroInvalido` para o resto.

    Recusa e nao volta para a pagina mais recente, pela razao de
    `consulta.decodificar_cursor`: quem chamou perdeu o lugar, e devolver o fim
    da conversa em silencio faria a tela empilha-lo acima do que ja mostra.
    """
    try:
        corpo = json.loads(base64.urlsafe_b64decode(texto.encode("ascii")))
        em = datetime.fromisoformat(corpo["t"])
        if em.tzinfo is None:
            # Um instante sem fuso comparado a `timestamptz` seria lido no fuso
            # da sessao do banco, e o cursor apontaria para outro lugar.
            raise ValueError("cursor sem fuso")
        return CursorDaTranscricao(em=em, message_id=uuid.UUID(corpo["m"]))
    except (ValueError, KeyError, TypeError) as erro:
        raise FiltroInvalido("cursor invalido") from erro


def validar_limite_da_transcricao(limite: int) -> int:
    if not 1 <= limite <= LIMITE_MAXIMO_DA_TRANSCRICAO:
        raise FiltroInvalido(f"limite fora da faixa 1..{LIMITE_MAXIMO_DA_TRANSCRICAO}: {limite}")
    return limite


@dataclass(frozen=True)
class Fala:
    """Uma linha da transcricao.

    `autor` e o `role` cru, um dos quatro de `ck_messages_role`: a TEC-324 pede
    rotulo textual para os quatro, e traduzi-los aqui seria texto de tela no
    backend.

    **`conteudo` nulo e "nao ha texto"** -- midia, ou fala gravada sem corpo --,
    e `tipo` diz qual. Numa fala `retida`, e nulo sempre.
    """

    id: uuid.UUID
    autor: str
    tipo: str
    conteudo: str | None
    retida: bool
    em: datetime


async def pagina_da_transcricao(
    session: AsyncSession,
    *,
    par: tuple[str, str],
    limite: int,
    cursor: CursorDaTranscricao | None,
    ve_retidas: bool,
) -> tuple[list[Fala], CursorDaTranscricao | None]:
    """A pagina em ordem cronologica, e o cursor das anteriores ou `None`.

    **Desce por `(created_at DESC, id DESC)` para o `LIMIT` cortar as mais
    antigas**, e a pagina e revertida antes de sair: quem le a tela le de cima
    para baixo, e a rolagem comeca embaixo, na mais recente. Pede uma fala a
    mais do que o limite e a descarta, para saber se ha anteriores sem um
    `COUNT(*)`.

    **Cursor de mensagem de outro lead e `FiltroInvalido`**, e nao pagina
    vazia: ele so chega aqui montado a mao ou trocado entre abas, e em nenhum
    dos dois casos "nao ha anteriores" seria a verdade.
    """
    channel, conversation_key = par
    consulta = select(Message).where(
        Message.channel == channel, Message.conversation_key == conversation_key
    )
    if not ve_retidas:
        consulta = consulta.where(Message.bloqueada_em.is_(None))

    if cursor is not None:
        dono = (
            await session.execute(
                select(Message.channel, Message.conversation_key).where(
                    Message.id == cursor.message_id
                )
            )
        ).first()
        if dono is None or (dono.channel, dono.conversation_key) != par:
            raise FiltroInvalido("cursor invalido")
        consulta = consulta.where(
            func.row(Message.created_at, Message.id) < func.row(cursor.em, cursor.message_id)
        )

    linhas = (
        (
            await session.execute(
                consulta.order_by(Message.created_at.desc(), Message.id.desc()).limit(limite + 1)
            )
        )
        .scalars()
        .all()
    )

    ha_anteriores = len(linhas) > limite
    visiveis = list(reversed(linhas[:limite]))

    falas = [
        Fala(
            id=linha.id,
            autor=linha.role,
            tipo=linha.content_type,
            conteudo=(
                None
                if linha.bloqueada_em is not None
                else decrypt(linha.text_body, aad_de(linha.id, "text_body"))
            ),
            retida=linha.bloqueada_em is not None,
            em=linha.created_at,
        )
        for linha in visiveis
    ]

    if not ha_anteriores or not falas:
        return falas, None
    mais_antiga = falas[0]
    return falas, CursorDaTranscricao(em=mais_antiga.em, message_id=mais_antiga.id)

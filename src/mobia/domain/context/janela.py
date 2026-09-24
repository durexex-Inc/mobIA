import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.repositorio import ResumoDaConversa
from mobia.domain.messages.models import Message


@dataclass(frozen=True)
class Marca:
    """Ate onde o resumo cobre.

    Par ordenavel em vez de contagem: contagem quebra quando uma linha e apagada
    ou quando duas mensagens chegam no mesmo instante.
    """

    created_at: datetime
    message_id: uuid.UUID


def marca_de(resumo: ResumoDaConversa | None) -> Marca | None:
    if resumo is None:
        return None
    return Marca(
        created_at=resumo.watermark_created_at,
        message_id=resumo.watermark_message_id,
    )


async def literais_apos(
    session: AsyncSession,
    channel: str,
    conversation_key: str,
    marca: Marca | None,
    *,
    pares_vinculados: Sequence[tuple[str, str]] = (),
) -> list[Message]:
    """Tudo o que ainda nao foi dobrado no resumo, em ordem cronologica.

    A comparacao e de tupla e nao de timestamp sozinho: duas mensagens no mesmo
    `created_at` fariam a janela pular uma ou repetir a outra. O par casa com
    `ix_messages_timeline (channel, conversation_key, created_at DESC)`.

    `pares_vinculados` (TEC-129, D4) sao as sessoes web que o turno do WhatsApp
    herdou: as falas delas entram na mesma janela, sob a mesma marca. A marca e
    uma tupla global `(created_at, id)`, e nao por par, entao uma fala web mais
    antiga que o resumo do WhatsApp fica de fora -- o que ela trouxe de
    criterio chega pela qualificacao, que a absorcao ja preencheu. Sem pares, o
    filtro e a igualdade de sempre.
    """
    filtro_do_par: ColumnElement[bool]
    if pares_vinculados:
        filtro_do_par = tuple_(Message.channel, Message.conversation_key).in_(
            [(channel, conversation_key), *pares_vinculados]
        )
    else:
        filtro_do_par = and_(
            Message.channel == channel, Message.conversation_key == conversation_key
        )
    condicoes: list[ColumnElement[bool]] = [
        filtro_do_par,
        # A fala que a moderacao de entrada bloqueou nao entra no contexto
        # (TEC-236). Filtrar **aqui** e nao no chamador e o que faz o resumo
        # herdar a correcao de graca: `dividir` recebe o que esta funcao
        # devolve, entao o que nao sai daqui nunca chega a dobra.
        #
        # A TEC-233 impedia so que a fala virasse resposta *naquele turno*. O
        # turno seguinte montava contexto decifrando-a inteira, e na dobra dos
        # ~40 turnos ela entrava no resumo permanente.
        Message.bloqueada_em.is_(None),
    ]
    if marca is not None:
        condicoes.append(
            tuple_(Message.created_at, Message.id)
            > tuple_(literal(marca.created_at), literal(marca.message_id))
        )

    resultado = await session.scalars(
        select(Message).where(*condicoes).order_by(Message.created_at, Message.id)
    )
    return list(resultado)


def deve_regenerar(quantidade: int, gatilho: int) -> bool:
    return quantidade >= gatilho


def dividir(
    literais: list[Message], minimas: int, *, piso_pode_ceder: bool = False
) -> tuple[list[Message], list[Message]]:
    """Separa o que vira resumo do que fica literal.

    O piso manda: por mais que se acumule, `minimas` mensagens sempre ficam na
    integra. E o que faz "as 20 mais recentes na integra" valer no turno logo
    apos uma regeneracao, e nao so no turno que a disparou.

    `piso_pode_ceder` e o unico jeito de dobrar abaixo do piso e existe para o
    ultimo degrau do laco do estouro. Vinte mensagens que sozinhas somam mais
    de 12.000 tokens existem -- vinte audios transcritos longos chegam la -- e
    quando o piso e o teto se contradizem o teto vence: ele e o limite fisico
    da chamada, o piso e preferencia de qualidade. Com a flag ligada o piso
    efetivo passa a ser uma mensagem, a mais recente da lista. Sem sessao
    vinculada essa e sempre a fala a que o modelo tem de responder, e sem ela
    nao ha turno. Com sessao vinculada (TEC-129, D4) `literais` intercala
    falas web, e a mais recente da lista pode ser uma fala web mais nova que a
    mensagem deste turno -- caso raro, exige atividade concorrente nos dois
    canais mais estouro de teto no mesmo turno: a mensagem respondida entao
    NAO e a que sobrevive, e pode ser dobrada para o resumo. O opt-in e
    explicito porque violar o piso e decisao de dominio, nao detalhe de
    implementacao -- quem chama tem de dizer, na chamada, que aceita a
    violacao.
    """
    piso = 1 if piso_pode_ceder else minimas
    if len(literais) <= piso:
        return [], literais
    corte = len(literais) - piso
    return literais[:corte], literais[corte:]

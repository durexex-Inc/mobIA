"""A lista de espera, gravada e lida de volta. TEC-169, RN-11.5.

Recebe a sessao e **nao commita** -- o commit e de quem chama, como em
`propostas.py`, `repositorio.py::reservar` e `registrar_handoff`. E o que
permite ao aceite da fila e ao handoff dele entrarem na MESMA transacao:
lead na fila sem handoff e o estado que a card existe para impedir.

Separado de `espera.py` pela mesma divisao que `remarcacao.py` e
`sweep_remarcacoes.py` fazem: la a regra pura, aqui o I/O. `espera.py` e
importavel por `tests/unit/` sem Postgres de pe, e continuaria sendo mesmo
que este modulo crescesse.

`ler_viva` devolve uma dataclass e nao o objeto do ORM, pela razao que
`propostas.py` escreve por extenso: quem consome nao pode depender de sessao
viva.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agendamento.models import ListaDeEspera


@dataclass(frozen=True)
class Espera:
    """Uma linha viva da fila, do jeito que a conversa precisa dela."""

    id: uuid.UUID
    imovel_id: uuid.UUID | None
    # Nulo enquanto a oferta esta de pe e o lead nao respondeu. Preenchido, e
    # o lugar dele na fila -- ver a D3 do desenho.
    aceita_em: datetime | None


async def oferecer(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    imovel_id: uuid.UUID | None,
    agora: datetime,
) -> Espera:
    """Grava a oferta da lista de espera, ou devolve a que ja esta viva.

    **Nao substitui a linha viva.** Um lead que pede visita tres vezes na
    mesma semana lotada recebe a oferta de novo, e isso e certo -- mas ele
    continua com UM lugar na fila, e com o `aceita_em` da primeira vez se ja
    tinha aceitado. Substituir devolveria ao fim da fila quem ja esperava, e
    a ordem de chegada e a unica regra que a card fixa.

    O indice parcial `uq_lista_de_espera_conversa_viva` e quem garante isso no
    banco; esta funcao so evita bater nele.
    """
    viva = await ler_viva(session, channel=channel, conversation_key=conversation_key)
    if viva is not None:
        return viva

    linha = ListaDeEspera(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        imovel_id=imovel_id,
        oferecida_em=agora,
    )
    session.add(linha)
    # O flush e o que da a garantia de que a linha existe antes de quem chama
    # seguir -- sem commitar, que continua sendo de quem chama.
    await session.flush()
    return Espera(id=linha.id, imovel_id=linha.imovel_id, aceita_em=None)


async def ler_viva(session: AsyncSession, *, channel: str, conversation_key: str) -> Espera | None:
    """A linha viva desta conversa: a oferta de pe, ou o lugar na fila.

    Viva e o mesmo predicado do indice parcial -- `recusada_em IS NULL AND
    avisada_em IS NULL`. Os dois textos tem de casar, ou a consulta e o indice
    passam a falar de conjuntos diferentes.
    """
    resultado = await session.execute(
        select(ListaDeEspera).where(
            ListaDeEspera.channel == channel,
            ListaDeEspera.conversation_key == conversation_key,
            ListaDeEspera.recusada_em.is_(None),
            ListaDeEspera.avisada_em.is_(None),
        )
    )
    linha = resultado.scalar_one_or_none()
    if linha is None:
        return None
    return Espera(id=linha.id, imovel_id=linha.imovel_id, aceita_em=linha.aceita_em)


async def aceitar(
    session: AsyncSession, *, espera_id: uuid.UUID, handoff_id: uuid.UUID, agora: datetime
) -> None:
    """Poe o lead na fila, com o momento de entrada e o handoff que abriu.

    **So marca o que ainda nao foi marcado** (`aceita_em IS NULL`): o lead que
    aceita duas vezes nao perde o lugar para si mesmo. Sem esse filtro, a
    segunda fala moveria `aceita_em` para agora e o poria atras de quem chegou
    depois dele.
    """
    await session.execute(
        update(ListaDeEspera)
        .where(ListaDeEspera.id == espera_id, ListaDeEspera.aceita_em.is_(None))
        .values(aceita_em=agora, handoff_id=handoff_id)
    )


async def recusar(session: AsyncSession, *, espera_id: uuid.UUID, agora: datetime) -> None:
    """O lead preferiu datas mais distantes: a oferta morre e ele nao entra.

    Nao e desistencia de quem estava na fila -- o CHECK
    `ck_lista_de_espera_desfecho_unico` recusa recusar o que ja foi aceito, e
    a conversa so chega aqui com a oferta ainda pendente.
    """
    await session.execute(
        update(ListaDeEspera)
        .where(ListaDeEspera.id == espera_id, ListaDeEspera.aceita_em.is_(None))
        .values(recusada_em=agora)
    )


async def primeiro_da_fila(session: AsyncSession, *, agora: datetime) -> ListaDeEspera | None:
    """Quem esperou mais, entre os que ainda nao foram avisados.

    Ordena por `aceita_em` e nao por `oferecida_em`, que e a D3: entrar na
    fila e aceitar. `agora` nao entra na consulta e e recebido assim mesmo,
    para que o dia em que a fila ganhar validade -- como o convite de
    remarcacao tem -- nao mude a assinatura de quem chama.
    """
    resultado = await session.execute(
        select(ListaDeEspera)
        .where(ListaDeEspera.aceita_em.is_not(None), ListaDeEspera.avisada_em.is_(None))
        .order_by(ListaDeEspera.aceita_em)
        .limit(1)
    )
    return resultado.scalar_one_or_none()


async def marcar_avisada(session: AsyncSession, *, espera_id: uuid.UUID, agora: datetime) -> None:
    """Tira da fila, tenha o lead respondido ou nao.

    Carimbada **tambem quando o envio nao saiu** por falta de template
    aprovado (TEC-373): senao o proximo slot ficaria preso atras de um lead
    que nao pode ser avisado, e a fila inteira travaria no primeiro. Ver a D7
    do desenho.
    """
    await session.execute(
        update(ListaDeEspera)
        .where(ListaDeEspera.id == espera_id, ListaDeEspera.avisada_em.is_(None))
        .values(avisada_em=agora)
    )

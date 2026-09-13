"""Assumir, devolver, e a pergunta que as quatro guardas fazem. TEC-179.

As duas consultas espelham `optout/repositorio.py` de proposito, inclusive na
assinatura: os sitios de chamada precisam exatamente dessas duas formas -- o
`sweep_followups` tem o par do lead, e o `GuardedOutbound.send` so tem o id da
mensagem. Duplicar a forma ali era a escolha certa e continua sendo aqui.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.atendimento.models import AtendimentoHumano
from mobia.domain.messages.models import Message


@dataclass(frozen=True)
class Atendimento:
    """O que a rota precisa devolver depois de assumir ou devolver."""

    assumido_por: uuid.UUID
    assumido_em: datetime


async def esta_silenciada(session: AsyncSession, *, channel: str, conversation_key: str) -> bool:
    """Alguem assumiu esta conversa e ainda nao devolveu.

    Sem linha nenhuma, nao esta -- o estado default e "o agente pode falar",
    mesma forma que `esta_em_optout` ja usa para o estado default de la.

    A condicao e `devolvido_em IS NULL` e nao uma coluna `ativo`: ver a D4 do
    desenho e o comentario do modelo. Esta funcao e a UNICA implementacao da
    frase "esta silenciada", pela mesma razao que o docstring de
    `sweep_followups` da para `esta_em_optout`.
    """
    achou = (
        await session.execute(
            select(AtendimentoHumano.id)
            .where(
                AtendimentoHumano.channel == channel,
                AtendimentoHumano.conversation_key == conversation_key,
                AtendimentoHumano.devolvido_em.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return achou is not None


async def esta_silenciada_por_mensagem(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """A mesma pergunta, para quem so tem o id da mensagem.

    E o caso da guarda em `GuardedOutbound.send`, cuja assinatura nao carrega
    o par da conversa. Mensagem inexistente devolve False: se nao ha conversa,
    nao ha atendimento humano a respeitar, e recusar o envio por isso
    esconderia o defeito real. Mesma decisao de
    `esta_em_optout_por_mensagem`.
    """
    conversa = (
        await session.execute(
            select(Message.channel, Message.conversation_key).where(Message.id == message_id)
        )
    ).one_or_none()
    if conversa is None:
        return False
    return await esta_silenciada(
        session, channel=conversa.channel, conversation_key=conversa.conversation_key
    )


async def assumir(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    corretor_id: uuid.UUID,
) -> Atendimento | None:
    """O corretor assume a conversa. `None` quando outro ja a tem.

    **Um statement, e nao um SELECT seguido de INSERT.** O SRS especifica 409
    "ja assumida por outro", e quem arbitra essa recusa e o UNIQUE
    `uq_atendimento_conversa`, nao a ordem do codigo -- mesmo raciocinio do
    `ON CONFLICT` de `registrar_handoff` e do UPDATE condicionado da rota de
    aceite da TEC-178. Duas abas do painel clicando ao mesmo tempo nao podem
    as duas se achar vencedoras.

    O `where` do `ON CONFLICT` e quem define quando a atualizacao vale: a
    conversa ja foi devolvida (qualquer um reassume), ou quem pede e o mesmo
    que ja a tem (idempotente). Fora desses dois casos nenhuma linha muda, o
    RETURNING vem vazio, e a resposta e `None`.

    **`assumido_em` NAO anda no caso idempotente.** O `case` abaixo e o que
    garante isso: quando a linha esta silenciada (`devolvido_em IS NULL`), o
    `where` ja provou que o pedinte e o dono atual, entao o carimbo antigo
    fica. Mover faria o corretor parecer ter pegado a conversa mais tarde do
    que pegou -- o mesmo argumento que a D8 da TEC-178 faz sobre `aceito_em`.
    """
    agora = datetime.now(UTC)
    statement = pg_insert(AtendimentoHumano).values(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        assumido_por=corretor_id,
        assumido_em=agora,
        criado_em=agora,
        atualizado_em=agora,
    )
    linha = (
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_atendimento_conversa",
                set_={
                    "assumido_por": corretor_id,
                    "assumido_em": case(
                        (AtendimentoHumano.devolvido_em.is_(None), AtendimentoHumano.assumido_em),
                        else_=agora,
                    ),
                    "devolvido_por": None,
                    "devolvido_em": None,
                    "atualizado_em": agora,
                },
                where=or_(
                    AtendimentoHumano.devolvido_em.is_not(None),
                    AtendimentoHumano.assumido_por == corretor_id,
                ),
            ).returning(AtendimentoHumano.assumido_por, AtendimentoHumano.assumido_em)
        )
    ).first()

    if linha is None:
        return None
    return Atendimento(assumido_por=linha.assumido_por, assumido_em=linha.assumido_em)


async def devolver(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    corretor_id: uuid.UUID,
) -> Atendimento | None:
    """O corretor devolve a conversa ao agente. `None` quando nao havia o que devolver.

    `devolvido_em IS NULL` no proprio WHERE, e o RETURNING decide -- nunca um
    SELECT antes. Devolver duas vezes nao pode gravar duas vezes, pelo mesmo
    motivo que assumir duas vezes nao move o carimbo.

    **Qualquer corretor pode devolver, nao so quem assumiu.** Nao ha
    identidade provada (D2 do desenho: o `corretor_id` e afirmacao de quem
    chama), entao exigir que fosse o mesmo daria uma sensacao de controle que
    o sistema nao tem -- e travaria o caso real de um corretor que assumiu e
    saiu de ferias. Quem devolveu fica gravado.
    """
    agora = datetime.now(UTC)
    linha = (
        await session.execute(
            update(AtendimentoHumano)
            .where(
                AtendimentoHumano.channel == channel,
                AtendimentoHumano.conversation_key == conversation_key,
                AtendimentoHumano.devolvido_em.is_(None),
            )
            .values(devolvido_por=corretor_id, devolvido_em=agora, atualizado_em=agora)
            .returning(AtendimentoHumano.assumido_por, AtendimentoHumano.assumido_em)
        )
    ).first()

    if linha is None:
        return None
    return Atendimento(assumido_por=linha.assumido_por, assumido_em=linha.assumido_em)

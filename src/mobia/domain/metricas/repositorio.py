"""As consultas agregadas do painel. TEC-190, RN-17.1 e RN-17.2.

**Todo numero deste modulo e sobre a COORTE** -- os leads cujo PRIMEIRO
contato caiu no periodo --, e nao sobre eventos ocorridos no periodo. Ver a
D10 do plano: por atividade, um lead recomendado em agosto que nasceu em
julho faria `Recomendado / Em conversa` passar de 100%, e a RN-17.2 pede uma
taxa de conversao, nao um numero acima de um.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos dez repositorios deste repo.
"""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.models import Recomendacao
from mobia.domain.context.models import LeadQualification
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.metricas.filtros import Recorte
from mobia.domain.metricas.vocabulario import Etapa

# O status de handoff que conta como aceito. Nao e enum importado porque
# `handoff/vocabulario.py` nomeia o ciclo inteiro e so este valor interessa
# aqui.
_ACEITO = "ACEITO"


def _nascimento() -> Any:
    """O instante do primeiro contato de cada conversa.

    `conversas` NAO tem `criado_em` -- as colunas dela sao `channel`,
    `conversation_key`, `status`, `motivo_do_encerramento` e `encerrada_em` --,
    entao o nascimento do lead sai da primeira linha em `messages`, que e a
    unica tabela com esse instante.
    """
    return (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.min(Message.created_at).label("nasceu_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )


def _coorte(recorte: Recorte) -> Select[Any]:
    """As conversas cujo PRIMEIRO contato caiu no periodo, ja filtradas."""
    nascimento = _nascimento()

    consulta = select(nascimento.c.channel, nascimento.c.conversation_key).where(
        nascimento.c.nasceu_em >= recorte.inicio,
        nascimento.c.nasceu_em < recorte.fim,
    )

    if recorte.canal is not None:
        consulta = consulta.where(nascimento.c.channel == recorte.canal)

    if recorte.intencao is not None or recorte.temperatura is not None:
        consulta = consulta.join(
            LeadQualification,
            (LeadQualification.channel == nascimento.c.channel)
            & (LeadQualification.conversation_key == nascimento.c.conversation_key),
        )
        if recorte.intencao is not None:
            consulta = consulta.where(LeadQualification.intencao == recorte.intencao)
        if recorte.temperatura is not None:
            consulta = consulta.where(LeadQualification.temperatura == recorte.temperatura)

    if recorte.corretor_id is not None:
        # D6 e lacuna L2: `corretor_id` so existe em `handoffs`, entao o lead
        # que ainda nao foi repassado nao aparece em filtro de corretor
        # nenhum. O funil filtrado e o dos leads que ACABARAM com ele.
        consulta = consulta.join(
            Handoff,
            (Handoff.channel == nascimento.c.channel)
            & (Handoff.conversation_key == nascimento.c.conversation_key),
        ).where(Handoff.corretor_id == recorte.corretor_id)

    return consulta


async def _quantos(session: AsyncSession, consulta: Select[Any]) -> int:
    alvo = consulta.distinct().subquery()
    return int((await session.execute(select(func.count()).select_from(alvo))).scalar_one())


async def contar_etapas(session: AsyncSession, *, recorte: Recorte) -> dict[Etapa, int]:
    """Quantos da coorte alcancaram cada etapa. `AGENDADO` nao esta aqui.

    A ausencia de `AGENDADO` no dicionario e deliberada e nao um
    esquecimento: nao existe tabela de agendamento, e quem poe o `None` na
    resposta e `montar_funil`, a partir de `SEM_FONTE`. Uma chave com zero
    aqui viraria zero la, que e exatamente o que a D1 recusa.
    """
    coorte = _coorte(recorte).subquery()

    novos = await _quantos(session, _coorte(recorte))

    # "Em conversa" e o lead que falou mais de uma vez: uma fala so e o
    # primeiro contato, que ja e a etapa Novo. Sem este piso, as duas etapas
    # dariam sempre o mesmo numero e a conversao entre elas seria 100% fixo.
    em_conversa = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key)
        .join(
            Message,
            (Message.channel == coorte.c.channel)
            & (Message.conversation_key == coorte.c.conversation_key),
        )
        .where(Message.direction == MessageDirection.INBOUND)
        .group_by(coorte.c.channel, coorte.c.conversation_key)
        .having(func.count(Message.id) > 1),
    )

    qualificados = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key).join(
            LeadQualification,
            (LeadQualification.channel == coorte.c.channel)
            & (LeadQualification.conversation_key == coorte.c.conversation_key)
            & LeadQualification.qualificado_em.is_not(None),
        ),
    )

    recomendados = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key).join(
            Recomendacao,
            (Recomendacao.channel == coorte.c.channel)
            & (Recomendacao.conversation_key == coorte.c.conversation_key),
        ),
    )

    aceitos = await _quantos(
        session,
        select(coorte.c.channel, coorte.c.conversation_key).join(
            Handoff,
            (Handoff.channel == coorte.c.channel)
            & (Handoff.conversation_key == coorte.c.conversation_key)
            & (Handoff.status == _ACEITO),
        ),
    )

    return {
        Etapa.NOVO: novos,
        Etapa.EM_CONVERSA: em_conversa,
        Etapa.QUALIFICADO: qualificados,
        Etapa.RECOMENDADO: recomendados,
        Etapa.HANDOFF_ACEITO: aceitos,
    }

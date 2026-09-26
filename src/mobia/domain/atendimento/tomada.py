"""O corretor toma e devolve a conversa, e o handoff anda junto. TEC-194.

**Existe para que as duas portas de entrada decidam a mesma coisa.** As rotas
antigas (`/conversas/assumir` e `/devolver`, TEC-179 e TEC-278) recebem o par
no corpo; as novas (`/leads/{leadId}/...`, TEC-194) recebem o apelido. Os dois
efeitos colaterais -- aceitar o handoff ao assumir (D6 da TEC-179) e conclui-lo
ao devolver (D2 da TEC-278) -- moravam dentro da rota antiga, e uma segunda
copia deles nas novas divergiria na primeira mudanca.

Sem commit: quem chama e dono da transacao, e o efeito sobre o handoff TEM de
entrar no mesmo commit do atendimento -- ver `assumir_conversa`.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.atendimento import repositorio as atendimento_repo
from mobia.domain.atendimento.repositorio import Atendimento
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import ACEITAVEIS, Status


async def assumir_conversa(
    session: AsyncSession, *, par: tuple[str, str], corretor_id: uuid.UUID
) -> Atendimento | None:
    """O agente cala, e o handoff pendente sai da fila. `None` se outro a tem.

    **O aceite do handoff entra na MESMA transacao** (D6 da TEC-179). Se o
    processo caisse entre os dois, um corretor apareceria com a conversa
    silenciada e a gerente continuaria sendo cobrada pelo SLA do handoff que
    ele acabou de pegar. Casar zero handoffs nao e erro: nem toda conversa
    assumida gerou um.
    """
    channel, conversation_key = par
    atendimento = await atendimento_repo.assumir(
        session, channel=channel, conversation_key=conversation_key, corretor_id=corretor_id
    )
    if atendimento is None:
        return None

    agora = datetime.now(UTC)
    await session.execute(
        update(Handoff)
        .where(
            Handoff.channel == channel,
            Handoff.conversation_key == conversation_key,
            Handoff.status.in_(ACEITAVEIS),
        )
        .values(status=Status.ACEITO.value, aceito_em=agora, atualizado_em=agora)
    )
    return atendimento


async def devolver_conversa(
    session: AsyncSession, *, par: tuple[str, str], corretor_id: uuid.UUID
) -> Atendimento | None:
    """O agente volta a falar, e o handoff aberto e concluido. `None` se nao estava assumida.

    O espelho da Emenda E-02 da RN-16.4, que fez `assumir` aceitar o handoff
    (D2 da TEC-278). O handoff existe para entregar o lead a um humano, e
    quando o humano devolve a conversa ao agente essa entrega acabou.

    **`!= CONCLUIDO` e nao uma lista de estados**, ao contrario de
    `ACEITAVEIS`. Duas razoes: o criterio aqui e literalmente "ainda esta
    aberto", e uma lista precisaria de manutencao toda vez que o enum
    crescesse; e este e exatamente o predicado do indice parcial
    `uq_handoffs_conversa_pendente` (ver `handoff/models.py`), que os dois
    precisam espelhar para nao divergirem em silencio.

    **Concluir o handoff NAO encerra a conversa** -- a RN-02.3 junta os dois e
    a emenda da TEC-278 os separa. Devolver e retomar o atendimento automatico.
    """
    channel, conversation_key = par
    atendimento = await atendimento_repo.devolver(
        session, channel=channel, conversation_key=conversation_key, corretor_id=corretor_id
    )
    if atendimento is None:
        return None

    agora = datetime.now(UTC)
    await session.execute(
        update(Handoff)
        .where(
            Handoff.channel == channel,
            Handoff.conversation_key == conversation_key,
            Handoff.status != Status.CONCLUIDO.value,
        )
        .values(status=Status.CONCLUIDO.value, atualizado_em=agora)
    )
    return atendimento

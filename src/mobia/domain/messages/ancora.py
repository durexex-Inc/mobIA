"""A ultima fala do lead: a ancora de todo envio automatico. TEC-172.

Este modulo existe porque a MESMA consulta estava escrita em tres lugares --
`agendamento/confirmacao.py::_avisar_lead` (TEC-170), a varredura dos
lembretes (TEC-171) e a dos convites de remarcacao (TEC-172) --, e uma quarta
copia era so questao de tempo. Nao e reuso por economia de linhas: os tres
sitios dependem da MESMA propriedade da linha, e uma copia que divergisse
(ordenar por outra coluna, esquecer o filtro de `role`) mandaria mensagem pelo
numero errado sem levantar nada.

**Por que a ultima fala DO LEAD, e nao a ultima mensagem da conversa.** Duas
razoes, e as duas importam:

- E ela que carrega, em `recipient_external_id`, o numero do canal que fala
  com este lead -- o "de" do envio. Uma fala do agente tem o par trocado.
- E ela que decide a janela de servico da Meta (`outbound/janela.py`): uma
  resposta do agente no meio nao move a janela, e usar a ultima mensagem
  qualquer faria o sistema achar que ainda cabe texto livre quando nao cabe.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message


@dataclass(frozen=True, slots=True)
class Ancora:
    """A linha que ancora um envio automatico.

    `de` e nulavel porque a coluna e: o canal web grava
    `REMETENTE_DO_WIDGET`, mas uma linha antiga pode nao ter nada. Quem envia
    trata o nulo como "nao ha de quem mandar" -- ver os chamadores.
    """

    message_id: uuid.UUID
    criada_em: datetime
    de: str | None


async def ancora_do_lead(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> Ancora | None:
    """A ultima fala do lead nesta conversa, ou `None` se ele nunca falou.

    Recebe a sessao e nao a abre: quem chama decide a fronteira, e os tres
    chamadores tem necessidades diferentes -- um ja esta dentro de uma sessao
    emprestada, os outros dois abrem a propria, curta.
    """
    linha = (
        await session.execute(
            select(Message.id, Message.created_at, Message.recipient_external_id)
            .where(
                Message.channel == channel,
                Message.conversation_key == conversation_key,
                Message.role == MessageRole.LEAD,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).first()
    if linha is None:
        return None
    return Ancora(message_id=linha[0], criada_em=linha[1], de=linha[2])


async def ancora_em_sessao_propria(
    session_factory: async_sessionmaker[AsyncSession], *, channel: str, conversation_key: str
) -> Ancora | None:
    """`ancora_do_lead` numa sessao curta, para quem esta fora de transacao.

    As varreduras leem a ancora entre duas chamadas de rede e nao podem manter
    transacao aberta durante elas -- o molde de `notificar`
    (`notificacao/envio.py`).
    """
    async with session_factory() as session:
        return await ancora_do_lead(session, channel=channel, conversation_key=conversation_key)

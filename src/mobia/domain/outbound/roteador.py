"""A escolha do adaptador de saida pelo canal da linha. TEC-124, D5.

Ate esta card `ctx["outbound"]` era uma instancia unica de `WhatsAppOutbound`,
e o canal nao entrava na decisao porque so havia um. Com o web, entra.

**A escolha se faz pela LINHA, e nao pelo chamador.** `OutboundPort.send`
recebe `message_id`, e e dele que sai o canal: um SELECT por chave primaria a
cada envio, em troca de nenhum dos sitios de chamada mudar -- inclusive os
seis dentro de `turno.py`, que tem mais de quatro mil linhas, e o
`_avisar_lead_da_janela_humana`, que fala com o lead de dentro da notificacao
de handoff. Um caminho de envio novo, escrito por quem nao leu esta card,
nasce roteado em vez de mandar tudo por WhatsApp.

**Nao herda de `GuardedOutbound`, de proposito.** As guardas de opt-out e de
atendimento humano e a reserva em `outbound_dispatches` moram no adaptador de
destino; repeti-las aqui reservaria duas vezes o mesmo envio, e a segunda
reserva colidiria com a primeira, fazendo todo envio parecer duplicata
suprimida.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.outbound.port import OutboundPort


class CanalSemPorta(Exception):
    """A linha nao existe, ou o canal dela nao tem adaptador montado.

    Levanta em vez de devolver False porque nao e indisponibilidade: e defeito
    de chamador ou de montagem do worker. Devolver False faria o turno fechar
    como "reentrega suprimida" -- PROCESSED, terminal -- e o lead nunca
    receberia nada, com um `info` no log mandando quem investiga para o lado
    errado. Propagada crua, cai no contrato que `OutboundPort` ja escreve para
    "qualquer outra excecao": a mensagem vira FAILED e alguem ve.
    """


class RoteadorPorCanal:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        portas: dict[str, OutboundPort],
    ) -> None:
        self._session_factory = session_factory
        self._portas = portas

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        async with self._session_factory() as session:
            canal = (
                await session.execute(select(Message.channel).where(Message.id == message_id))
            ).scalar_one_or_none()

        if canal is None:
            raise CanalSemPorta(f"nao ha linha em messages para {message_id}")

        porta = self._portas.get(canal)
        if porta is None:
            raise CanalSemPorta(f"canal {canal} sem adaptador de saida montado")

        return await porta.send(message_id, kind, payload)

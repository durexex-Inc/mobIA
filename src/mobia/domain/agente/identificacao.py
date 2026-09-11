"""Quem o agente diz que e, e quando ele diz (TEC-139).

**A fronteira de conversa nao existe neste sistema, e isto aqui e um
substituto declarado.** A emenda E-01 da TEC-148 sob a RN-05.7 registra que
`conversation_key` e o id externo do LEAD, que nenhuma tabela distingue
conversas, e que introduzir a entidade foi deferido. A TEC-130 e quem a cria.

Ate la, "conversa nova" e uma janela de silencio: nada deste lead nos ultimos
30 dias. O numero nao foi escolhido aqui -- e o mesmo que a TEC-130 nomeia no
proprio titulo. Usar outro criaria duas definicoes antes de a primeira
existir.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message

# Mesmo limiar da TEC-130. Quando aquela card chegar, este modulo passa a
# perguntar a entidade em vez de derivar, e esta constante sai.
DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30


async def e_conversa_nova(
    session_factory: async_sessionmaker[AsyncSession],
    message: Message,
    *,
    agora: datetime,
) -> bool:
    """Houve silencio longo o bastante antes desta mensagem?

    **`Message.id != message.id` e o que faz isto funcionar.** A ingestao
    grava a fala em `messages` antes de o worker rodar, entao a mensagem
    corrente ja esta no timeline quando esta funcao e chamada. Sem a exclusao,
    a consulta acha sempre a propria mensagem, o predicado e sempre falso e a
    identificacao nunca sai -- em silencio, com os testes de "nao repete"
    passando pelo motivo errado.

    Empate resolvido para o lado conservador: exatamente 30 dias ainda nao
    abre conversa nova. Nao repetir a identificacao incomoda menos que
    repeti-la, e o empate ficar ao acaso e o defeito que a TEC-229 documentou.

    `agora` entra por parametro e nao sai de `datetime.now()` aqui dentro,
    como `candidatos_a_followup` (`followup/repositorio.py`) e
    `tentativa_devida` (`followup/cadencia.py`) ja fazem: sem isso nenhum
    teste consegue posicionar o relogio no exato instante em que carimbou a
    mensagem anterior, e o teste do empate deixaria de exercitar um empate.
    """
    corte = agora - timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)
    async with session_factory() as session:
        anterior = await session.scalar(
            select(Message.id)
            .where(
                Message.channel == message.channel,
                Message.conversation_key == message.conversation_key,
                Message.id != message.id,
                Message.created_at >= corte,
            )
            .limit(1)
        )
    return anterior is None

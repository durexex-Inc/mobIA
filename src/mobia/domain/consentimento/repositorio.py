"""Grava e consulta o consentimento de uma pessoa. TEC-363.

`registrar` recebe `session_factory` e commita sozinho, como
`registrar_optout`: e ato completo em si, e quem chama -- o handler do
WebSocket -- nao tem transacao para compartilhar.

Nao passa `created_at`: a coluna tem `server_default=func.now()` e quem
carimba e o Postgres. Ver a nota em `Consentimento.created_at`.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.consentimento.models import Consentimento


async def registrar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    marketing: bool,
    texto_exibido: str,
    exibido_em: datetime | None,
) -> None:
    """Acrescenta o evento. Nunca atualiza nada.

    **`marketing=False` tambem vira linha**, e isso e deliberado: a recusa e
    evidencia de que o aviso foi exibido e de que a resposta foi nao. Sem ela,
    "nao perguntamos" e "perguntamos e ela recusou" ficam indistinguiveis. Ver
    a D3 do desenho.
    """
    async with session_factory() as session:
        session.add(
            Consentimento(
                id=uuid.uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                marketing=marketing,
                texto_exibido=texto_exibido,
                exibido_em=exibido_em,
            )
        )
        await session.commit()


async def tem_consentimento_de_marketing(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> bool:
    """O ULTIMO evento decide, e ausencia de evento e `False`.

    **Esta funcao existe para ninguem precisar interpretar linhas.** Um
    `SELECT` ingenuo na tabela traz recusas junto com aceites -- as duas sao
    linhas, pela D3 --, e quem contasse linhas concluiria que toda visitante
    que viu o aviso consentiu.

    Recebe `session` e nao `session_factory`, como as leituras do opt-out:
    roda dentro da sessao de quem pergunta.
    """
    ultimo = await session.scalar(
        select(Consentimento.marketing)
        .where(
            Consentimento.channel == channel,
            Consentimento.conversation_key == conversation_key,
        )
        .order_by(Consentimento.created_at.desc())
        .limit(1)
    )
    return bool(ultimo)

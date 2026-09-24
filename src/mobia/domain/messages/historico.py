"""O que a visitante do widget ve ao reabrir a pagina. TEC-124, D6.

**Le de `messages`, e nao de uma copia em Redis.** A durabilidade desta
conversa ja e do Postgres nos dois sentidos: a fala da visitante porque o
`IngestionService` commita antes de enfileirar, e a do agente porque o turno a
grava assim que o `WebOutbound` devolve -- e ele nunca levanta, entao a
gravacao nao depende de haver alguem ouvindo. A excecao e o worker cancelado
entre publicar e gravar; ver o docstring de `domain/outbound/web.py`. Uma
segunda representacao do mesmo fato seria mais uma coisa que pode divergir.

**A fala bloqueada pela moderacao fica de fora**, pelo mesmo criterio da
TEC-236 e da Emenda E-01 da RN-02.2: ela nao entra em contexto nem em resumo,
e esta tela seria o unico lugar do sistema em que ela reapareceria.

So `LEAD` e `AGENTE`: `CORRETOR` e `SISTEMA` existem para o handoff e para o
registro interno, e nao sao a conversa que a visitante teve.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, decrypt

_PAPEL_NA_TELA = {MessageRole.LEAD.value: "lead", MessageRole.AGENTE.value: "agente"}


@dataclass(frozen=True)
class FalaDoHistorico:
    papel: str
    texto: str
    em: datetime


async def historico_da_sessao(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    canal: str,
    sessao: str,
    limite: int,
) -> list[FalaDoHistorico]:
    """As ultimas `limite` falas, em ordem cronologica.

    A consulta desce por `created_at DESC` para o `LIMIT` cortar as MAIS
    ANTIGAS -- cortar as recentes devolveria o comeco de uma conversa longa e
    esconderia o que acabou de ser dito --, e a lista e revertida antes de
    sair, porque quem le a tela le de cima para baixo.

    Desempata por `id DESC` pela mesma razao que `falas_do_lead` em
    `followup/repositorio.py`: `_persist` grava o lote de um envelope num
    unico INSERT e `created_at` cai no `now()` do statement, constante para
    todas as linhas dele.
    """
    async with session_factory() as session:
        linhas = (
            (
                await session.execute(
                    select(Message)
                    .where(
                        Message.channel == canal,
                        Message.conversation_key == sessao,
                        Message.role.in_(tuple(_PAPEL_NA_TELA)),
                        Message.bloqueada_em.is_(None),
                    )
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(limite)
                )
            )
            .scalars()
            .all()
        )

    falas = []
    for linha in reversed(linhas):
        texto = decrypt(linha.text_body, aad_de(linha.id, "text_body"))
        if texto is None:
            # Linha sem corpo em claro -- midia, ou uma fala gravada sem
            # texto. Nao ha o que mostrar, e inventar um placeholder seria
            # afirmar na tela algo que a tabela nao diz.
            continue
        falas.append(
            FalaDoHistorico(papel=_PAPEL_NA_TELA[linha.role], texto=texto, em=linha.created_at)
        )
    return falas

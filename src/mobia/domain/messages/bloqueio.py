"""A marca de bloqueio na linha da mensagem (TEC-236).

Mora fora de `MessageRecorder` de proposito. O contrato daquele e explicito --
*"nenhum metodo propaga excecao. Quem chama esta no meio de responder ao
lead"* -- e ele esta certo para telemetria: perder uma linha de custo nao pode
derrubar a resposta.

**Aqui a escolha e a oposta, e a inversao e o ponto.** Se a marca falhar em
silencio, a fala bloqueada continua elegivel para o contexto do proximo turno e
para o resumo permanente. O desfecho seguro nao e "responda assim mesmo": e
falhar o turno, deixar a linha em FAILED e o sweeper retentar -- pagando de
novo a moderacao, que e barata perto de vazar a fala para dentro do prompt.

**A TEC-142 estende o mesmo argumento a auditoria.** `marcar_bloqueada` agora
grava a marca e o `ModerationEvent` no mesmo commit, e
`registrar_bloqueio_de_saida` grava so o evento (a saida nao tem linha propria
para carimbar). As duas propagam pelo motivo do paragrafo acima: sem a
transacao unica existiria o estado duravel "mensagem marcada como bloqueada,
recusa nao auditada" -- o estado em que o controle de risco da RN-B04 falha
em silencio.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.moderacao.models import ModerationEvent
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
    Veredito,
)

log = structlog.get_logger(__name__)


async def marcar_bloqueada(
    session_factory: async_sessionmaker[AsyncSession],
    message_id: UUID,
    *,
    channel: str,
    conversation_key: str,
    categoria: str,
) -> None:
    """Carimba `bloqueada_em` e grava a auditoria, num commit so.

    `UPDATE` direto e nao leitura-e-grava: a linha ja existe (a ingestao a
    gravou antes de o worker existir) e nao ha nada nela para ler antes de
    decidir. Uma segunda passada do sweeper sobre a mesma mensagem reescreve o
    carimbo com a hora nova, e isso e inofensivo -- o que importa e a coluna
    deixar de ser NULL, nao o instante exato.

    **As duas escritas sao uma so (TEC-142).** Duas transacoes deixariam
    existir o estado duravel "marcada, nao auditada": a marca protege o
    contexto do agente e nao diz nada sobre a auditoria, e esse e o estado em
    que o controle de risco da RN-B04 falha em silencio. Se qualquer uma
    falhar, nenhuma vale e a excecao sobe, pelo motivo no topo deste modulo.

    O evento da segunda passada do sweeper e uma linha a mais numa tabela
    append-only, e nao um problema: `moderation_events` registra recusas, e
    duas tentativas de recusar a mesma fala foram duas recusas.
    """
    async with session_factory() as session:
        await session.execute(
            update(Message).where(Message.id == message_id).values(bloqueada_em=datetime.now(UTC))
        )
        session.add(
            ModerationEvent(
                id=uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                direcao=Direcao.ENTRADA.value,
                categoria=categoria,
                message_id=message_id,
            )
        )
        await session.commit()


async def moderar_entrada_e_marcar(
    session_factory: async_sessionmaker[AsyncSession],
    moderador: ModeradorPort,
    *,
    message_id: UUID,
    channel: str,
    conversation_key: str,
    corpo: str,
) -> Veredito | None:
    """Modera a fala de entrada e, se reprovada, marca e audita num commit so.

    **Devolve `None` somente quando o provedor esta indisponivel.** Fail-open,
    a assimetria que `domain/moderacao/port.py` documenta: a fala do lead ja
    esta cifrada no banco, e negar atendimento a lead legitimo porque um
    servico caiu pune o inocente. `None` e nao `Veredito(bloqueado=False)`
    porque "nao deu para moderar" nao e "moderou e liberou", e quem chama
    precisa poder distinguir.

    **Nao entrega recusa nenhuma.** Quem chama decide se ha texto a mandar: o
    turno entrega a recusa de entrada, o caminho do agrupado e os cinco ramos
    que retornam cedo nao entregam nada (TEC-297, D2).

    Existe para ter um sitio so. Antes da TEC-297 esta sequencia estava
    escrita duas vezes -- no turno e em `_moderar_superada`, que a TEC-295
    criou --, e os cinco ramos que retornam antes da moderacao precisariam
    de uma terceira copia.
    """
    try:
        veredito = await moderador.moderar(corpo, direcao=Direcao.ENTRADA)
    except ModeracaoIndisponivel as exc:
        log.error(
            "moderacao.indisponivel",
            direcao=Direcao.ENTRADA.value,
            message_id=str(message_id),
            reason=str(exc),
        )
        return None

    if not veredito.bloqueado:
        return veredito

    # `error` e nao `warning`: e o nivel que o alerta observa, pelo mesmo
    # criterio de `outbound.recusado`. O texto julgado **nao** entra no log --
    # e fala do lead, coberta pela regra de PII.
    log.error(
        "moderacao.entrada_bloqueada",
        message_id=str(message_id),
        motivo=veredito.motivo,
        categoria=veredito.categoria,
    )
    # Se a marca falhar, a excecao sobe -- ver o topo deste modulo.
    #
    # `categoria or CATEGORIA_OUTRO`: `ModeradorPort` e um `Protocol`, um
    # adaptador futuro pode devolver `Veredito(bloqueado=True)` sem categoria,
    # e a coluna e `not null`. A alternativa seria esta chamada estourar por
    # causa de um campo de auditoria.
    await marcar_bloqueada(
        session_factory,
        message_id,
        channel=channel,
        conversation_key=conversation_key,
        categoria=veredito.categoria or CATEGORIA_OUTRO,
    )
    return veredito


async def registrar_bloqueio_de_saida(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message_id: UUID,
    channel: str,
    conversation_key: str,
    categoria: str,
) -> None:
    """A auditoria do que a empresa nao disse.

    Sem marca a carimbar: o texto barrado nunca chegou a `messages` e nao vai
    chegar -- persisti-lo criaria em claro exatamente o que a moderacao
    impediu de sair. O `message_id` e o da mensagem de ENTRADA que originou o
    turno, que e a ancora que existe.

    Propaga como a irma acima: um bloqueio de saida nao auditado e o caso em
    que o risco reputacional da RN-B04 aconteceu e nao ficou registrado.
    """
    async with session_factory() as session:
        session.add(
            ModerationEvent(
                id=uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                direcao=Direcao.SAIDA.value,
                categoria=categoria,
                message_id=message_id,
            )
        )
        await session.commit()

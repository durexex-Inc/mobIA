from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agente.classificador import ClassificadorPort
from mobia.domain.agente.repositorio import gravar_intencao
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.resumo import ContadorPort, ResumidorPort
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.outbound.port import EnvioRecusado, OutboundPort
from mobia.domain.outbound.whatsapp import EnvioForaDaJanela

log = structlog.get_logger(__name__)

KIND_DA_RESPOSTA = "reply"

# Conjunto fechado de proposito (Literal, nao str): um typo num dos dois
# lugares que compara contra esta string (process_message, os testes) vira
# erro de tipo no mypy em vez de um `if resultado == "processed"` que nunca
# bate e falha em silencio.
ResultadoDoTurno = Literal["respondido", "sem_resposta", "expirado", "reentrega_suprimida"]


async def executar_turno(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    classificador: ClassificadorPort,
    resumidor: ResumidorPort,
    contador: ContadorPort,
    outbound: OutboundPort,
) -> ResultadoDoTurno:
    """Um turno inteiro: contexto, classificacao, entrega, registro.

    A ordem no fim nao e arbitraria. Gravar a fala **depois** da entrega
    significa que uma queda no meio deixa o lead com a resposta e a linha do
    tempo sem ela, e o turno seguinte pode se repetir. Gravar antes deixaria
    uma fala fantasma no historico -- texto que o lead nunca viu, que entra no
    contexto do proximo turno e depois e dobrado permanentemente no resumo. O
    agente se repetir o lead perdoa; memoria inventada contamina tudo o que vem
    depois e ninguem percebe.
    """
    try:
        contexto = await montar_contexto(
            session_factory,
            channel=message.channel,
            conversation_key=message.conversation_key,
            resumidor=resumidor,
            contador=contador,
        )
    except ContextoIrreducivel as exc:
        # Uma unica mensagem que nao cabe no teto. Retentar nao encolhe nada.
        log.warning(
            "turno.contexto_irreducivel",
            channel=message.channel,
            reason=str(exc),
        )
        return "sem_resposta"

    gerada = await classificador.classificar(contexto)

    # Gravada antes da entrega de proposito: a classificacao e sobre a mensagem
    # do lead, que existe, e nao sobre a resposta que pode nao sair.
    async with session_factory() as session:
        await gravar_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            confianca=gerada.confianca,
            modelo=gerada.modelo,
        )
        await session.commit()

    try:
        entregue = await outbound.send(
            message.id,
            KIND_DA_RESPOSTA,
            {
                "para": message.conversation_key,
                "de": message.recipient_external_id,
                "texto": gerada.resposta,
            },
        )
    except EnvioForaDaJanela as exc:
        log.warning(
            "outbound.fora_da_janela",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "expirado"
    except EnvioRecusado as exc:
        # `error` e nao `warning`: e o alerta que observa isto. O estado da
        # linha vira PROCESSED porque FAILED faria o sweeper rodar o turno
        # inteiro de novo -- inclusive a chamada paga ao modelo -- para um
        # payload que nunca vai ser aceito.
        log.error(
            "outbound.recusado_permanente",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "sem_resposta"

    if not entregue:
        # `send()` devolve False sem levantar quando a guarda (Task 3) suprime
        # uma reentrega: ja existe uma reserva em outbound_dispatches para este
        # (message_id, kind), de uma tentativa anterior. `_deliver` nunca foi
        # chamado agora -- entao `gerada.resposta`, que veio de uma chamada
        # nova ao classificador, pode nao ser o texto que o lead recebeu (ou
        # nenhum texto pode ter saido ainda, se a tentativa anterior tambem
        # foi suprimida). Gravar aqui seria o mesmo risco de fala fantasma que
        # a ordem grava-depois-de-entregar existe para evitar, so que entrando
        # por esta porta em vez de uma excecao: exatamente por isso a checagem
        # do retorno, e nao so do "nao levantou", decide se grava.
        log.warning(
            "turno.reentrega_suprimida",
            channel=message.channel,
            message_id=str(message.id),
        )
        return "reentrega_suprimida"

    recorder = MessageRecorder(session_factory)
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=gerada.resposta,
        model=gerada.modelo,
        subagent="classificador",
        tokens_in=gerada.tokens_in,
        tokens_out=gerada.tokens_out,
        latency_ms=gerada.latency_ms,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    return "respondido"

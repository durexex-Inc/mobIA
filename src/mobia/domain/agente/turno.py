from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import MODELO_SEM_CHAMADA
from mobia.domain.agente.classificador import ClassificadorPort
from mobia.domain.agente.desambiguacao import deve_desambiguar
from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao, marcar_desambiguacao
from mobia.domain.agente.schemas import PerguntaDeDesambiguacao, RespostaDoAgente
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.repositorio import gravar_estado
from mobia.domain.context.resumo import ContadorPort, ResumidorPort
from mobia.domain.messages.bloqueio import marcar_bloqueada
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.moderacao.port import (
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
)
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRecusado, OutboundPort
from mobia.infra.crypto import aad_de, decrypt

log = structlog.get_logger(__name__)

KIND_DA_RESPOSTA = "reply"

SUBAGENTE_CLASSIFICADOR = "classificador"
SUBAGENTE_DESAMBIGUADOR = "desambiguador"
SUBAGENTE_MODERACAO = "moderacao"

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
    moderador: ModeradorPort,
) -> ResultadoDoTurno:
    """Um turno inteiro: contexto, classificacao, entrega, registro.

    A ordem no fim nao e arbitraria. Gravar a fala **depois** da entrega
    significa que uma queda no meio deixa o lead com a resposta e a linha do
    tempo sem ela, e o turno seguinte pode se repetir. Gravar antes deixaria
    uma fala fantasma no historico -- texto que o lead nunca viu, que entra no
    contexto do proximo turno e depois e dobrado permanentemente no resumo. O
    agente se repetir o lead perdoa; memoria inventada contamina tudo o que vem
    depois e ninguem percebe.

    Abaixo de `LIMIAR_DE_DESAMBIGUACAO` e com o episodio ainda limpo, a
    resposta da chamada 1 e descartada e o texto da segunda chamada
    (`classificador.desambiguar`) e entregue no lugar dela. O que o codigo
    garante e so esse desvio -- nada aqui garante que o texto devolvido seja
    uma pergunta aberta em vez de um menu numerado; a regra vive inteira no
    system prompt de `desambiguar` (ver a secao de lacunas do spec). O
    marcador que impede a repeticao so e gravado depois da entrega confirmada
    **e** so quando a pergunta foi de fato a coisa entregue -- marca-lo antes
    queimaria a unica chance de perguntar num 5xx da Meta, e marca-lo com a
    saida bloqueada queimaria a mesma chance por um texto neutro que nao
    pergunta nada.

    A marca de `perguntou` da TEC-257 segue a mesma regra, pelo mesmo motivo:
    e um fato sobre a nossa resposta, nao sobre a fala do lead, entao so entra
    depois da entrega confirmada e so quando `gerada` foi de fato o texto
    entregue -- nunca no caminho de desambiguacao (a chamada 1 foi descartada)
    nem com a saida bloqueada (o texto neutro nao pergunta nada). Diferente do
    marcador de desambiguacao, esta marca e permanente e a uniao no SQL nunca
    remove: marcar de mais aqui perde a chance de perguntar aquele campo para
    sempre e em silencio, nao so ate o proximo episodio.
    """
    # Antes de montar contexto de proposito: bloquear aqui economiza o turno
    # inteiro, inclusive as chamadas pagas ao modelo. E o texto do lead ainda
    # nao passou por lugar nenhum.
    corpo = decrypt(message.text_body, aad_de(message.id, "text_body"))
    if corpo:
        try:
            veredito = await moderador.moderar(corpo, direcao=Direcao.ENTRADA)
        except ModeracaoIndisponivel as exc:
            # Falha aberta, e assimetrica de proposito: a fala do lead ja esta
            # cifrada no banco (a ingestao a gravou antes de o worker existir),
            # e negar atendimento a lead legitimo porque um servico caiu pune o
            # inocente. Na saida a escolha e a oposta -- ver o bloco de saida.
            log.error(
                "moderacao.indisponivel",
                direcao=Direcao.ENTRADA.value,
                message_id=str(message.id),
                reason=str(exc),
            )
        else:
            if veredito.bloqueado:
                # `error` e nao `warning`: e o nivel que o alerta observa, pelo
                # mesmo criterio de `outbound.recusado`. O texto julgado **nao**
                # entra no log -- e fala do lead, coberta pela regra de PII.
                log.error(
                    "moderacao.entrada_bloqueada",
                    message_id=str(message.id),
                    motivo=veredito.motivo,
                )
                # A marca vem ANTES da entrega, e a ordem e o ponto (TEC-236).
                # `_entregar_texto_fixo` tem tres saidas que nao entregam nada
                # -- janela fechada, recusa permanente da Meta, reentrega
                # suprimida --, e duas delas fecham a linha em PROCESSED, que e
                # terminal. Marcar depois deixaria a fala bloqueada sem marca
                # exatamente nos casos em que ninguem mais volta nesta linha, e
                # ela entraria no contexto do proximo turno.
                #
                # Se a marca falhar, a excecao sobe: a linha vira FAILED e o
                # sweeper retenta. Custa uma moderacao paga a mais e nao vaza a
                # fala -- ver `messages/bloqueio.py`.
                await marcar_bloqueada(session_factory, message.id)
                return await _entregar_texto_fixo(
                    session_factory,
                    message=message,
                    outbound=outbound,
                    recorder_texto=TEXTO_DA_RECUSA_DE_ENTRADA,
                )

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
    #
    # A leitura vem **antes** da gravacao no mesmo bloco: `gravar_intencao`
    # limpa o marcador quando a confianca sustenta a classificacao, entao
    # depois dela nao da mais para saber se este episodio ja tinha perguntado.
    #
    # O estado de qualificacao entra no mesmo commit pela mesma razao, e ela
    # vale mais forte aqui: o que o lead disse que procura e fato sobre a fala
    # dele, nao sobre a nossa resposta. Saida bloqueada e envio fora da janela
    # nao descartam a extracao.
    #
    # `perguntou` fica de fora deste `gravar_estado`, de proposito: ao
    # contrario da intencao e da extracao, ele e um fato sobre a NOSSA
    # resposta, nao sobre a fala do lead -- e a resposta pode nao ser a coisa
    # entregue (desambiguacao descarta a chamada 1; moderacao troca o texto
    # pelo neutro). A marca dele so e gravada mais abaixo, depois da entrega
    # confirmada -- ver o comentario la.
    async with session_factory() as session:
        anterior = await ler_intencao(session, message.channel, message.conversation_key)
        await gravar_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            confianca=gerada.confianca,
            modelo=gerada.modelo,
        )
        await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
        )
        await session.commit()

    desambiguando = deve_desambiguar(
        gerada.confianca, anterior.desambiguado_em if anterior else None
    )
    # Anotado explicitamente: sem isso o mypy infere o tipo de `telemetria` a
    # partir so do primeiro ramo que ve (`PerguntaDeDesambiguacao`) e recusa a
    # atribuicao do segundo. Os dois tipos so precisam ter em comum os campos
    # de telemetria que `record_agent_message` le abaixo.
    texto: str
    telemetria: RespostaDoAgente | PerguntaDeDesambiguacao
    subagente: str
    if desambiguando:
        # A resposta da chamada 1 foi escrita assumindo um palpite que a
        # confianca nao sustenta. Ela e descartada -- paga e nao entregue.
        pergunta = await classificador.desambiguar(contexto)
        texto, telemetria, subagente = pergunta.texto, pergunta, SUBAGENTE_DESAMBIGUADOR
    else:
        texto, telemetria, subagente = gerada.resposta, gerada, SUBAGENTE_CLASSIFICADOR

    # Uma vez por turno: so um texto sai. No caminho ambiguo a resposta da
    # chamada 1 foi descartada e so a pergunta e entregue.
    #
    # Aqui **nao** ha falha aberta. Entregar texto nao moderado e o risco que
    # este subsistema existe para fechar, e o custo recai sobre a reputacao da
    # imobiliaria em publico -- diferente da entrada, onde o custo de falhar
    # aberto recai sobre o contexto do agente. A excecao propaga: a linha vira
    # FAILED com `attempts` e o sweeper retenta.
    try:
        veredito_da_saida = await moderador.moderar(texto, direcao=Direcao.SAIDA)
    except ModeracaoIndisponivel as exc:
        # Loga e **repropaga**. O log existe porque `process_message` vai
        # registrar so `message.failed` -- sem esta linha, "o turno falhou" e
        # "nao deu para moderar a saida" ficam indistinguiveis no log, e o
        # segundo e o unico dos dois que aponta para o moderador.
        log.error(
            "moderacao.indisponivel",
            direcao=Direcao.SAIDA.value,
            message_id=str(message.id),
            reason=str(exc),
        )
        raise
    saida_bloqueada = veredito_da_saida.bloqueado
    if saida_bloqueada:
        # O texto barrado **nao** entra no log: registra-lo criaria, no log,
        # exatamente aquilo que a moderacao impediu de sair.
        log.error(
            "moderacao.saida_bloqueada",
            message_id=str(message.id),
            motivo=veredito_da_saida.motivo,
            subagente=subagente,
        )
        texto = TEXTO_NEUTRO_DE_SAIDA

    try:
        entregue = await outbound.send(
            message.id,
            KIND_DA_RESPOSTA,
            {
                "para": message.conversation_key,
                "de": message.recipient_external_id,
                "texto": texto,
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
        # chamado agora -- entao `texto`, que veio de uma chamada nova ao
        # classificador (a de classificar ou a de desambiguar), pode nao ser o
        # texto que o lead recebeu (ou nenhum texto pode ter saido ainda, se a
        # tentativa anterior tambem foi suprimida). Gravar aqui seria o mesmo
        # risco de fala fantasma que a ordem grava-depois-de-entregar existe
        # para evitar, so que entrando por esta porta em vez de uma excecao:
        # exatamente por isso a checagem do retorno, e nao so do "nao
        # levantou", decide se grava.
        # `error`, pelo mesmo criterio do 4xx logo acima: a visibilidade vem
        # do nivel do log, nao do estado da linha, e o estado aqui e PROCESSED
        # -- terminal, o sweeper nunca reenfileira. Este desfecho e pelo menos
        # tao ruim quanto um 4xx: o lead pode nao ter recebido nada em
        # nenhuma das tentativas, e nao ha mais nenhuma. Se so o alerta de
        # `error` acorda alguem, isto tem de estar nele.
        log.error(
            "turno.reentrega_suprimida",
            channel=message.channel,
            message_id=str(message.id),
        )
        return "reentrega_suprimida"

    if desambiguando and not saida_bloqueada:
        # Depois da entrega confirmada, nunca antes: ver `marcar_desambiguacao`.
        # A ordem entre esta gravacao e a da fala do agente nao e carregada --
        # as duas sao pos-entrega, e a guarda do outbound suprime qualquer
        # reentrega se o turno cair entre elas.
        #
        # `not saida_bloqueada` pelo mesmo motivo que o marcador espera a
        # entrega: um bloqueio de saida e indistinguivel de um 5xx da Meta no
        # unico aspecto que o marcador afirma -- a pergunta nao chegou. O que
        # chegou foi `TEXTO_NEUTRO_DE_SAIDA`, que nao pergunta nada. Marcar
        # aqui gastaria a unica pergunta do episodio numa entrega que nunca a
        # fez, e o lead ficaria em INDEFINIDA sem ter sido perguntado. O
        # `log.info` vai junto pela mesma razao: fora daqui ele afirmaria um
        # "desambiguou" que nao aconteceu.
        async with session_factory() as session:
            await marcar_desambiguacao(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
            await session.commit()
        log.info(
            "turno.desambiguou",
            channel=message.channel,
            message_id=str(message.id),
        )

    if not desambiguando and not saida_bloqueada:
        # A marca de `perguntou` (TEC-257) e, ao contrario da intencao e da
        # extracao gravadas la em cima, um fato sobre a NOSSA resposta -- e
        # por isso nao pode entrar naquele commit pre-entrega. Ela so pode ser
        # gravada depois da entrega confirmada, e so quando o texto de
        # `gerada` foi de fato o que saiu, pela mesma razao que
        # `marcar_desambiguacao` espera a entrega (ver o bloco acima): no
        # caminho de desambiguacao a resposta da chamada 1 foi descartada --
        # paga e nao entregue -- e o lead recebeu a pergunta do desambiguador,
        # nao a de `gerada`; com a saida bloqueada o lead recebeu
        # `TEXTO_NEUTRO_DE_SAIDA`, que tambem nao pergunta nada. Marcar aqui
        # queimaria, para sempre e em silencio, a chance de perguntar aquele
        # campo de verdade -- a uniao no SQL nunca remove.
        #
        # Reusa `gravar_estado` em vez de uma funcao nova: regravar os mesmos
        # `intencao`/`extracao` de cima e idempotente (mais novo vence, mesmos
        # valores) e mantem a subtracao contra `campos` correta -- esta
        # segunda chamada so acrescenta `perguntou`, que so agora e seguro
        # gravar.
        async with session_factory() as session:
            await gravar_estado(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                intencao=gerada.intencao,
                extracao=gerada.extracao,
                perguntou=gerada.perguntou,
            )
            await session.commit()

    recorder = MessageRecorder(session_factory)
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=texto,
        model=telemetria.modelo,
        subagent=subagente,
        tokens_in=telemetria.tokens_in,
        tokens_out=telemetria.tokens_out,
        # As duas colunas existem em `message_telemetry` desde a TEC-126 e
        # ficaram SEMPRE NULL: `record_agent_message` as aceitava como
        # parametro e nenhum chamador passava valor. A TEC-251 ligou o cache e
        # pos os contadores no LOG, o que nao alcanca consulta nenhuma -- o
        # painel de custo da TEC-191 continuaria sem custo de cache. Este e o
        # criterio da TEC-231 que faltava.
        cache_write_tokens=telemetria.cache_write,
        cache_read_tokens=telemetria.cache_read,
        latency_ms=telemetria.latency_ms,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    return "respondido"


async def _entregar_texto_fixo(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    recorder_texto: str,
) -> ResultadoDoTurno:
    """Entrega um texto que nao veio do modelo, e grava o que entregou.

    Bloqueio nunca produz silencio: e a mesma escolha que a TEC-134 e a
    TEC-227 fizeram ao preferir a duplicata a perda, porque a duplicata e
    visivel e recuperavel e o silencio nao.
    """
    try:
        entregue = await outbound.send(
            message.id,
            KIND_DA_RESPOSTA,
            {
                "para": message.conversation_key,
                "de": message.recipient_external_id,
                "texto": recorder_texto,
            },
        )
    except EnvioForaDaJanela as exc:
        # Separada de `EnvioRecusado`, e com o mesmo nivel e o mesmo desfecho
        # que o caminho principal ja dava a ela: janela de 24h fechada nao e
        # recusa permanente, e o `Literal` de `ResultadoDoTurno` existe para
        # essa distincao nao se perder. Classificar a mesma excecao de dois
        # jeitos conforme o ramo do codigo faria o alerta de `error` acordar
        # alguem por uma janela que so fechou, e faria "expirado" sumir das
        # contagens exatamente nas mensagens bloqueadas.
        log.warning(
            "outbound.fora_da_janela",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "expirado"
    except EnvioRecusado as exc:
        log.error(
            "moderacao.texto_fixo_nao_entregue",
            message_id=str(message.id),
            reason=type(exc).__name__,
        )
        return "sem_resposta"

    if not entregue:
        # Mesmo raciocinio do bloco principal (ver `turno.reentrega_suprimida`
        # la embaixo): `send()` devolve False sem levantar quando a guarda ja
        # tem uma reserva para este (message_id, kind) de uma tentativa
        # anterior. Gravar aqui seria a mesma fala fantasma que aquele bloco
        # existe para evitar -- so que para o texto fixo do bloqueio.
        log.error(
            "turno.reentrega_suprimida",
            channel=message.channel,
            message_id=str(message.id),
        )
        return "reentrega_suprimida"

    recorder = MessageRecorder(session_factory)
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=recorder_texto,
        # Nao houve chamada ao modelo neste caminho: o texto e constante. Ver
        # `MODELO_SEM_CHAMADA` em `app/config.py` -- com "" a telemetria
        # abriria um `telemetry.unknown_model` por entrada bloqueada.
        model=MODELO_SEM_CHAMADA,
        subagent=SUBAGENTE_MODERACAO,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    return "respondido"

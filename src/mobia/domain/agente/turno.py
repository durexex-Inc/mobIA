from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import MODELO_SEM_CHAMADA
from mobia.domain.agente.classificador import ClassificadorPort
from mobia.domain.agente.desambiguacao import deve_desambiguar
from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao, marcar_desambiguacao
from mobia.domain.agente.schemas import PerguntaDeDesambiguacao, RespostaDoAgente
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.qualificacao import esta_qualificado
from mobia.domain.context.repositorio import gravar_estado, marcar_perguntados, registrar_recalculo
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

# Consumida no corpo deste modulo (a checagem de opt-out e a entrega da
# confirmacao), entao o import normal ja basta -- sem o "as X" que so existia
# para calar o ruff quando o nome era so reexportado, nunca usado aqui. Quem
# importava `from mobia.domain.agente.turno import KIND_DA_CONFIRMACAO_DE_OPTOUT`
# continua funcionando: o nome fica no namespace do modulo do mesmo jeito.
from mobia.domain.optout.deteccao import (
    KIND_DA_CONFIRMACAO_DE_OPTOUT,
    TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    pediu_optout,
)
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRecusado, OutboundPort
from mobia.infra.crypto import aad_de, decrypt

log = structlog.get_logger(__name__)

KIND_DA_RESPOSTA = "reply"

SUBAGENTE_CLASSIFICADOR = "classificador"
SUBAGENTE_DESAMBIGUADOR = "desambiguador"
SUBAGENTE_MODERACAO = "moderacao"
SUBAGENTE_OPTOUT = "optout"

# Conjunto fechado de proposito (Literal, nao str): um typo num dos dois
# lugares que compara contra esta string (process_message, os testes) vira
# erro de tipo no mypy em vez de um `if resultado == "processed"` que nunca
# bate e falha em silencio.
ResultadoDoTurno = Literal[
    "respondido",
    "sem_resposta",
    "expirado",
    "reentrega_suprimida",
    # A TEC-182 acrescentou os tres abaixo. Separados de proposito:
    # "opt_out" e o turno que ATENDEU o pedido (gravou e confirmou);
    # "silenciado" e o turno que nao fez nada porque o pedido ja valia;
    # "bloqueado_por_optout" e o turno que tentou responder normalmente e a
    # guarda da porta de saida (Task 4) barrou o envio porque outro turno da
    # MESMA conversa registrou o opt-out entre a checagem do topo deste turno
    # e este envio -- ver `_bloqueado_por_optout_concorrente`. Somar os tres
    # num valor so esconderia quantos opt-outs de fato acontecem, e faria o
    # terceiro caso soar como perda de dado quando a guarda so fez o trabalho
    # dela.
    "opt_out",
    "silenciado",
    "bloqueado_por_optout",
]


def _recusados_de(estado: LeadQualification | None) -> frozenset[str]:
    """A recusa da linha, na forma que `esta_qualificado` recebe.

    `or ()` porque `NULL` e `{}` na coluna significam coisas diferentes e a
    leitura trata as duas iguais -- ver o comentario da coluna. `frozenset` e
    nao `set` porque e o que a assinatura da TEC-147 pede.
    """
    if estado is None:
        return frozenset()
    return frozenset(estado.campos_recusados or ())


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

    # `bool(...)` por fora, e nao `bool(corpo) and ...`: so a forma curta-
    # circuitada estreita `corpo` de `str | None` para `str` dentro da chamada.
    pedido_de_optout = bool(corpo and pediu_optout(corpo))

    # Antes de tudo, inclusive da moderacao: quem ja pediu silencio nao paga
    # moderacao nem recebe resposta. Fica FORA do `if corpo:` de proposito: o
    # silencio e sobre o LEAD (o par channel/conversation_key), nao sobre a
    # mensagem ter texto. Uma imagem ou audio de quem ja pediu opt-out
    # tambem nao pode receber resposta, e dentro do `if corpo:` essa
    # mensagem sem texto escaparia do silencio. A guarda da porta de saida
    # (Task 4) ja impediria o envio de qualquer jeito; esta checagem existe
    # so para nao pagar o turno inteiro ate la.
    #
    # `not pedido_de_optout` e o fix de revisao (Important). Sem ele a
    # confirmacao se perdia PARA SEMPRE numa falha retentavel: turno 1 grava o
    # OPT_OUT, `_deliver` levanta `EnvioRetentavel` (5xx da Meta), a guarda
    # libera a reserva, a linha vira FAILED e o sweeper reenfileira -- e o
    # turno 2, sobre a MESMA mensagem, batia aqui, devolvia "silenciado" e
    # fechava em PROCESSED sem nunca reentregar. A D5 aceitou o lead ficar sem
    # confirmacao nas saidas TERMINAIS de `_entregar_texto_fixo` (janela
    # fechada, recusa permanente, reentrega suprimida); falha retentavel nao e
    # nenhuma delas, e o custo caiu entre duas tasks sem ninguem escolher.
    #
    # A idempotencia de quem JA recebeu a confirmacao continua vindo da
    # reserva em `outbound_dispatches`: se a confirmacao de fato saiu, a
    # reserva ainda existe, `send` devolve False e o desfecho e
    # `reentrega_suprimida`, com o alarme certo.
    #
    # O custo aceito: um lead que ja optou e digita "parar" de novo recebe a
    # confirmacao de novo -- mensagem nova para quem pediu silencio. E
    # defensavel porque e a excecao que a D1 ja nomeia (a confirmacao do
    # proprio pedido e o unico envio permitido depois do registro), e o
    # gatilho e sempre uma fala do lead pedindo exatamente isso.
    if not pedido_de_optout:
        async with session_factory() as sessao:
            if await esta_em_optout(
                sessao, channel=message.channel, conversation_key=message.conversation_key
            ):
                log.info(
                    "turno.silenciado_por_optout",
                    channel=message.channel,
                    message_id=str(message.id),
                )
                return "silenciado"

    if pedido_de_optout:
        # ANTES da moderacao de entrada, de proposito -- fix de revisao
        # (Critical): o bloco de moderacao logo abaixo tem `return` proprio.
        # Se este bloco rodasse depois dele, uma mensagem que e AO MESMO
        # TEMPO um pedido de opt-out e algo que a moderacao reprova (ex.:
        # "pare de mandar mensagem" seguido de um xingamento) nunca chegaria
        # aqui: a moderacao bloquearia e devolveria antes, o opt-out nunca
        # seria registrado, e continuariamos mandando mensagem (a recusa de
        # entrada) para quem pediu para sair -- a violacao que a D5 existe
        # para evitar, entrando por outra porta. Checar opt-out primeiro
        # tambem poupa a chamada paga de moderacao no caminho de opt-out, que
        # e o que o docstring de
        # `test_pedido_de_optout_grava_confirma_e_nao_paga_o_modelo` promete.
        #
        # Gravado ANTES da entrega, pelo precedente de `marcar_bloqueada`. Se
        # a entrega falhar depois, o lead fica em silencio sem confirmacao --
        # ruim e conforme. Na ordem inversa, um opt-out nao registrado nos
        # deixaria mandando mensagem, que e a violacao.
        await registrar_optout(
            session_factory,
            channel=message.channel,
            conversation_key=message.conversation_key,
            message_id=message.id,
        )
        # Nome distinto de `entregue` (o bool que `outbound.send` devolve mais
        # abaixo, no caminho principal): mypy infere um tipo unico por nome de
        # variavel na funcao inteira, e este aqui e o `ResultadoDoTurno` que
        # `_entregar_texto_fixo` devolve, nao o booleano cru.
        desfecho_da_confirmacao = await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
            kind=KIND_DA_CONFIRMACAO_DE_OPTOUT,
            subagent=SUBAGENTE_OPTOUT,
        )
        # `_entregar_texto_fixo` devolve "expirado", "sem_resposta",
        # "reentrega_suprimida" ou "bloqueado_por_optout" quando nao entrega.
        # Esses desfechos sao sobre o ENVIO da confirmacao, e o opt-out ja
        # esta gravado -- entao eles passam adiante como estao, e so o
        # caminho de sucesso vira "opt_out".
        return "opt_out" if desfecho_da_confirmacao == "respondido" else desfecho_da_confirmacao

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
                # `_entregar_texto_fixo` tem quatro saidas que nao entregam
                # nada -- janela fechada, recusa permanente da Meta, reentrega
                # suprimida, bloqueio por opt-out concorrente (TEC-182) --, e
                # a maioria delas fecha a linha em PROCESSED, que e terminal.
                # Marcar depois deixaria a fala bloqueada sem marca exatamente
                # nos casos em que ninguem mais volta nesta linha, e ela
                # entraria no contexto do proximo turno.
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
    #
    # `recusou` entra AQUI, ao contrario de `perguntou`: e fato sobre a fala
    # do lead, nao sobre a nossa resposta. Saida bloqueada e envio fora da
    # janela nao descartam uma recusa que o lead de fato disse.
    antes = esta_qualificado(contexto.estado, _recusados_de(contexto.estado))
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
        depois_do_estado = await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
            recusou=gerada.recusou,
        )
        # A trilha entra no mesmo commit que o estado, pela mesma razao que a
        # intencao e a extracao entram: ou os dois fatos existem, ou nenhum.
        #
        # Chamada em cada turno com estado, e nao so quando `gravar_estado`
        # devolveu linha: o engajamento depende da contagem de mensagens, que
        # sobe em todo turno, e as travessias de faixa dele podem cair num
        # turno sem campo nenhum. Amarrar o recalculo a escrita de campo
        # deixaria essas subidas fora da trilha.
        #
        # Nao recebe `depois_do_estado`: `registrar_recalculo` rele a linha sob
        # lock, e o motivo esta na docstring dele. `depois_do_estado` continua
        # valendo abaixo -- a releitura acontece na mesma sessao e na mesma
        # transacao, entao as duas referencias apontam para a mesma linha.
        await registrar_recalculo(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
        )
        await session.commit()

    # A borda, nao o estado: um lead ja qualificado que segue conversando nao
    # gera o evento de novo, senao a taxa de qualificacao da RN-17.1 contaria
    # conversas em vez de leads. `antes` sai de `contexto.estado`, que
    # `montar_contexto` ja leu para montar o prompt -- nenhuma consulta extra.
    # `esta_qualificado(None)` devolve False, entao o caso FORA_DE_ESCOPO (onde
    # `gravar_estado` devolve None) nao dispara nada.
    if not antes and esta_qualificado(depois_do_estado, _recusados_de(depois_do_estado)):
        log.info(
            "lead.qualificado",
            channel=message.channel,
            message_id=str(message.id),
        )

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
        if await _bloqueado_por_optout_concorrente(session_factory, message):
            # A guarda de `GuardedOutbound.send` (Task 4) barrou ESTE envio
            # porque outro turno da MESMA conversa registrou o opt-out entre
            # a checagem do topo deste turno (`esta_em_optout`, la em cima) e
            # este envio -- os dois turnos correram em paralelo sobre a mesma
            # conversa. A guarda funcionou exatamente como desenhada: nada
            # foi perdido, o lead so nao recebe porque pediu para nao
            # receber. Por isso este desfecho NAO pode se disfarcar de
            # "reentrega_suprimida" -- aquele nome e `error` porque e alarme
            # de DADO SUMIDO (ver o comentario logo abaixo), e aqui nao sumiu
            # nada. `info`, no nivel de uma checagem que funcionou como devia.
            log.info(
                "turno.bloqueado_por_optout_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_optout"

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
        # `marcar_perguntados`, e NAO `gravar_estado` de novo: regravar
        # `intencao`/`extracao` aqui e idempotente so contra si mesmo. Contra
        # a concorrencia real entre dois turnos da mesma conversa -- a razao
        # pela qual a uniao da marca foi para o SQL -- reescrever as colunas
        # de valor pos-entrega reabriria a corrida que a uniao fechou, so que
        # do lado errado: turno A grava extracao_A em t1, turno B grava
        # extracao_B em t2 > t1, e este commit pos-entrega de A aconteceria
        # em t3 > t2 e sobrescreveria a extracao mais nova de B com a mais
        # velha de A -- "mais novo vence" invertido, em silencio, para as
        # mesmas colunas que a marca foi desenhada para nao arriscar.
        # `marcar_perguntados` faz so o UPDATE da marca, ver o docstring la.
        async with session_factory() as session:
            await marcar_perguntados(
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


async def _bloqueado_por_optout_concorrente(
    session_factory: async_sessionmaker[AsyncSession], message: Message
) -> bool:
    """Distingue as duas causas de `outbound.send` devolver False sem levantar.

    `OutboundPort.send` documenta que quem le so o retorno NAO consegue
    separar uma reentrega genuinamente suprimida (reserva duplicada em
    `outbound_dispatches`) de um envio que a guarda de opt-out barrou -- ver
    o docstring de `OutboundPort` e `GuardedOutbound.send`. Reconsultar
    `esta_em_optout` aqui, depois do `send()`, e o unico jeito de escolher a
    historia certa para o log: se o lead esta em opt-out agora, a guarda e a
    explicacao mais provavel para o False, e as duas causas nao podem levar
    o mesmo nivel de log nem o mesmo `ResultadoDoTurno` -- uma e alarme de
    dado sumido, a outra e a guarda funcionando como desenhada.

    Best-effort de proposito: entre o `send()` e esta consulta o estado ainda
    pode mudar (uma reativacao, por exemplo). Isso so muda qual historia o
    log conta -- em nenhum dos dois casos ha texto reenviado ou dado perdido,
    entao um veredito ocasionalmente desatualizado aqui nao cria um risco
    novo de LGPD nem de duplicata.
    """
    async with session_factory() as sessao:
        return await esta_em_optout(
            sessao, channel=message.channel, conversation_key=message.conversation_key
        )


async def _entregar_texto_fixo(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    recorder_texto: str,
    kind: str = KIND_DA_RESPOSTA,
    subagent: str = SUBAGENTE_MODERACAO,
) -> ResultadoDoTurno:
    """Entrega um texto que nao veio do modelo, e grava o que entregou.

    Bloqueio nunca produz silencio: e a mesma escolha que a TEC-134 e a
    TEC-227 fizeram ao preferir a duplicata a perda, porque a duplicata e
    visivel e recuperavel e o silencio nao. `kind` tem default para preservar
    os chamadores existentes -- o texto de recusa de entrada usa o kind da
    resposta normal. A confirmacao de opt-out (TEC-182) passa o kind proprio,
    que e o unico que atravessa a guarda de opt-out da porta de saida depois
    do registro -- ver `GuardedOutbound.send`. `subagent` anda junto de
    `kind` pelo mesmo motivo: sem o parametro, toda entrega deste caminho --
    inclusive a confirmacao de opt-out, que nao e moderacao nenhuma -- gravava
    `message_telemetry.subagent = "moderacao"`, rotulando errado quem olhar a
    telemetria depois.
    """
    try:
        entregue = await outbound.send(
            message.id,
            kind,
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
        # `kind != KIND_DA_CONFIRMACAO_DE_OPTOUT` guarda a chamada seguinte,
        # de proposito -- fix de revisao (Important). Quando ESTE chamador e
        # a propria confirmacao de opt-out, o turno acabou de rodar
        # `registrar_optout` antes de chegar aqui: `esta_em_optout` so pode
        # devolver True, sempre, por construcao -- nao porque a guarda barrou
        # por opt-out desta vez, mas porque o opt-out que o PROPRIO turno
        # gravou ainda esta la. E a guarda pula a checagem de opt-out para
        # este kind especifico (ver `GuardedOutbound.send`), entao um `False`
        # aqui so pode vir de reserva duplicada de verdade. Chamar o helper
        # mesmo assim relataria "bloqueado_por_optout" em `info` e engoliria
        # o "reentrega_suprimida" em `error` -- o alarme de dado sumido que
        # importa exatamente aqui, na confirmacao que apaga o unico rastro
        # visivel do pedido do lead se ela nao chegar.
        if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT and await _bloqueado_por_optout_concorrente(
            session_factory, message
        ):
            # Mesmo raciocinio do bloco principal (ver
            # `turno.bloqueado_por_optout_concorrente` la em cima): a guarda
            # barrou este envio porque outro turno da mesma conversa
            # registrou o opt-out entre a checagem do topo e este envio. Nao
            # e "reentrega_suprimida" -- nada foi perdido.
            log.info(
                "turno.bloqueado_por_optout_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_optout"

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
        subagent=subagent,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    return "respondido"

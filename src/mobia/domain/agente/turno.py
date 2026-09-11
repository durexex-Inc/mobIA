import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import MODELO_SEM_CHAMADA
from mobia.domain.agente.apresentacao import legenda_de
from mobia.domain.agente.citacao import divergencias_de
from mobia.domain.agente.classificador import ClassificadorPort, LacoDeBuscaExcedido
from mobia.domain.agente.desambiguacao import deve_desambiguar
from mobia.domain.agente.ferramenta_de_busca import fichas_do_catalogo, porta_de_busca
from mobia.domain.agente.identificacao import (
    SEPARADOR_DA_IDENTIFICACAO,
    TEXTO_DA_IDENTIFICACAO,
    e_conversa_nova,
)
from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao, marcar_desambiguacao
from mobia.domain.agente.schemas import PerguntaDeDesambiguacao, RespostaDoAgente
from mobia.domain.context.gatilhos import gatilhos_de
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.qualificacao import esta_qualificado
from mobia.domain.context.repositorio import gravar_estado, marcar_perguntados, registrar_recalculo
from mobia.domain.context.resumo import ContadorPort, ResumidorPort
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.messages.bloqueio import marcar_bloqueada, registrar_bloqueio_de_saida
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
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
from mobia.domain.outbound.port import (
    EnvioForaDaJanela,
    EnvioRecusado,
    EnvioRetentavel,
    OutboundPort,
)
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.embeddings import embedar

log = structlog.get_logger(__name__)

KIND_DA_RESPOSTA = "reply"

# TEC-162. Kinds fixos POR POSICAO, e nao derivados do id do imovel: o
# UNIQUE (message_id, kind) de `outbound_dispatches` precisa de um valor que
# a retentativa reproduza. Um kind com o id dentro deixaria de colidir assim
# que a retentativa escolhesse outro imovel, e a idempotencia sumiria
# justamente no caso em que ela importa -- ver a D9 e a L1 do desenho.
KINDS_DAS_FICHAS = ("ficha_1", "ficha_2", "ficha_3")

# RN-10.2: maximo de 3 por turno, mesmo quando a busca devolveu 10.
MAX_IMOVEIS_POR_TURNO = len(KINDS_DAS_FICHAS)

# TEC-265, D4. O lead nunca fica em silencio porque o teto do laco funcionou.
TEXTO_DA_BUSCA_INCONCLUSIVA = (
    "Deixa eu confirmar algumas coisas com um corretor para nao te passar "
    "informacao errada. Ja te retorno com as opcoes."
)

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


def _faixa_declarada(estado: LeadQualification | None) -> tuple[int | None, int | None]:
    """O orcamento que o lead ja declarou, na forma que `divergencias_de` recebe.

    Existe para a guarda da TEC-161 nao bloquear o modelo ecoando o proprio
    lead: "entendi, ate R$ 600 mil" nao e imovel inventado. Linha ausente vira
    faixa vazia, que `_na_faixa` trata como ausencia de declaracao -- e nao
    como faixa aberta.
    """
    if estado is None:
        return (None, None)
    return (estado.faixa_preco_min_centavos, estado.faixa_preco_max_centavos)


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

    # Ao lado do opt-out de proposito: mesmo insumo (o texto decifrado), mesmo
    # ponto do fluxo, e nenhuma consulta. A fala bloqueada pela moderacao nunca
    # chega ao gancho -- `executar_turno` retorna por `_entregar_texto_fixo`
    # antes do bloco transacional --, entao um turno que o resto do produto
    # trata como nao-dito nao forca QUENTE, e isso sai de graca.
    #
    # `if corpo else ()` e nao `bool(corpo) and ...` porque a saida e uma
    # tupla, nao um bool: so a forma condicional estreita `corpo` de
    # `str | None` para `str` E preserva o tipo de retorno.
    gatilhos = gatilhos_de(corpo) if corpo else ()

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
                    categoria=veredito.categoria,
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
                #
                # `TEC-142`: a marca e a auditoria de ENTRADA saem no mesmo
                # commit (ver `marcar_bloqueada`). `categoria or CATEGORIA_OUTRO`
                # porque `ModeradorPort` e um `Protocol` -- um adaptador futuro
                # pode devolver `Veredito(bloqueado=True)` sem categoria, e a
                # coluna e `not null`. A alternativa seria o turno estourar por
                # causa de um campo de auditoria.
                await marcar_bloqueada(
                    session_factory,
                    message.id,
                    channel=message.channel,
                    conversation_key=message.conversation_key,
                    categoria=veredito.categoria or CATEGORIA_OUTRO,
                )
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

    try:
        gerada = await classificador.classificar(
            contexto,
            # A porta e montada aqui porque e aqui que existe `session_factory`.
            # O classificador recebe um callable pronto e nao sabe o que e uma
            # sessao -- D3 do desenho.
            #
            # `embedador=embedar` liga a busca do turno ao provedor de verdade
            # -- o mesmo `embedar` que `indexar_catalogo` usa para o catalogo.
            # Sem isto, `consulta_texto` do tool call seria aceito e nunca
            # mudaria um resultado: `_vetor_da_consulta` (busca.py) devolve
            # None sem embedador injetado, a similaridade fica 0 para todo
            # candidato, e a busca hibrida da TEC-158 nunca aconteceria dentro
            # de um turno -- so pela rota HTTP, que nao injeta embedador (ver
            # `api/routes/imoveis.py`). A degradacao por falha continua
            # coberta pelo mesmo `except Exception` de `_vetor_da_consulta`:
            # o embedador real pode falhar, e a busca segue pelo filtro
            # estruturado -- D9.
            porta=porta_de_busca(session_factory, embedador=embedar),
        )
    except LacoDeBuscaExcedido:
        # Nao propaga: `process_message` marcaria FAILED e o sweeper
        # reenfileiraria o mesmo turno, que pediria a ferramenta duas vezes de
        # novo -- gastando duas chamadas ao modelo por tentativa para chegar
        # ao mesmo lugar. O lead recebe texto conservador e o corretor entra.
        log.warning("turno.laco_de_busca_excedido", channel=message.channel)
        return await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=TEXTO_DA_BUSCA_INCONCLUSIVA,
            subagent=SUBAGENTE_CLASSIFICADOR,
        )

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
        recalculo = await registrar_recalculo(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            gatilhos=gatilhos,
        )
        await session.commit()

    # A borda, nao o estado: um lead ja qualificado que segue conversando nao
    # gera o evento de novo, senao a taxa de qualificacao da RN-17.1 contaria
    # conversas em vez de leads. `antes` sai de `contexto.estado`, que
    # `montar_contexto` ja leu para montar o prompt -- nenhuma consulta extra.
    # Um turno FORA_DE_ESCOPO que so grava recusa (o caminho do Achado 1 em
    # `gravar_estado`) pode devolver a linha em vez de `None` -- mas isso
    # nunca dispara o evento: aquele caminho so acrescenta nomes a
    # `campos_recusados` (uniao, sem `array_remove`, porque nao ha campo
    # respondido neste turno) e nunca toca as colunas de valor, entao a
    # qualificacao de `depois_do_estado` so pode piorar ou empatar com a de
    # `contexto.estado` -- nunca melhorar. Como o evento exige `not antes and
    # esta_qualificado(depois...)`, ele so dispararia se `depois` fosse MAIS
    # qualificado que `antes`, o que este caminho nunca produz.
    #
    # TEC-148 quebrou a premissa que sustentava "uma vez qualificado, sempre
    # qualificado" por tras do primeiro paragrafo acima: antes desta card
    # nenhum valor gravado era apagado, entao a borda so era cruzada uma vez
    # por lead, para sempre. Agora uma recusa pode derrubar `esta_qualificado`
    # (o campo deixa de contar enquanto recusado) e uma resposta seguinte pode
    # devolve-lo (o `array_remove` de `gravar_estado` tira a recusa quando o
    # valor chega) -- turno A completa os quatro obrigatorios e emite; turno B
    # recusa um deles; turno C comeca com `antes` False (o estado que
    # `contexto.estado` leu ja carrega a recusa do turno B), o lead responde e
    # a borda e cruzada de novo, para o MESMO lead. O evento reemite. Isto NAO
    # esta corrigido aqui: tornar a emissao idempotente por lead exige estado
    # persistido de "ja emiti uma vez", que e decisao de quem e dono da
    # metrica RN-17.1, nao desta card -- so fica declarado, para quem ler essa
    # metrica saber que uma travessia de ida-e-volta agora conta duas vezes.
    if not antes and esta_qualificado(depois_do_estado, _recusados_de(depois_do_estado)):
        log.info(
            "lead.qualificado",
            channel=message.channel,
            message_id=str(message.id),
        )

    # A borda, e nao o estado: um lead que continua QUENTE nao reemite, senao
    # a RN-06.5 viraria um ping por mensagem. `recalculo.anterior` sai da
    # coluna `temperatura`, e nao da trilha de auditoria -- a trilha grava so
    # quando o score muda e tem retencao de 12 meses (RNF-18), entao um lead
    # cujo ultimo registro fosse expurgado voltaria a parecer nunca-calculado
    # e reemitiria como se tivesse acabado de esquentar. (`anterior`, sem
    # prefixo, e OUTRA variavel nesta funcao -- a linha de intencao que
    # `ler_intencao` devolveu, la em cima; nao confundir as duas.)
    #
    # `recalculo.anterior is None` (coluna nula) com QUENTE emite: um lead
    # cujo primeiro recalculo ja cai em QUENTE de fato esquentou, e tratar
    # NULL como "ja era quente" perderia a unica travessia que ele tem.
    #
    # `recalculo is not None` nao e so defensivo: e "nao havia
    # `lead_qualification` para pontuar" (ver a docstring de
    # `registrar_recalculo`). Uma linha so nasce quando `campos_a_gravar`
    # devolve algo -- `gravar_estado` documenta o caminho "Deliberadamente NAO
    # cria linha" --, entao um lead que AINDA NAO TEM linha (primeiro turno, ou
    # so turnos FORA_DE_ESCOPO/INDEFINIDA sem extracao ate agora) e que peca
    # visita justo num turno assim continua sem linha: `registrar_recalculo`
    # nao acha o que pontuar, devolve `None`, e o pedido se perde em silencio,
    # sem forcar e sem emitir. Um lead que JA TEM linha (de um turno COMPRA
    # anterior, por exemplo) nao sofre disto -- `registrar_recalculo` acha a
    # linha existente e aplica o gatilho normalmente, mesmo num turno
    # FORA_DE_ESCOPO. Nao corrigido aqui -- lacuna declarada no desenho.
    #
    # Depois do commit, como `lead.qualificado`: logar uma transicao que o
    # rollback desfez e mentir para quem le o log.
    #
    # **Isto NAO e a notificacao da RN-06.5, e a lacuna esta declarada no
    # desenho.** A entrega depende do handoff (E7), que nao existe -- nao ha
    # epico, nao ha consumidor, e o conteudo da mensagem esta fora do escopo
    # da card. Os 60 segundos da regra sao triviais porque o evento e sincrono
    # no turno; o que nao existe e alguem do outro lado.
    #
    # O texto do lead nao entra: `motivos` e vocabulario nosso, nao fala dele.
    # Mesma regra de PII que `moderacao.entrada_bloqueada` respeita.
    #
    # Este evento herda o defeito de reemissao de `lead.qualificado`, pela
    # mesma causa: o total nao e monotono desde a TEC-148, entao a borda por
    # faixa e atravessavel nos dois sentidos para o MESMO lead. O forcado nao
    # volta; o derivado volta. Declarado, nao corrigido -- corrigir exige
    # estado persistido de "ja emiti uma vez".
    if (
        recalculo is not None
        and recalculo.anterior is not Temperatura.QUENTE
        and recalculo.temperatura is Temperatura.QUENTE
    ):
        log.info(
            "lead.esquentou",
            channel=message.channel,
            message_id=str(message.id),
            motivos=list(recalculo.gatilhos),
            total=recalculo.total,
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

    # Uma vez por turno: so um texto vem do modelo. No caminho ambiguo a
    # resposta da chamada 1 foi descartada e so a pergunta e entregue. Na
    # apresentacao da TEC-162 saem tres mensagens, mas o unico texto gerado
    # continua sendo esta prosa -- a ficha e dado do banco montado por codigo,
    # e moderar dado nosso seria gastar chamada sobre texto que nao inventamos.
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
            categoria=veredito_da_saida.categoria,
        )
        # Antes da entrega, pelo mesmo precedente de `marcar_bloqueada`: se a
        # auditoria falhar, o turno falha e o sweeper retenta. Um bloqueio de
        # saida entregue e nao auditado e o caso em que o risco da RN-B04
        # aconteceu sem deixar registro.
        await registrar_bloqueio_de_saida(
            session_factory,
            message_id=message.id,
            channel=message.channel,
            conversation_key=message.conversation_key,
            categoria=veredito_da_saida.categoria or CATEGORIA_OUTRO,
        )
        texto = TEXTO_NEUTRO_DE_SAIDA

    # TEC-162, D4. Candidatos sem pergunta e turno de apresentacao. As tres
    # condicoes sao a mesma regra: pergunta adia as fichas. `desambiguando`
    # entra porque `gerada.perguntou` fala da chamada 1, que foi DESCARTADA
    # nesse caminho -- o texto entregue e a pergunta do desambiguador.
    apresentando = bool(gerada.candidatos) and not gerada.perguntou and not desambiguando

    # TEC-161. A ultima coisa que acontece antes de a entrega comecar, e a
    # ordem e a invariante da card: `_apresentar` grava reserva em
    # `outbound_dispatches`, e bloquear depois dela deixaria linha gravada e
    # mensagem entregue.
    #
    # **Nao regenera**, contra a letra da RN-09.4 e com emenda no SRS. Tres
    # razoes, na ordem de peso: a moderacao de saida logo acima ja barra sem
    # regerar e duas politicas para o mesmo problema no mesmo turno seriam uma
    # a mais; uma segunda chamada reexecuta o laco de tool use da TEC-265, ou
    # seja uma busca nova, dentro de um `job_timeout` que o pior caso ja
    # estoura; e depois da TEC-162 descartar a prosa ainda entrega ate tres
    # fichas corretas, porque nenhum campo delas passou pelo modelo.
    # `depois_do_estado or contexto.estado`: `gravar_estado` devolve `None` em
    # todo turno que nao extraiu campo novo e nao registrou recusa (ver o
    # "Deliberadamente NAO cria linha" no docstring dela), o que inclui o
    # turno mais comum de todos -- o lead nao disse nada novo sobre orcamento,
    # so continuou a conversa. Alimentar so `depois_do_estado` cegaria a
    # excecao da faixa exatamente nesses turnos, mesmo com a linha
    # `lead_qualification` ja existindo e ja carregando a faixa: o modelo
    # ecoando "beleza, vou procurar ate 600 mil" -- que o D5 do desenho existe
    # para permitir, e que `montar_contexto` ate instrui o modelo a fazer --
    # seria bloqueado como se tivesse inventado o numero. `contexto.estado` e
    # o mesmo valor que `antes`, la em cima, ja leu para a borda de
    # qualificacao: a linha de antes do turno, que continua valendo quando
    # este turno nao gravou nada novo.
    divergencias = divergencias_de(
        texto,
        candidatos=gerada.candidatos,
        faixa=_faixa_declarada(depois_do_estado or contexto.estado),
    )
    citacao_bloqueada = bool(divergencias)
    if citacao_bloqueada:
        # A prosa barrada **nao** entra no log, pela mesma razao que o texto
        # barrado pela moderacao nao entra: registra-la criaria no log
        # exatamente aquilo que a guarda impediu de sair. Os valores
        # divergentes entram -- sao o que o modelo inventou, e sao o unico
        # dado que torna a linha investigavel.
        log.error(
            "citacao.bloqueada",
            channel=message.channel,
            message_id=str(message.id),
            tipos=[d.tipo for d in divergencias],
            citados=[d.citado for d in divergencias],
            candidatos=len(gerada.candidatos),
            apresentando=apresentando,
        )
        # Apresentando, a prosa vira prefixo vazio e `legenda_de` a omite: o
        # lead recebe a ficha do banco, que e o conteudo que a RN-10.1 exige.
        # Sem ficha para entregar, a prosa era a mensagem inteira, e o
        # substituto e o mesmo texto que o `LacoDeBuscaExcedido` ja usa --
        # ele E a proposta de verificacao com o corretor que a card pede.
        texto = "" if apresentando else TEXTO_DA_BUSCA_INCONCLUSIVA

    # Depois da moderacao de saida, de proposito: o texto e constante deste
    # repositorio e nao saida de modelo -- moderar dado nosso seria gastar
    # chamada sobre texto que nao inventamos, o mesmo argumento que a TEC-162
    # escreveu para as fichas.
    #
    # Este ponto fica DEPOIS das duas reatribuicoes de `texto` acima, e por
    # isso cobre quatro trilhas, nao uma: a resposta normal, o
    # TEXTO_NEUTRO_DE_SAIDA da moderacao de saida bloqueada, o
    # TEXTO_DA_BUSCA_INCONCLUSIVA da citacao bloqueada da TEC-161 e -- via
    # `apresentando` abaixo -- o caminho excluido de proposito, tratado na
    # Task 5.
    #
    # `apresentando` fica de FORA aqui: naquele caminho `texto` vira prefixo de
    # legenda, e `legenda_de` corta o prefixo antes da ficha (D14 da TEC-162).
    # A identificacao seria descartada em silencio. A Task 5 trata dele.
    identificar = not apresentando and await e_conversa_nova(
        session_factory, message, agora=datetime.now(UTC)
    )
    if identificar:
        texto = f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{texto}"

    try:
        if apresentando:
            # `prosa=texto` le o valor ANTES da atribuicao: a chamada e
            # avaliada primeiro, e o `texto` que sai sao as legendas
            # concatenadas (D16).
            texto, quantas, suprimidas = await _apresentar(
                session_factory,
                message=message,
                outbound=outbound,
                candidatos=gerada.candidatos,
                prosa=texto,
            )
            entregue = quantas > 0
            # Nenhuma ficha entrou e TODAS foram suprimidas pela reserva: e o
            # mesmo caso do `not entregue` do caminho de texto -- reentrega de
            # uma tentativa anterior --, e o desfecho tem de ser o mesmo.
            if not entregue and suprimidas == 0:
                # Duas rotas chegam aqui, e as duas ja logaram em
                # `_apresentar`: ou todas as fichas foram recusadas
                # permanentemente (um `apresentacao.ficha_recusada` por
                # ficha), ou nenhuma ficha existiu -- `imoveis_por_ids`
                # derrubou todos os ids e o loop nunca rodou
                # (`apresentacao.fichas_sumiram_do_catalogo`). A segunda e a
                # que engana: sem aquele log ela seria um turno inteiramente
                # mudo, sem uma linha para quem opera.
                return "sem_resposta"
        else:
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
        # classificador (a de classificar ou a de desambiguar) ou, no caminho
        # de apresentacao da TEC-162, das legendas que ESTA tentativa montou,
        # pode nao ser o texto que o lead recebeu (ou nenhum texto pode ter
        # saido ainda, se a tentativa anterior tambem foi suprimida). Na
        # apresentacao o `texto` chega aqui vazio, porque nenhuma ficha
        # entrou. Gravar aqui seria o mesmo
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

    if desambiguando and not saida_bloqueada and not citacao_bloqueada:
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
        #
        # `not citacao_bloqueada` (TEC-161) pela mesma razao, terceiro caso: a
        # guarda de citacao substituiu o texto ANTES deste ponto, e no caminho
        # de desambiguacao esse texto era a pergunta do desambiguador. O que
        # chegou ao lead foi `TEXTO_DA_BUSCA_INCONCLUSIVA` (ou a ficha pura),
        # nao a pergunta -- marcar aqui seria o mesmo dano que `saida_bloqueada`
        # evita, so que pela guarda nova em vez da moderacao.
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

    if not desambiguando and not saida_bloqueada and not citacao_bloqueada:
        # A marca de `perguntou` (TEC-257) e, ao contrario da intencao e da
        # extracao gravadas la em cima, um fato sobre a NOSSA resposta -- e
        # por isso nao pode entrar naquele commit pre-entrega. Ela so pode ser
        # gravada depois da entrega confirmada, e so quando o texto de
        # `gerada` foi de fato o que saiu, pela mesma razao que
        # `marcar_desambiguacao` espera a entrega (ver o bloco acima): no
        # caminho de desambiguacao a resposta da chamada 1 foi descartada --
        # paga e nao entregue -- e o lead recebeu a pergunta do desambiguador,
        # nao a de `gerada`; com a saida bloqueada o lead recebeu
        # `TEXTO_NEUTRO_DE_SAIDA`, que tambem nao pergunta nada; e com a
        # citacao bloqueada (TEC-161) o lead recebeu `TEXTO_DA_BUSCA_INCONCLUSIVA`
        # ou a ficha pura -- tambem nao a pergunta de `gerada`. Marcar aqui
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
    """Entrega um texto que nao veio do modelo, grava o que entregou e decide
    se prefixa a identificacao do assistente.

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
    # A identificacao entra AQUI e nao em cada chamador: este e o funil das
    # tres trilhas que passam por `_entregar_texto_fixo` -- recusa da
    # moderacao de entrada, confirmacao de opt-out e laco de busca excedido.
    # (O texto neutro da moderacao de saida e a busca inconclusiva da citacao
    # bloqueada nao chamam esta funcao -- reatribuem `texto` e caem no bloco
    # de entrega compartilhado de `executar_turno`, que tem o ponto de
    # insercao proprio da Task 4.) Espalhada pelos chamadores, a proxima
    # trilha que surgisse sairia sem ela, e em silencio.
    if await e_conversa_nova(session_factory, message, agora=datetime.now(UTC)):
        recorder_texto = f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{recorder_texto}"

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


async def _apresentar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    candidatos: list[dict[str, Any]],
    prosa: str,
) -> tuple[str, int, int]:
    """Entrega ate 3 fichas e devolve (texto para gravar, entregues, suprimidas).

    O texto devolvido sao as legendas concatenadas -- o que o lead recebeu, e
    nao a prosa sozinha. Gravar so a prosa faria o turno seguinte reapresentar
    os mesmos imoveis por nao saber que ja os mostrou (D16).

    **Recusa permanente numa ficha nao interrompe as outras**, e a divergencia
    do caminho de texto unico e deliberada: a recusa provavel aqui e a Meta
    rejeitando a URL da midia, e uma foto ruim nao pode apagar dois imoveis
    bons (D10). `EnvioForaDaJanela` propaga, porque nesse caso a apresentacao
    inteira e impossivel e o desfecho e o mesmo de hoje.

    **Custo conhecido, e nao acidente: entrega parcial seguida de falha
    retentavel perde o registro do que ja saiu.** `EnvioRetentavel` e
    capturado logo abaixo, mas so para logar `entregues` e repropagar sem
    mudar nada -- o desfecho continua passando por cima de
    `record_agent_message`. Se a ficha 1 entregou e a 2 tomou um 5xx, a
    reserva da 2 e liberada, a linha vira FAILED, o sweeper roda o turno
    inteiro de novo, a posicao 1 e suprimida pela reserva que sobreviveu -- e
    a legenda que o lead viu nunca e gravada na linha do tempo, por nenhuma
    das duas tentativas. E exatamente o dano que a D16 existe para evitar,
    entrando pela porta da falha parcial; a consequencia pratica e o turno
    seguinte poder reapresentar aqueles imoveis. `EnvioForaDaJanela` depois de
    uma ficha ter entrado abre o mesmo buraco. O log torna o caso visivel para
    quem opera; nao torna o dado recuperavel -- a lacuna L1 do desenho registra
    o custo por extenso, e a correcao de verdade e a mesma citada abaixo.

    Gravar as parciais antes de deixar a excecao sair mudaria o que um turno
    FAILED escreve na linha do tempo, no caminho de entrega que TODA conversa
    usa, e nenhum teste deste repo consegue reproduzir um 5xx no meio da
    apresentacao. A correcao de verdade e persistir o conjunto escolhido --
    a `Recomendacao` da TEC-163. Ate la, isto e custo herdado e nao surpresa.
    """
    escolhidos = candidatos[:MAX_IMOVEIS_POR_TURNO]
    ids = [uuid.UUID(c["imovel_id"]) for c in escolhidos]
    precos = {uuid.UUID(c["imovel_id"]): int(c["preco_centavos"]) for c in escolhidos}
    fichas = await fichas_do_catalogo(session_factory, ids=ids, precos=precos)

    if len(fichas) < len(escolhidos):
        # `imoveis_por_ids` derruba id sem linha, e a D6 chama isso de caminho
        # normal: o candidato veio do indice vetorial e o imovel pode ter saido
        # do catalogo entre a busca e agora. O que NAO e normal e isso passar
        # calado -- quando nenhuma ficha sobra, o loop abaixo nao roda, nenhum
        # `ficha_recusada` sai, e o turno inteiro vira silencio com a prosa ja
        # moderada jogada fora. Sem esta linha ninguem que opera consegue ver
        # isso acontecer.
        #
        # `error` quando sobrou ZERO, porque ai o lead nao recebe nada e nao ha
        # segunda tentativa; `warning` quando sobrou alguma, porque o lead
        # ainda recebe o que restou.
        #
        # `imovel_ids_faltantes` e fix de revisao (Minor): `pedidas` e
        # `encontradas` sao contagem, e quem opera precisa saber QUAL imovel
        # sumiu, nao so quantos. O id nao aparece em nenhuma outra linha deste
        # arquivo -- sem isto ele e irrecuperavel. `Ficha.id` (fix wave, mesma
        # entrega) e o que torna a diferenca calculavel aqui.
        encontrados = {ficha.id for ficha in fichas}
        faltantes = [i for i in ids if i not in encontrados]
        registrar = log.error if not fichas else log.warning
        registrar(
            "apresentacao.fichas_sumiram_do_catalogo",
            channel=message.channel,
            message_id=str(message.id),
            pedidas=len(escolhidos),
            encontradas=len(fichas),
            imovel_ids_faltantes=[str(i) for i in faltantes],
        )

    legendas: list[str] = []
    entregues = suprimidas = 0
    for posicao, ficha in enumerate(fichas):
        # So a primeira leva a prosa (D5); as outras sao ficha pura.
        legenda = legenda_de(ficha, prefixo=prosa if posicao == 0 else None)
        payload: dict[str, Any] = {
            "para": message.conversation_key,
            "de": message.recipient_external_id,
        }
        if ficha.foto is None:
            # D13: sem foto, cai no caminho de texto que ja existe em vez de
            # ganhar um ramo proprio.
            payload["texto"] = legenda
        else:
            payload["tipo"] = "imagem"
            payload["link"] = ficha.foto
            payload["legenda"] = legenda

        try:
            entrou = await outbound.send(message.id, KINDS_DAS_FICHAS[posicao], payload)
        except EnvioForaDaJanela:
            # Repropaga, e esta clausula tem de vir ANTES da de baixo:
            # `EnvioForaDaJanela` HERDA de `EnvioRecusado` (port.py), entao um
            # `except EnvioRecusado` sozinho engoliria a janela de 24h
            # fechada: o turno devolveria "sem_resposta" (se todas as tres
            # batessem na janela) ou "respondido" com as fichas restantes (se
            # a janela fechasse no meio) em vez de "expirado", e o alerta que
            # observa janela fechada ficaria cego -- alem de o desfecho passar
            # a mentir sobre por que o lead nao recebeu. Janela fechada torna
            # a apresentacao inteira impossivel; nao e uma ficha ruim entre
            # tres.
            raise
        except EnvioRetentavel:
            # Fix de revisao (aceito do revisor). `EnvioRetentavel` nao herda
            # de `EnvioRecusado` nem de `EnvioForaDaJanela` (port.py) -- as
            # tres sao ramos distintos, entao esta clausula nao disputa MRO
            # com as duas de cima e a ordem entre elas nao muda qual excecao
            # cada uma pega. Propaga sem alterar o desfecho -- FAILED e o
            # sweeper reenfileira, exatamente como sem esta clausula --, e o
            # unico acrescimo e este log: sem ele, uma entrega PARCIAL (uma ou
            # duas fichas ja saidas quando o 5xx bateu nesta) fica invisivel
            # para quem opera ate a proxima tentativa reaparecer no mesmo
            # lugar. `entregues` conta so as que JA passaram por
            # `entregues += 1` abaixo -- a que estourou agora nao entra.
            log.error(
                "apresentacao.entrega_parcial_antes_de_falha_retentavel",
                channel=message.channel,
                message_id=str(message.id),
                kind=KINDS_DAS_FICHAS[posicao],
                entregues=entregues,
            )
            raise
        except EnvioRecusado as exc:
            # `error` pelo mesmo criterio do caminho de texto: o estado da
            # linha sera terminal e a visibilidade vem do nivel do log.
            log.error(
                "apresentacao.ficha_recusada",
                channel=message.channel,
                message_id=str(message.id),
                kind=KINDS_DAS_FICHAS[posicao],
                reason=str(exc),
            )
            continue

        if not entrou:
            suprimidas += 1
            continue

        entregues += 1
        legendas.append(legenda)

    return "\n\n".join(legendas), entregues, suprimidas

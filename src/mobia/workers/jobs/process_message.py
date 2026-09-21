import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

import structlog
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.agente.repositorio import ler_apresentacao_da_mensagem
from mobia.domain.agente.turno import ResultadoDoTurno, executar_turno
from mobia.domain.handoff.agendador import AgendadorDeResumoPort
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho
from mobia.domain.humano.deteccao import pediu_humano
from mobia.domain.messages.models import Message
from mobia.domain.messages.rajada import superada_por_mais_nova
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus
from mobia.domain.optout.deteccao import pediu_optout
from mobia.domain.outbound.port import OutboundPort
from mobia.domain.outbound.presenca import indicador_de_digitacao
from mobia.domain.outbound.repositorio import kinds_reservados
from mobia.infra.crypto import aad_de, decrypt

log = structlog.get_logger(__name__)

# String fixa, sem id dentro, pelo mesmo argumento de idempotencia que os KINDs
# de `turno.py` registram: kind que muda entre retentativas perde a dedup da
# reserva justamente quando ela importa. A coluna e String(32); isto tem 13.
KIND_DO_AVISO_DE_ERRO = "aviso_de_erro"

# Nao promete prazo nem explica a falha: o lead nao tem o que fazer com
# "timeout do provedor", e prometer horario e promessa que esta card nao tem
# como cumprir -- a alocacao de corretor e a TEC-166. E nao promete um AVISO
# que este sistema nao pratica -- notificar o corretor e a TEC-177, fora do
# escopo desta card. "Passei sua conversa para" descreve o que de fato ocorre
# (a linha PENDENTE em `handoffs`, que e por onde o time humano pega o caso)
# sem afirmar que alguem do outro lado ja foi avisado.
TEXTO_DO_AVISO_DE_ERRO = (
    "Tive um problema técnico aqui e não consegui seguir. "
    "Passei sua conversa para um corretor assumir."
)

# "skipped" e "agrupado" sao deste modulo; os outros nove vem do turno (Task 6,
# Literal de proposito: ver `ResultadoDoTurno`).
#
# Os dois sao distintos de proposito. "skipped" e anomalia -- claim recusado ou
# a mensagem sumiu entre o claim e a busca. "agrupado" e o caminho FELIZ da
# RN-01.6: a mensagem foi pega, e o certo era nao responder porque outra mais
# nova do mesmo lead assumiu o turno. Colapsar os dois tornaria ilegivel
# qualquer contagem de anomalia no log.
ResultadoDoProcessamento = Literal["skipped", "agrupado"] | ResultadoDoTurno


def _detalhe_para_a_coluna(exc: BaseException) -> str:
    """O que vai para `messages.last_error`: o nome da classe, e so.

    A coluna e `Text` em claro, duravel, sem cifra e fora da mascara de PII do
    log. Ate a TEC-222 aqui valia o criterio da TEC-134 -- excecao definida em
    `mobia` mantinha a mensagem inteira, porque "ela foi escrita aqui dentro e
    sabe-se o que ela carrega".

    **O criterio caiu porque confunde dono do TIPO com dono da MENSAGEM.**
    `ModeracaoIndisponivel` e definida em `domain/moderacao/port.py`, mas
    `infra/moderacao.py` a levanta com `motivo_do_provedor(exc)`: prosa que o
    servidor da Anthropic escreveu respondendo a uma requisicao cujo corpo e o
    texto moderado. O docstring de `motivo_do_provedor` aceita esse risco por
    escrito, e o limita com tres coisas -- o teto de 300 caracteres, o
    mascaramento de digitos de `app/logging.py` e o formato da chamada. **Uma
    delas, e so uma, e propriedade do log**: as outras duas ja valem no
    momento em que o texto e montado, e protegem esta coluna igual. O que a
    coluna perde e o mascaramento -- e ele alcanca corrida de 10 a 15 digitos
    contiguos e mais nada, entao para prosa em ingles de um SDK ele e quase um
    no-op.

    A diferenca entre os dois destinos e, portanto, MENOR do que parece, e nao
    e dela que sai a decisao. A decisao sai de duas outras coisas: esta coluna
    e duravel, e o criterio de dono do tipo nao se sustenta.

    Datas, porque elas sao o argumento: o criterio entrou em 26/08/2026
    (TEC-134, `d069f3e`) e foi violado em 30/08/2026 (TEC-237, `d79e2d7`),
    quatro dias depois, sem que nenhuma revisao notasse. Nao e o caso
    hipotetico do autor futuro desatento -- e o caso medido de duas cards da
    mesma semana, cada uma correta sozinha.

    Dai nao haver ramo nenhum: uma garantia que dependa de toda excecao futura
    ter sido escrita com cuidado nao e uma garantia. O texto continua no log,
    via `_detalhe_para_o_log`.
    """
    return type(exc).__name__


def _detalhe_para_o_log(exc: BaseException) -> str:
    """O que vai para o log estruturado, que e mais do que vai para a coluna.

    Este e o criterio da TEC-134, intacto, aplicado ao destino para o qual ele
    faz sentido: aqui a mascara de PII de `app/logging.py` alcanca o valor, e o
    raciocinio da TEC-237 sobre o corpo de erro do provedor foi escrito
    pensando neste destino.

    Manter a divisao importa nos dois sentidos. Emudecer o log junto com a
    coluna seria regressao de diagnostico sem ganho de seguranca -- e
    `test_texto_de_provedor_em_excecao_do_projeto_nao_chega_a_coluna` reprova
    se alguem fizer isso.
    """
    modulo = type(exc).__module__
    if modulo == "mobia" or modulo.startswith("mobia."):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


# Teto proprio para a escrita que registra um cancelamento. Quando ela roda,
# todo prazo ja se foi: o `asyncio.timeout` do arq disparou uma vez e nao volta
# a disparar, e o `wait_for` que o envolvia ja decorreu. Sem teto, um banco
# pendurado -- que e justamente uma das razoes de o turno ter estourado o
# orcamento -- prenderia o slot do worker para sempre e faria o `close()` do
# arq, que espera as tasks de job antes de desligar, nunca retornar.
SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO = 10


async def _marcar_falha(
    session_factory: async_sessionmaker[AsyncSession], identifier: uuid.UUID, detalhe: str
) -> int:
    """Fecha a linha como FAILED, conta a tentativa e devolve o novo total.

    Nao loga: os dois chamadores emitem eventos diferentes de proposito, e o
    que eles compartilham e so a escrita.

    **Devolve o total desde a TEC-174.** O incremento e expressao SQL, entao
    sem o `returning` ninguem em Python sabe quantas tentativas ja houve -- e
    "irrecuperavel" e a falha que ESGOTA as tentativas, nao qualquer falha.
    """
    async with session_factory() as session:
        resultado = await session.execute(
            update(Message)
            .where(Message.id == identifier)
            .values(
                status=MessageStatus.FAILED,
                attempts=Message.attempts + 1,
                last_error=detalhe,
            )
            .returning(Message.attempts)
        )
        await session.commit()
        return resultado.scalar_one()


async def _encaminhar_por_erro(
    session_factory: async_sessionmaker[AsyncSession],
    outbound: OutboundPort,
    message: Message,
    agendador: AgendadorDeResumoPort,
) -> None:
    """Cria o handoff do erro irrecuperavel e avisa o lead, nessa ordem.

    **Sessao propria**: a do turno morreu com a excecao.

    **Nada daqui pode escapar.** Uma excecao neste bloco SUBSTITUIRIA o erro
    original do turno e apagaria a causa real da falha -- e o mesmo argumento
    que o `except asyncio.CancelledError` deste arquivo ja faz para si.

    **Handoff primeiro, aviso depois**: o turno falhou, entao nao se sabe se o
    `outbound` responde. Se o aviso falhar, o handoff PERMANECE -- o corretor
    ser avisado nao pode depender de o lead ter sido avisado.
    """
    try:
        async with session_factory() as session:
            registro = await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.ERRO_DO_AGENTE,
            )
            await session.commit()
    except Exception as falha:
        log.error(
            "handoff.nao_registrado",
            message_id=str(message.id),
            reason=type(falha).__name__,
        )
        return

    # Depois do commit acima -- ver o comentario em `registrar_handoff` sobre
    # por que ela mesma nao loga.
    log.info(
        "handoff.criado" if registro.criado else "handoff.gatilho_adicional",
        channel=message.channel,
        gatilho=Gatilho.ERRO_DO_AGENTE.value,
        etiqueta=ETIQUETA_DE[Gatilho.ERRO_DO_AGENTE],
        prioridade=PRIORIDADE_DE[Gatilho.ERRO_DO_AGENTE].value,
    )

    # Mesma guarda de nao-propagacao do docstring acima, aplicada aqui: uma
    # excecao nesta chamada SUBSTITUIRIA a excecao original do turno e
    # apagaria a causa real da falha -- o mesmo argumento do `except
    # asyncio.CancelledError` deste arquivo. Falha ao agendar vira log e
    # segue -- o handoff permanece, e fica sem resumo ate a regeneracao.
    if registro.criado:
        try:
            await agendador.agendar(registro.id)
        except Exception as falha:
            # `exc_info=True`, e nao so `reason=type(falha).__name__`: este e
            # justamente o caminho de erro, onde o diagnostico mais importa.
            # O traceback aqui e da falha de AGENDAMENTO, no bloco que a
            # envolve -- nao o da excecao original do turno, que ja subiu e
            # foi tratada mais acima -- entao nao ha risco de confundir as
            # duas. Mesma fidelidade de `_agendar_resumo` em `turno.py`.
            #
            # Desde a TEC-293 o traceback leva pilha e tipo, nunca a mensagem,
            # entao `motivo` carrega o texto -- que aqui e seguro, porque a
            # unica coisa que esta chamada passa adiante e `registro.id`, um
            # UUID gerado por este projeto. Mesmo argumento da D3 da TEC-292.
            log.warning(
                "resumo_handoff.nao_agendado",
                handoff_id=str(registro.id),
                motivo=str(falha),
                exc_info=True,
            )

    try:
        await outbound.send(
            message.id,
            KIND_DO_AVISO_DE_ERRO,
            {
                "para": message.conversation_key,
                "de": message.recipient_external_id,
                "texto": TEXTO_DO_AVISO_DE_ERRO,
            },
        )
    except Exception as falha:
        log.warning(
            "handoff.aviso_nao_entregue",
            message_id=str(message.id),
            reason=type(falha).__name__,
        )


async def _tem_entrega_parcial_pendente(session_factory: Any, message_id: uuid.UUID) -> bool:
    """Esta mensagem apresentou um lote de fichas que ainda nao terminou de sair?

    TEC-128 (Important 2 da onda final). Mesma consulta e mesma condicao que
    `executar_turno` usa para decidir se entra no ramo de continuacao (TEC-275,
    D4, em torno de `turno.py:1395-1398`): um lote existe e pelo menos um dos
    kinds dele ja tem reserva -- ou seja, a apresentacao comecou e nao
    terminou. Sem esta checagem, a guarda de superacao (D3 da TEC-128)
    fecharia essa retentativa como "agrupado" antes de `executar_turno` ter a
    chance de continuar a entrega, e as fichas que faltam nunca sairiam.

    Repete a condicao em vez de chamar `executar_turno` porque aqui so o
    BOOLEANO importa -- diferente de la, que precisa do `lote` e do
    `ja_reservados` para montar a continuacao.
    """
    lote = await ler_apresentacao_da_mensagem(session_factory, message_id=message_id)
    if not lote:
        return False
    ja_reservados = await kinds_reservados(session_factory, message_id=message_id)
    return bool(ja_reservados & {linha.kind for linha in lote})


async def claim_message(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """Reivindica a mensagem para processamento.

    PROCESSING esta entre os estados reivindicaveis de proposito: e o estado que
    um worker morto no meio do job deixa para tras, e e o que permite a retomada.

    A exclusao mutua e **parcial**. O `SELECT ... FOR UPDATE SKIP LOCKED` resolve
    o caso simultaneo: quem chega com a linha travada sai limpo com False, em vez
    de bloquear, reavaliar o predicado contra a nova versao da linha (onde
    PROCESSING continua reivindicavel) e reivindicar tambem. O que ele nao cobre
    e o worker que chega depois do commit do primeiro -- por construcao, ja que
    e assim que a retomada funciona. Exclusao completa pede um lease com coluna
    `claimed_at`, que fica para uma historia posterior.
    """
    reservada = await session.execute(
        select(Message.id)
        .where(Message.id == message_id, Message.status.in_(CLAIMABLE_STATUSES))
        .with_for_update(skip_locked=True)
    )
    if reservada.scalar_one_or_none() is None:
        return False

    # O `execute` de um UPDATE devolve um CursorResult em runtime, mas a tipagem
    # do SQLAlchemy declara o Result generico, que nao expoe `rowcount`.
    resultado = cast(
        CursorResult[Any],
        await session.execute(
            update(Message)
            .where(Message.id == message_id, Message.status.in_(CLAIMABLE_STATUSES))
            .values(status=MessageStatus.PROCESSING)
        ),
    )
    return resultado.rowcount == 1


async def process_message(ctx: dict[str, Any], message_id: str) -> ResultadoDoProcessamento:
    session_factory = ctx["session_factory"]
    outbound = ctx["outbound"]
    # `ctx[...]` direto, e nao `ctx.get(...) or AgendadorNoop()`: ao contrario
    # de `ctx.get("settings") or get_settings()` (`sweep_stalled.py`), onde o
    # fallback constroi um `Settings` real e equivalente ao que a chave daria,
    # aqui o fallback trocaria uma porta real por um duble de teste dentro de
    # producao -- e o sintoma de um `startup` que deixe de popular a chave
    # seria nenhum resumo agendado, para sempre, sem log e sem erro. Um
    # `ctx["agendador"]` ausente deve estourar `KeyError` alto, na primeira
    # mensagem -- o mesmo raciocinio que a guarda de `WHATSAPP_ACCESS_TOKEN`
    # em `workers/main.py` ja aplica a outras portas.
    agendador = ctx["agendador"]
    # `ctx[...]` direto pela mesma razao que `agendador` logo acima: um
    # `ctx.get("indicador") or IndicadorNoop()` trocaria a porta real por um
    # duble dentro de producao, e o sintoma de um `startup` que deixasse de
    # popular a chave seria nenhum indicador, nunca, sem log e sem erro.
    identifier = uuid.UUID(message_id)

    async with session_factory() as session:
        if not await claim_message(session, identifier):
            await session.rollback()
            log.info("message.skipped", message_id=message_id, reason="not_claimable")
            return "skipped"
        await session.commit()

    # Fora do try: se o proprio `get` falhar, o except abaixo nao teria
    # como montar o handoff (precisa de `channel`/`conversation_key`) e
    # `linha` continua None -- ver a guarda antes de `_encaminhar_por_erro`.
    linha: Message | None = None
    try:
        async with session_factory() as session:
            linha = await session.get(Message, identifier)
        if linha is None:
            log.warning("message.sumiu", message_id=message_id)
            return "skipped"

        # RN-01.6 (TEC-128, D4): entre o claim e aqui, uma mensagem mais nova
        # do mesmo lead pode ter chegado. Se chegou, o turno dela e que deve
        # responder -- esta fecha PROCESSED sem rodar nada, e nao ha reserva
        # de outbound para liberar porque nenhuma foi feita. Ha tres excecoes,
        # tratadas logo abaixo: opt-out, pedido de humano e entrega parcial
        # pendente. Nos tres o turno roda mesmo superada.
        async with session_factory() as session:
            if await superada_por_mais_nova(session, linha):
                # A excecao do opt-out existe por um defeito que a TEC-182
                # previu por escrito. Sem ela: o lead pede para parar e, nos
                # milissegundos seguintes, manda outra coisa; esta mensagem
                # sai como "agrupado", `pediu_optout` nunca roda sobre ela, e
                # o opt-out NUNCA e registrado -- em silencio, sem log de erro.
                #
                # O enqueue sem atraso de `IngestionService.ingest` nao basta:
                # ele vence a corrida no caso comum, nao em todos.
                #
                # Nao ha decisao duplicada com o turno: e a mesma funcao pura
                # sobre o mesmo texto da mesma mensagem, entao os dois sitios
                # nao tem como divergir sem que `pediu_optout` mude para ambos.
                corpo = decrypt(linha.text_body, aad_de(linha.id, "text_body"))
                # `bool(...)` por fora, e nao `bool(corpo) and ...`: so a forma
                # curta-circuitada estreita `corpo` de `str | None` para `str`
                # dentro da chamada -- mesmo idioma de `turno.py`.
                pedido_de_optout = bool(corpo and pediu_optout(corpo))
                # Mesmo furo, mesma razao, aplicada a RN-16.1/emenda E-04 (TEC-128,
                # onda final, Critical 1): sem ele, um pedido de humano isolado
                # que perde a corrida contra uma mensagem mais nova fecha como
                # "agrupado", `pediu_humano` nunca roda sobre ele, e nenhum
                # handoff nasce -- o lead que pediu uma pessoa fica preso no
                # robo, em silencio.
                pedido_de_humano = bool(corpo and pediu_humano(corpo))
                if pedido_de_optout or pedido_de_humano:
                    log.info(
                        "message.optout_fura_a_janela"
                        if pedido_de_optout
                        else "message.pedido_de_humano_fura_a_janela",
                        message_id=message_id,
                    )
                # A terceira excecao (TEC-128, onda final, Important 2): uma
                # retentativa que ja apresentou fichas e nao terminou de
                # entrega-las nao pode ser descartada so porque uma mensagem
                # mais nova chegou durante a espera -- as fichas que faltam
                # nunca sairiam, e a linha de `recomendacoes` delas ficaria
                # orfa. So checa quando as duas primeiras ja liberaram o
                # caminho comum: e a mais cara das tres (duas consultas), e as
                # outras duas ja decidem a maioria dos casos.
                elif await _tem_entrega_parcial_pendente(session_factory, identifier):
                    log.info("message.entrega_parcial_fura_a_janela", message_id=message_id)
                else:
                    await session.execute(
                        update(Message)
                        .where(Message.id == identifier)
                        .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
                    )
                    await session.commit()
                    log.info("message.agrupado", message_id=message_id)
                    return "agrupado"

        # TEC-274, RN-04.7. O relogio mede o turno INTEIRO -- contexto,
        # resumo, modelo e as duas moderacoes --, e nao so a chamada ao
        # classificador: e o silencio que o lead percebe. Um turno com tres
        # segundos de contexto e tres e meio de modelo nao ultrapassa quatro
        # em nenhuma parte e deixa o lead seis segundos e meio no vazio.
        #
        # Mora AQUI e nao dentro de `executar_turno` porque as guardas baratas
        # ficam no topo daquela funcao e a primeira entrega mil e trezentas
        # linhas abaixo: o `async with` la dentro reindentaria cerca de duas
        # mil linhas, e a protecao que a posicao daria e reproduzida -- melhor
        # -- pela conferencia no disparo. Ver as D2 e D3 do desenho.
        #
        # TEC-128: o relogio conta do RECEBIMENTO, nao do inicio do job. Com o
        # debounce da RN-01.6 o job so comeca uma janela depois de o lead
        # apertar enviar; somar as duas esperas deixaria o lead em silencio
        # absoluto durante a janela inteira -- o oposto do que a TEC-274 quis
        # quando escreveu que o relogio mede "o silencio que o lead percebe".
        idade = (datetime.now(UTC) - linha.created_at).total_seconds()
        apos_segundos = max(0.0, get_settings().indicador_de_digitacao_apos_segundos - idade)
        async with indicador_de_digitacao(
            session_factory,
            message=linha,
            indicador=ctx["indicador"],
            apos_segundos=apos_segundos,
        ):
            resultado = await executar_turno(
                session_factory,
                message=linha,
                classificador=ctx["classificador"],
                resumidor=ctx["resumidor"],
                contador=ctx["contador"],
                outbound=outbound,
                moderador=ctx["moderador"],
                agendador=agendador,
            )

        async with session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == identifier)
                .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
            )
            await session.commit()
    except Exception as exc:
        tentativas = await _marcar_falha(session_factory, identifier, _detalhe_para_a_coluna(exc))
        # Valor que PODE ser maior que o da coluna, desde a TEC-222: para
        # excecao de `mobia` o log carrega a mensagem inteira e a coluna so o
        # nome da classe; para excecao de terceiro (DBAPIError,
        # CancelledError, o caso mais comum) os dois valores coincidem. A
        # coluna e duravel e fora da mascara, o log nao. Ver os dois
        # docstrings acima.
        log.warning("message.failed", message_id=message_id, error=_detalhe_para_o_log(exc))
        # So encaminha quando as tentativas ESGOTARAM (D9) -- na primeira
        # falha a proxima retentativa ainda pode resolver, e handoff aqui
        # seria alarme falso para o corretor. `linha is not None` cobre o
        # caso raro de o `session.get` acima ser o que falhou: sem a linha
        # nao ha `channel`/`conversation_key` para o handoff.
        if linha is not None and tentativas >= get_settings().sweep_max_attempts:
            await _encaminhar_por_erro(session_factory, outbound, linha, agendador)
        raise
    except asyncio.CancelledError as exc:
        # `CancelledError` e BaseException, nao Exception: o `except` acima nao
        # a pega. Sem esta clausula a linha fica em PROCESSING -- e como
        # PROCESSING e reivindicavel e `attempts` nao subia, o sweeper
        # reenfileirava para sempre, pagando o turno inteiro a cada volta.
        try:
            async with asyncio.timeout(SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO):
                await _marcar_falha(session_factory, identifier, _detalhe_para_a_coluna(exc))
        except Exception as falha:
            # Esta excecao nao pode escapar: ela **substituiria** o
            # CancelledError, o worker deixaria de ver o cancelamento e o
            # desligamento limpo quebraria -- justamente a garantia que esta
            # clausula existe para dar. Vira evento proprio e o cancelamento
            # segue seu caminho. A linha fica em PROCESSING, que o sweeper
            # ainda recupera, so que sem contar a tentativa.
            log.error(
                "message.cancelled_nao_registrado",
                message_id=message_id,
                reason=type(falha).__name__,
            )
        # Evento proprio, e nao `message.failed`: cancelamento e problema
        # operacional diferente de o turno falhar. Desde a TEC-232 o SIGTERM de
        # um deploy drena os jobs em voo antes de cancelar
        # (`job_completion_wait` em `workers/main.py`), entao o que chega aqui e
        # quase sempre o `job_timeout` estourando. O deploy so alcanca este
        # ponto se o turno atravessar a janela inteira de drenagem -- e ai o
        # orcamento dele realmente acabou. Ver a secao TEC-232 do README.
        log.warning("message.cancelled", message_id=message_id, error=_detalhe_para_o_log(exc))
        raise

    log.info("message.processed", message_id=message_id)
    return resultado

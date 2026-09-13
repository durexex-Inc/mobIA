import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

import structlog
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.agente.turno import ResultadoDoTurno, executar_turno
from mobia.domain.handoff.agendador import AgendadorDeResumoPort
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus
from mobia.domain.outbound.port import OutboundPort

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
    "Tive um problema tecnico aqui e nao consegui seguir. "
    "Passei sua conversa para um corretor assumir."
)

# "skipped" e deste modulo -- claim recusado ou a mensagem sumiu entre o claim
# e a busca -- os outros nove vem do turno (Task 6, Literal de proposito: ver
# `ResultadoDoTurno`).
ResultadoDoProcessamento = Literal["skipped"] | ResultadoDoTurno


def _detalhe_do_erro(exc: BaseException) -> str:
    """O que pode ser gravado em `messages.last_error` sem risco de vazamento.

    `last_error` e coluna `Text` durvel e **nao** passa pela mascara de PII do
    log. Ate a TEC-134 so excecoes da ingestao chegavam aqui. Agora duas
    chamadas a terceiros ficam a montante -- `contador.contar` e
    `messages.create`, ambas com a conversa decifrada do lead no corpo da
    requisicao -- e `str(exc)` de uma excecao de terceiro nao e uma garantia
    que este projeto possa dar: o SDK em geral nao ecoa o corpo na mensagem,
    mas "em geral" nao e o padrao que a restricao de nao logar conteudo do
    lead aceita.

    Dai o criterio pelo dono do tipo: excecao definida em `mobia` teve a
    mensagem escrita aqui dentro e sabe-se o que ela carrega (ver
    `RespostaInvalida`, que so guarda o nome da classe original). De qualquer
    outra, so o nome -- que ja e o que aponta para o modulo culpado.
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
        except Exception:
            # `exc_info=True`, e nao so `reason=type(falha).__name__`: este e
            # justamente o caminho de erro, onde o diagnostico mais importa.
            # O traceback aqui e da falha de AGENDAMENTO, no bloco que a
            # envolve -- nao o da excecao original do turno, que ja subiu e
            # foi tratada mais acima -- entao nao ha risco de confundir as
            # duas. Mesma fidelidade de `_agendar_resumo` em `turno.py`.
            log.warning("resumo_handoff.nao_agendado", handoff_id=str(registro.id), exc_info=True)

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
        detalhe = _detalhe_do_erro(exc)
        tentativas = await _marcar_falha(session_factory, identifier, detalhe)
        # Mesmo valor da coluna, e pelo mesmo motivo: o log estruturado nao
        # mascara `error`, e a chave nao esta na lista de campos redigidos.
        log.warning("message.failed", message_id=message_id, error=detalhe)
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
        detalhe = _detalhe_do_erro(exc)
        try:
            async with asyncio.timeout(SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO):
                await _marcar_falha(session_factory, identifier, detalhe)
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
        log.warning("message.cancelled", message_id=message_id, error=detalhe)
        raise

    log.info("message.processed", message_id=message_id)
    return resultado

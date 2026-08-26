import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.outbound.models import OutboundDispatch

log = structlog.get_logger(__name__)

# A UNIQUE (message_id, kind) de `outbound_dispatches` -- ver
# `OutboundDispatch.__table_args__`. E a unica violacao de integridade que
# significa "ja reservei este envio".
UNIQUE_DA_RESERVA = "uq_outbound_message_kind"


def _e_reserva_duplicada(exc: IntegrityError) -> bool:
    """Distingue a colisao da reserva de qualquer outra falha de integridade.

    Tratar todo IntegrityError como duplicata converte uma falha nao
    relacionada (FK quebrada, NOT NULL, um constraint novo que alguem
    adicionar amanha) no desfecho terminal do turno: `send()` devolve False, o
    turno vira "reentrega_suprimida", a linha fecha em PROCESSED -- terminal --
    e o lead nunca recebe nada, com uma linha de log que diz "duplicata
    suprimida" e manda quem investiga para o lado errado.

    `constraint_name` vem do asyncpg; a checagem no texto e o fallback para
    qualquer outro driver, que ainda cita o nome do constraint na mensagem.
    """
    original = exc.orig
    nome = getattr(original, "constraint_name", None)
    if nome is not None:
        return bool(nome == UNIQUE_DA_RESERVA)
    return UNIQUE_DA_RESERVA in str(original)


class OutboundPort(Protocol):
    """A porta de saida do turno -- e o contrato de excecoes que vem junto.

    A assinatura declara so `send`, mas a correcao de `executar_turno` depende
    inteiramente de **qual** excecao a implementacao levanta. Sem isto escrito,
    um adaptador novo (a TEC-124 traz o canal web) escolhe o tipo errado e
    muda o desfecho do turno sem tocar em nenhuma linha do dominio:

    - `EnvioRetentavel` -- rede, 5xx, 408, 429. A guarda libera a reserva e
      propaga: a mensagem vira FAILED e o sweeper retenta. O lead recebe
      eventualmente.
    - `EnvioForaDaJanela` -- o canal nao aceita mais mensagem livre nesta
      conversa. Turno `expirado`, PROCESSED, aviso no log. Expirar nao e
      falhar, e retentar nunca entregaria.
    - `EnvioRecusado` -- 4xx permanente. Turno `sem_resposta`, PROCESSED, log
      em `error` (e o alerta que observa isso). FAILED aqui faria o sweeper
      rodar o turno inteiro de novo, chamada paga ao modelo inclusa, por um
      payload que nunca sera aceito.
    - Qualquer outra excecao propaga crua: a reserva **fica**, a mensagem vira
      FAILED e a retentativa cai na supressao de reentrega. Levantar algo fora
      destes tres tipos e escolher esse desfecho sem querer.

    E `send` devolve `False`, sem levantar, quando a guarda suprime uma
    reentrega -- ver `GuardedOutbound.send` e `turno.reentrega_suprimida`.
    """

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool: ...


class EnvioRetentavel(Exception):
    """Falha de envio que uma nova tentativa pode resolver -- rede, 5xx."""


class EnvioRecusado(Exception):
    """Falha de envio permanente -- 4xx. Retentar nao muda nada."""


class EnvioForaDaJanela(EnvioRecusado):
    """O canal nao aceita mais mensagem livre nesta conversa.

    Herda de EnvioRecusado porque retentar nao ajuda. Mas e distinguivel de um
    4xx comum porque nao e erro nosso: o turno termina PROCESSED com aviso,
    nao com erro de payload.

    Mora aqui, e nao no adaptador do WhatsApp que a levanta hoje, porque
    `executar_turno` a captura e o turno e agnostico de canal em todo o resto
    -- ele recebe um `OutboundPort`. O nome ficou como estava, sem um
    "EnvioExpirado" neutro com subclasse do WhatsApp por cima: a janela de 24h
    da Meta e a unica encarnacao existente do conceito, e uma hierarquia de
    dois niveis com um so habitante seria estrutura para um caso hipotetico.
    O canal web da TEC-124 nao tem janela nenhuma -- ele simplesmente nunca
    levanta esta excecao.
    """


class GuardedOutbound:
    """Reserva antes de entregar.

    A linha em outbound_dispatches e commitada antes do efeito externo. Queda
    entre a reserva e a entrega so perde aquele envio quando a falha e
    permanente (EnvioRecusado); queda depois nunca duplica. Falha retentavel
    (EnvioRetentavel) libera a reserva para a proxima tentativa poder entregar.
    O criterio de aceite exige "nenhuma resposta duplicada" -- a troca e essa,
    e continua valendo no caminho de sucesso e na falha permanente.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        async with self._session_factory() as session:
            session.add(OutboundDispatch(id=uuid.uuid4(), message_id=message_id, kind=kind))
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if not _e_reserva_duplicada(exc):
                    raise
                # `info` de proposito, e nao `error` como o desfecho do turno:
                # aqui a supressao ainda pode ser o caso benigno (um ACK
                # reentregue). Quem sabe que o que se perdeu foi a resposta ao
                # lead e `executar_turno`, e e la que o nivel sobe -- ver
                # `turno.reentrega_suprimida`.
                log.info(
                    "outbound.duplicate_suppressed",
                    message_id=str(message_id),
                    kind=kind,
                )
                return False

        try:
            await self._deliver(message_id, kind, payload)
        except EnvioRetentavel:
            # A reserva foi desenhada na TEC-122 para um ACK, e ali perder o
            # envio nao custava nada. Agora o que se perde e a resposta ao
            # lead: a reserva commitada faz o sweeper reenfileirar, o worker
            # reivindicar e a guarda responder "ja entreguei isso" -- e o lead
            # nunca recebe nada sobre aquele turno. Liberar inverte a troca
            # para uma duplicata possivel, que e visivel e recuperavel.
            try:
                await self._liberar(message_id, kind)
            except Exception as exc:
                # Se o proprio delete da liberacao falhar (deadlock, conexao
                # caida), quem chama send() ainda precisa ver EnvioRetentavel,
                # nao um erro de infra do release -- senao um retentavel vira
                # permanente por engano e a reserva fica presa do mesmo jeito
                # que este bloco existe para evitar. O erro de liberacao vira
                # seu proprio evento de log, porque e um problema operacional
                # diferente de perder o envio.
                log.error(
                    "outbound.liberacao_falhou",
                    message_id=str(message_id),
                    kind=kind,
                    # Sem o tipo, este evento nao tem nada de que se depurar --
                    # um TypeError daqui de dentro fica indistinguivel de um
                    # deadlock do banco. So o nome da classe, como no resto do
                    # projeto: nao vaza conteudo.
                    reason=type(exc).__name__,
                )
            raise

        log.info("outbound.delivered", message_id=str(message_id), kind=kind)
        return True

    async def _liberar(self, message_id: uuid.UUID, kind: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(OutboundDispatch).where(
                    OutboundDispatch.message_id == message_id,
                    OutboundDispatch.kind == kind,
                )
            )
            await session.commit()
        log.warning("outbound.reserva_liberada", message_id=str(message_id), kind=kind)

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

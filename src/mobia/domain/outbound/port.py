import asyncio
import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.atendimento.repositorio import esta_silenciada_por_mensagem
from mobia.domain.optout.deteccao import KIND_DA_CONFIRMACAO_DE_OPTOUT
from mobia.domain.optout.repositorio import esta_em_optout_por_mensagem
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
    - `EnvioRecusado` -- 4xx permanente. No caminho de texto unico: turno
      `sem_resposta`, PROCESSED, log `outbound.recusado_permanente` em `error`
      (e o alerta que observa isso). FAILED aqui faria o sweeper rodar o turno
      inteiro de novo, chamada paga ao modelo inclusa, por um payload que
      nunca sera aceito.
      **Na apresentacao de fichas (TEC-162, D10) o desfecho e outro:** a
      recusa de UMA ficha nao interrompe as outras. Ela loga
      `apresentacao.ficha_recusada` em `error`, com o `kind` da posicao, e o
      turno segue -- devolvendo `respondido` se qualquer outra ficha entrou. O
      `sem_resposta` so volta quando TODAS as fichas do turno foram
      recusadas -- que pode ser uma, duas ou tres. `MAX_IMOVEIS_POR_TURNO` e
      um teto, nao um piso: um turno com menos de tres candidatos, ou um em
      que `imoveis_por_ids` derrubou algum, tem menos de tres fichas para
      recusar em primeiro lugar. A divergencia e deliberada: a recusa
      provavel ali e a Meta rejeitando a URL da foto, e uma foto ruim nao
      pode apagar os outros imoveis bons do mesmo turno.
      Os dois nomes de evento importam por igual para quem configura alerta:
      **nao existe regra de alerta neste repositorio** -- ela vive no
      monitoramento externo, que casa por nome --, e este bullet e o unico
      lugar da arvore que diz quais nomes observar. Alertar so em
      `outbound.recusado_permanente` deixa uma apresentacao inteiramente
      recusada passar em silencio.
    - Qualquer outra excecao propaga crua: a reserva **fica**, a mensagem vira
      FAILED e a retentativa cai na supressao de reentrega. Levantar algo fora
      destes tres tipos e escolher esse desfecho sem querer.

    `asyncio.CancelledError` nao esta nessa lista porque nao e escolha de
    adaptador nenhum: e o `job_timeout` do worker ou o shutdown chegando de
    fora. A guarda a trata como retentavel (libera a reserva e propaga) --
    ver TEC-227.

    `send` devolve `False`, sem levantar, em duas situacoes distintas, e
    quem le o retorno nao consegue distinguir uma da outra so pelo booleano:

    - Reentrega suprimida: a reserva em `outbound_dispatches` ja existia
      para este `(message_id, kind)` -- ver `GuardedOutbound.send` e
      `turno.reentrega_suprimida`.
    - Envio barrado pela guarda de opt-out: o lead deste `message_id` pediu
      para parar de receber mensagem, e `kind` nao e
      `KIND_DA_CONFIRMACAO_DE_OPTOUT` -- ver `GuardedOutbound.send` e
      `esta_em_optout_por_mensagem`.
    - Envio barrado pela guarda de atendimento humano: um corretor assumiu
      esta conversa e ainda nao a devolveu (TEC-179, RN-16.4) -- ver
      `GuardedOutbound.send` e `esta_silenciada_por_mensagem`. Ao contrario
      da guarda de opt-out, esta nao tem excecao por `kind`.

    `OutboundPort` e um Protocol estrutural: qualquer classe com um metodo
    `send` de assinatura compativel satisfaz o tipo, herdando de
    `GuardedOutbound` ou nao. As guardas de opt-out e de atendimento humano,
    porem, so existem dentro do corpo de `GuardedOutbound.send` -- nao ha
    nada no `Protocol` em si, nem no `mypy`, que as force. Um adaptador novo
    escrito direto contra este Protocol, sem herdar de `GuardedOutbound`,
    tipa igual e passa em qualquer checagem estatica, mas nao tem guarda
    nenhuma: ele manda mensagem para quem pediu para parar, e fala por cima
    do corretor que assumiu a conversa. Isso nao e um bug de performance ou
    um turno errado -- e uma violacao de LGPD no primeiro caso, e no segundo
    o proprio motivo de existir da TEC-179. Quem for por esse caminho
    precisa reimplementar as duas checagens por conta propria; a rota
    segura e herdar de `GuardedOutbound`.
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
    """Barra quem pediu opt-out, reserva, e so entao entrega.

    A guarda de opt-out (TEC-182) roda antes da reserva, e e a razao de o
    docstring de `OutboundPort` apontar esta classe como a rota segura: herdar
    daqui e o que garante que um caminho de envio novo nao fale com quem pediu
    silencio. O unico kind que a atravessa e
    `KIND_DA_CONFIRMACAO_DE_OPTOUT` -- ver `send`.

    A linha em outbound_dispatches e commitada antes do efeito externo. Queda
    entre a reserva e a entrega so perde aquele envio quando a falha e
    permanente (EnvioRecusado); queda depois nunca duplica. Falha retentavel
    (EnvioRetentavel) e cancelamento (`asyncio.CancelledError`, TEC-227)
    liberam a reserva para a proxima tentativa poder entregar. O criterio de
    aceite exige "nenhuma resposta duplicada" -- a troca e essa, e continua
    valendo no caminho de sucesso e na falha permanente.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        # A guarda de opt-out mora AQUI, e nao em `executar_turno`, de
        # proposito. No turno ela protegeria o caminho de hoje e nada mais, e a
        # TEC-183 vai criar um segundo caminho de envio. Quem HERDA desta
        # classe ganha a guarda de graca, sem precisar lembrar dela -- e e por
        # isso que ela mora aqui. Mas herdar e o mecanismo, nao uma garantia
        # da linguagem: quem implementar `OutboundPort` direto, sem herdar,
        # nao tem a guarda -- ver o aviso no docstring do Protocol acima.
        #
        # Antes da reserva: barrar depois deixaria linha orfa em
        # `outbound_dispatches`, e o sweeper leria isso como tentativa feita.
        if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT:
            async with self._session_factory() as session:
                if await esta_em_optout_por_mensagem(session, message_id):
                    # `warning` e nao `info`: um envio barrado aqui significa
                    # que algum caminho tentou falar com quem pediu silencio.
                    # Nao e erro nosso -- a guarda funcionou --, mas e o
                    # sintoma que denuncia um caminho sem a checagem barata do
                    # turno.
                    log.warning(
                        "outbound.optout_bloqueou",
                        message_id=str(message_id),
                        kind=kind,
                    )
                    return False

        # A guarda de atendimento humano (TEC-179, RN-16.4). Mora aqui pela
        # mesma razao que a de opt-out logo acima, e o docstring do
        # `OutboundPort` ja escreve: quem herda ganha a guarda de graca. No
        # turno ela protegeria so o caminho de hoje.
        #
        # **Barra TODO kind, sem a escotilha que o opt-out tem.** A D5 do
        # desenho decide isso: nao existe caminho humano de envio para deixar
        # passar -- a rota `POST /conversas/{id}/mensagens` do SRS nao esta
        # implementada --, e uma lista de excecoes construida agora seria para
        # um chamador hipotetico. Quando aquela rota chegar ela vai encontrar
        # o proprio envio barrado aqui, e tera de decidir como o humano
        # atravessa. Falhar fechado e o lado certo de errar, e a L3 do desenho
        # existe para que ninguem descubra isso por um teste vermelho sem
        # explicacao.
        #
        # Antes da reserva pelo mesmo motivo do bloco acima: barrar depois
        # deixaria linha orfa em `outbound_dispatches`.
        async with self._session_factory() as session:
            if await esta_silenciada_por_mensagem(session, message_id):
                # `warning` e nao `info`, pelo mesmo criterio do opt-out: um
                # envio barrado aqui significa que algum caminho tentou falar
                # por cima do corretor que assumiu.
                log.warning(
                    "outbound.atendimento_humano_bloqueou",
                    message_id=str(message_id),
                    kind=kind,
                )
                return False

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
        except (EnvioRetentavel, asyncio.CancelledError):
            # A reserva foi desenhada na TEC-122 para um ACK, e ali perder o
            # envio nao custava nada. Agora o que se perde e a resposta ao
            # lead: a reserva commitada faz o sweeper reenfileirar, o worker
            # reivindicar e a guarda responder "ja entreguei isso" -- e o lead
            # nunca recebe nada sobre aquele turno. Liberar inverte a troca
            # para uma duplicata possivel, que e visivel e recuperavel.
            #
            # `CancelledError` entra na mesma clausula, e nao numa propria, de
            # proposito: o que fazer e identico, e duas copias do bloco
            # divergiriam. O gatilho e que e diferente -- ele nao e excecao
            # tipada nossa, e sim o `job_timeout` do worker ou o shutdown, e
            # cai em qualquer ponto do `_deliver`, inclusive depois de o POST
            # ter chegado a Meta. Nesse caso a duplicata acontece de verdade;
            # a TEC-227 escolheu esse lado pelo mesmo criterio da TEC-134.
            try:
                await self._liberar(message_id, kind)
            except Exception as exc:
                # Se o proprio delete da liberacao falhar (deadlock, conexao
                # caida), quem chama send() ainda precisa ver a excecao
                # original -- o EnvioRetentavel ou o cancelamento -- e nao um
                # erro de infra do release: senao um retentavel vira permanente
                # por engano, ou o cancelamento some, e a reserva fica presa do
                # mesmo jeito que este bloco existe para evitar. Um
                # cancelamento *da propria liberacao* nao cai aqui, porque
                # `CancelledError` nao e Exception -- ele propaga, que e o
                # desfecho certo. O erro de liberacao vira
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

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from arq.connections import ArqRedis
from sqlalchemy import CursorResult, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.humano.deteccao import pediu_humano
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_NUMERO
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.deteccao import pediu_optout
from mobia.infra.crypto import aad_de, encrypt, encrypt_json
from mobia.infra.db import motivo_do_erro_de_banco
from mobia.infra.queue import enqueue_process_message
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_numero, consumir

log = structlog.get_logger(__name__)


class IngestionService:
    """Persiste a mensagem recebida e so entao a enfileira.

    A ordem importa: a linha commitada no Postgres e a garantia de nao-perda.
    Depois do `_persist`, o enqueue e a virada de status continuam otimistas
    -- a mensagem fica em RECEIVED e o sweeper (workers/jobs/sweep_stalled.py)
    a recupera -- mas nenhum dos dois engole toda excecao.

    `consumir` (chamado daqui para o rate limit por numero) so absorve
    `RedisError`: indisponibilidade de Redis fica silenciosa e fail-open, por
    decisao de `infra/rate_limit.py`. Qualquer outra classe de falha --
    `AttributeError` num pool mal construido, `RuntimeError: Event loop is
    closed` num shutdown mal ordenado -- sobe. `registrar_bloqueio` absorve
    falha de escrita no banco, mas constroi o `RateLimitEvent` FORA do seu
    try: erro de construcao e defeito de codigo, nao indisponibilidade, e
    tambem sobe.

    Consequencia para quem le isto de fora: uma excecao que escape por
    qualquer um desses caminhos sobe ate quem chamou, e desde a TEC-124 sao
    dois, com desfechos diferentes de proposito. No webhook ela vira 500 e a
    Meta re-entrega -- sem duplicar, porque o UNIQUE de `(channel,
    provider_message_id)` segura, mas custando uma retentativa a toa. No
    widget (`api/routes/widget.py`) ela e capturada e a conexao fecha com
    1011: la o equivalente da reentrega e o cliente reenviar com o mesmo id.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: ArqRedis | None,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue

    async def ingest(
        self, parsed: list[ParsedMessage], channel: str = CANAL_WHATSAPP
    ) -> list[uuid.UUID]:
        if not parsed:
            return []

        gravadas = await self._persist(parsed, channel)
        # A leitura da config mora AQUI, uma vez por lote, e nao dentro de
        # `_try_enqueue`: quem decide o atraso por mensagem e a ingestao. O que
        # e unico e a LEITURA da configuracao, nao o atraso aplicado -- cada
        # mensagem do lote recebe zero, a janela de debounce ou, desde a
        # TEC-205, o backoff do rate limit por numero, decidido logo abaixo.
        # Ler dentro de `_try_enqueue` colocaria a leitura de configuracao na
        # camada errada.
        settings = get_settings()
        janela = settings.debounce_de_rajada_segundos
        limite = settings.rate_limit_mensagens_por_minuto
        backoff = settings.atraso_de_backoff_segundos
        # Colapsa `provider_message_id` repetido dentro do MESMO envelope para
        # o texto da ULTIMA ocorrencia. So e inofensivo porque uma reentrega da
        # Meta traz sempre o mesmo texto (o `wamid` e do provedor, nao nosso) --
        # nao ha caso em que duas ocorrencias do mesmo id tragam corpos
        # diferentes para este dicionario escolher entre eles.
        texto_de = {item.provider_message_id: item.text_body for item in parsed}
        # O numero do lead por `provider_message_id`, pelo mesmo motivo e com a
        # mesma ressalva de `texto_de` acima: `gravadas` traz id interno e id
        # do provedor, nao o remetente.
        remetente_de = {item.provider_message_id: item.sender_external_id for item in parsed}
        for message_id, provider_message_id in gravadas:
            texto = texto_de.get(provider_message_id) or ""
            # O opt-out nao espera a janela (RN-01.6 + RN-14), e desde a
            # TEC-128 (onda final) o pedido de humano tambem nao (RN-16.1,
            # emenda E-04: o handoff precisa nascer em ate 5s, e o debounce
            # incondicional levaria toda mensagem a esperar a janela inteira
            # antes de qualquer handoff). `pediu_optout` e `pediu_humano` sao
            # puras e deterministicas, sem chamada paga, e aqui o texto ainda
            # esta em claro -- e o unico ponto do fluxo onde ele esta.
            pediu = pediu_optout(texto) or pediu_humano(texto)

            # A cota e consumida por TODA mensagem, inclusive a que pede
            # opt-out ou humano. Contar so as demais deixaria quem inunda o
            # canal com "pare" fora de qualquer registro -- e a contagem aqui
            # e o que a tabela de eventos publica. O que o opt-out fura e o
            # ATRASO, nao a contagem: um limite de volume atrasar justamente o
            # pedido de parar de receber mensagens seria o contrario do que a
            # RN-14 promete.
            consumo = await consumir(
                self._queue,
                chave=chave_de_numero(channel, remetente_de.get(provider_message_id, "")),
                limite=limite,
                janela_segundos=JANELA_DE_UM_MINUTO,
            )

            if consumo.permitido:
                atraso = 0.0 if pediu else janela
            else:
                atraso = 0.0 if pediu else backoff
                log.warning(
                    "ratelimit.blocked",
                    escopo=ESCOPO_NUMERO,
                    conversation_key=remetente_de.get(provider_message_id, ""),
                    channel=channel,
                    volume=consumo.volume,
                    limite=limite,
                )
                await registrar_bloqueio(
                    self._session_factory,
                    self._queue,
                    escopo=ESCOPO_NUMERO,
                    chave=remetente_de.get(provider_message_id, ""),
                    channel=channel,
                    volume=consumo.volume,
                    limite=limite,
                    message_id=message_id,
                )

            await self._try_enqueue(message_id, atraso_segundos=atraso)
        return [message_id for message_id, _ in gravadas]

    async def _persist(
        self, parsed: list[ParsedMessage], channel: str
    ) -> list[tuple[uuid.UUID, str]]:
        """Grava as mensagens novas e descarta as que ja tinham chegado.

        "Ja tinham chegado" e a reentrega da Meta, e desde a TEC-124 tambem o
        reenvio do widget depois de uma queda -- os dois com o mesmo
        `provider_message_id`, que no web e o id que a pagina gerou.

        O descarte e resolvido pelo `ON CONFLICT` do proprio Postgres, nao por
        uma checagem em memoria: duas replicas da API recebendo a mesma reentrega
        ao mesmo tempo so podem ser separadas pela constraint (TEC-125). O
        `DO NOTHING` tambem impede que uma duplicata no meio do lote derrube as
        mensagens legitimas que vieram junto.
        """
        valores = []
        for item in parsed:
            identificador = uuid.uuid4()
            valores.append(
                {
                    "id": identificador,
                    "channel": channel,
                    "provider_message_id": item.provider_message_id,
                    "sender_external_id": item.sender_external_id,
                    "recipient_external_id": item.recipient_external_id,
                    # Quem fala e o lead, entao a conversa e a dele. Na saida
                    # sender e recipient se invertem e esta coluna nao.
                    "conversation_key": item.sender_external_id,
                    "role": MessageRole.LEAD,
                    "direction": MessageDirection.INBOUND,
                    "content_type": item.content_type,
                    "text_body": encrypt(item.text_body, aad_de(identificador, "text_body")),
                    "raw_payload": encrypt_json(
                        item.raw_payload, aad_de(identificador, "raw_payload")
                    ),
                    "status": MessageStatus.RECEIVED,
                }
            )
        statement = (
            pg_insert(Message)
            .values(valores)
            .on_conflict_do_nothing(constraint="uq_messages_channel_provider_message_id")
            .returning(Message.id, Message.provider_message_id)
        )

        async with self._session_factory() as session:
            resultado = await session.execute(statement)
            inseridas = resultado.all()
            await session.commit()

        # Contagem, nao conjunto: o mesmo wamid pode vir repetido dentro de um
        # unico envelope, e ai uma das ocorrencias e gravada e a outra descartada.
        # Com um `set` a segunda sumiria sem log, e a regra do TEC-125 e que todo
        # descarte seja contabilizado.
        recebidos = Counter(item.provider_message_id for item in parsed)
        gravados = Counter(linha.provider_message_id for linha in inseridas)
        for provider_message_id, vezes in recebidos.items():
            for _ in range(vezes - gravados[provider_message_id]):
                log.info(
                    "message.duplicate_discarded",
                    provider_message_id=provider_message_id,
                    channel=channel,
                )

        message_ids = [linha.id for linha in inseridas]
        if message_ids:
            log.info(
                "message.received",
                message_ids=[str(i) for i in message_ids],
                channel=channel,
            )
        # O `RETURNING` ja trazia `provider_message_id` para a contagem de
        # descartes do TEC-125; agora ele tambem e a unica forma de casar cada
        # id gravado com o texto em claro do `ParsedMessage` que o originou --
        # `inseridas` pode ser subconjunto de `parsed`, sem garantia de ordem.
        return [(linha.id, linha.provider_message_id) for linha in inseridas]

    async def _try_enqueue(self, message_id: uuid.UUID, *, atraso_segundos: float = 0.0) -> None:
        if self._queue is None:
            log.warning("enqueue.failed", message_id=str(message_id), reason="no_queue")
            return
        try:
            # `atraso_segundos` vem de `ingest`, que le a config uma vez por
            # lote -- a janela da RN-01.6 entra AQUI e nao no default da fila,
            # porque a ingestao e o unico ponto onde uma rajada pode estar se
            # formando. O sweeper, que e recuperacao, e o opt-out, que fura a
            # janela de proposito, chamam sem atraso e continuam enfileirando
            # para agora.
            await enqueue_process_message(self._queue, message_id, atraso_segundos=atraso_segundos)
        except Exception as exc:
            # `detail=str(exc)` fica: o unico argumento deste job e um UUID que
            # o proprio projeto gerou (`str(message_id)`), entao nao ha entrada
            # externa para a excecao ecoar. O que sobra e texto de nivel de
            # conexao (`Error 111 connecting to ...`), que e o que se quer ler
            # quando a fila cai -- nao ha aqui o vetor que motivou a TEC-292.
            log.warning(
                "enqueue.failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        # O predicado de status importa: entre o enqueue voltar e este commit
        # aterrissar, um worker pode ter reivindicado e concluido a mensagem.
        # Sem ele, o webhook atropelaria PROCESSED de volta para QUEUED.
        #
        # A falha aqui tambem e engolida, e por um motivo mais forte que a do
        # enqueue: neste ponto o `_persist` ja commitou as linhas. Deixar subir
        # viraria 500 na rota e a Meta re-entregaria um payload cujas linhas ja
        # existem. Desde o TEC-125 a UNIQUE (channel, provider_message_id)
        # descartaria essa re-entrega, entao ela nao duplica -- mas tambem nao
        # resolve nada: a linha ja esta em RECEIVED e o sweeper a recupera sem
        # precisar de nada da Meta. O 500 so custaria retentativa a toa.
        try:
            async with self._session_factory() as session:
                # O `execute` de um UPDATE devolve um CursorResult em runtime, mas
                # a tipagem do SQLAlchemy declara o Result generico, sem `rowcount`.
                resultado = cast(
                    CursorResult[Any],
                    await session.execute(
                        update(Message)
                        .where(
                            Message.id == message_id,
                            Message.status == MessageStatus.RECEIVED,
                        )
                        .values(status=MessageStatus.QUEUED, queued_at=datetime.now(UTC))
                    ),
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "queued_flag.failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=motivo_do_erro_de_banco(exc),
            )
            return

        if resultado.rowcount == 1:
            log.info("message.queued", message_id=str(message_id))
        else:
            log.info(
                "message.queued_skipped",
                message_id=str(message_id),
                reason="status_ja_avancou",
            )

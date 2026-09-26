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
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.limites.eventos import registrar_bloqueio
from mobia.domain.limites.models import ESCOPO_NUMERO
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.models import MidiaRecebida
from mobia.domain.midia.repositorio import linha_pendente
from mobia.domain.optout.deteccao import pediu_optout
from mobia.infra.crypto import aad_de, encrypt, encrypt_json
from mobia.infra.db import motivo_do_erro_de_banco
from mobia.infra.queue import enqueue_baixar_midia, enqueue_process_message
from mobia.infra.rate_limit import JANELA_DE_UM_MINUTO, chave_de_numero, consumir

log = structlog.get_logger(__name__)


class IngestionService:
    """Persiste a mensagem recebida e so entao a enfileira.

    A ordem importa: a linha commitada no Postgres e a garantia de nao-perda.
    Depois do `_persist`, o enqueue do turno e a virada de status continuam
    otimistas -- a mensagem fica em RECEIVED e o sweeper
    (workers/jobs/sweep_stalled.py) a recupera -- mas nenhum dos dois engole
    toda excecao. Desde a TEC-132 ha um TERCEIRO passo do mesmo tipo:
    `_try_enqueue_midia`, chamado depois do enqueue do turno para toda
    mensagem de imagem ou documento com linha PENDENTE em `midias_recebidas`.
    Mesma forma -- falha no enqueue vira `log.warning` e nao impede nada -- e
    mesma rede de seguranca, so que outra: aqui quem recupera o que se perder
    e `sweep_midias_pendentes` (workers/jobs/sweep_midias_pendentes.py), nao o
    sweeper de mensagens.

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

        # TEC-203. A chave do lead no lugar do remetente, em toda parte:
        # coluna, rate limit, log e evento. O remetente cru so existe aqui, na
        # memoria, e na identidade cifrada que `_persist` grava.
        chave_de_remetente = {
            item.provider_message_id: chave_de(channel, item.sender_external_id) for item in parsed
        }
        gravadas = await self._persist(parsed, channel, chave_de_remetente)
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
        for message_id, provider_message_id, tem_midia in gravadas:
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
                chave=chave_de_numero(channel, chave_de_remetente.get(provider_message_id, "")),
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
                    conversation_key=chave_de_remetente.get(provider_message_id, ""),
                    channel=channel,
                    volume=consumo.volume,
                    limite=limite,
                )
                await registrar_bloqueio(
                    self._session_factory,
                    self._queue,
                    escopo=ESCOPO_NUMERO,
                    chave=chave_de_remetente.get(provider_message_id, ""),
                    channel=channel,
                    volume=consumo.volume,
                    limite=limite,
                    message_id=message_id,
                )

            await self._try_enqueue(message_id, atraso_segundos=atraso)
            if tem_midia:
                await self._try_enqueue_midia(message_id)
        return [message_id for message_id, _, _ in gravadas]

    async def _persist(
        self, parsed: list[ParsedMessage], channel: str, chave_de_remetente: dict[str, str]
    ) -> list[tuple[uuid.UUID, str, bool]]:
        """Grava as mensagens novas e descarta as que ja tinham chegado.

        "Ja tinham chegado" e a reentrega da Meta, e desde a TEC-124 tambem o
        reenvio do widget depois de uma queda -- os dois com o mesmo
        `provider_message_id`, que no web e o id que a pagina gerou.

        O descarte e resolvido pelo `ON CONFLICT` do proprio Postgres, nao por
        uma checagem em memoria: duas replicas da API recebendo a mesma reentrega
        ao mesmo tempo so podem ser separadas pela constraint (TEC-125). O
        `DO NOTHING` tambem impede que uma duplicata no meio do lote derrube as
        mensagens legitimas que vieram junto.

        Desde a TEC-132, a mensagem de imagem/documento tambem grava a linha
        PENDENTE em `midias_recebidas`, NA MESMA transacao e antes do commit:
        uma mensagem de midia sem a linha correspondente seria uma midia que
        nenhuma varredura (`pendentes_para_reenfileirar`) encontra. O
        `on_conflict_do_nothing` aqui e pela mesma razao do de `messages` --
        reentrega nao pode tentar gravar a mesma PK duas vezes.
        """
        valores = []
        for item in parsed:
            identificador = uuid.uuid4()
            valores.append(
                {
                    "id": identificador,
                    "channel": channel,
                    "provider_message_id": item.provider_message_id,
                    "sender_external_id": chave_de_remetente[item.provider_message_id],
                    "recipient_external_id": item.recipient_external_id,
                    # Quem fala e o lead, entao a conversa e a dele. Na saida
                    # sender e recipient se invertem e esta coluna nao.
                    "conversation_key": chave_de_remetente[item.provider_message_id],
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
            # A identidade entra na mesma transacao das mensagens: chave gravada
            # sem identidade seria um lead a quem nao se consegue responder.
            # Ordem fixa: duas replicas travando as mesmas identidades em
            # ordens diferentes (a de um `set`) podem entrar em deadlock.
            for remetente in sorted({item.sender_external_id for item in parsed}):
                await registrar(session, channel, remetente)

            resultado = await session.execute(statement)
            inseridas = resultado.all()

            # Mesma convencao de `texto_de`/`chave_de_remetente` em `ingest`: o
            # `provider_message_id` repetido dentro do MESMO envelope resolve
            # para a ULTIMA ocorrencia, inofensivo pelo mesmo motivo (reentrega
            # da Meta nunca traz corpos diferentes para o mesmo wamid).
            item_de = {item.provider_message_id: item for item in parsed}
            midia_valores = []
            for linha in inseridas:
                correspondente = item_de.get(linha.provider_message_id)
                if correspondente is None:
                    continue
                midia = linha_pendente(
                    linha.id, correspondente.raw_payload, correspondente.content_type
                )
                if midia is not None:
                    midia_valores.append(midia)

            if midia_valores:
                await session.execute(
                    pg_insert(MidiaRecebida).values(midia_valores).on_conflict_do_nothing()
                )

            await session.commit()

        ids_com_midia = {midia["message_id"] for midia in midia_valores}

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
        # O terceiro elemento (TEC-132) e quem decide, ja em `ingest`, se aquele
        # id precisa tambem do `_try_enqueue_midia`.
        return [
            (linha.id, linha.provider_message_id, linha.id in ids_com_midia) for linha in inseridas
        ]

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

    async def _try_enqueue_midia(self, message_id: uuid.UUID) -> None:
        """Enfileira `baixar_midia` para uma mensagem que ja tem linha PENDENTE.

        Engole toda falha, no mesmo espirito de `_try_enqueue`: a linha em
        `midias_recebidas` ja foi commitada por `_persist`, e a varredura de
        pendentes (Task 5) reenfileira o que se perder aqui. Falha no enqueue
        da midia nunca pode impedir o `process_message` -- por isso este
        metodo e chamado DEPOIS dele, nao antes nem no lugar.
        """
        if self._queue is None:
            log.warning("midia.enqueue_failed", message_id=str(message_id), reason="no_queue")
            return
        try:
            await enqueue_baixar_midia(self._queue, message_id)
        except Exception as exc:
            log.warning(
                "midia.enqueue_failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
            )

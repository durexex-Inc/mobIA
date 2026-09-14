import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text as sql

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel, GuardedOutbound
from mobia.infra.db import get_sessionmaker

KIND = "reply"


class OutboundQueFalha(GuardedOutbound):
    """Falha as primeiras `falhas` tentativas, depois entrega."""

    def __init__(self, session_factory, erro: Exception, falhas: int = 1) -> None:
        super().__init__(session_factory)
        self._erro = erro
        self._falhas = falhas
        self.entregues: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        if self._falhas > 0:
            self._falhas -= 1
            raise self._erro
        self.entregues.append(message_id)


async def uma_mensagem(session) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel="whatsapp",
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key="5511911112222",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()
    return identificador


class OutboundLiberacaoFalha(OutboundQueFalha):
    """Simula o delete da liberacao explodindo -- deadlock, conexao caida etc."""

    async def _liberar(self, message_id: uuid.UUID, kind: str) -> None:
        raise RuntimeError("conexao caiu no meio do delete de liberacao")


class OutboundQueEstoura(GuardedOutbound):
    """Deixa escapar uma excecao crua, sem passar por EnvioRetentavel/EnvioRecusado."""

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("provider explodiu sem dizer se vale retentar")


async def reservas(session, message_id: uuid.UUID) -> int:
    return await session.scalar(
        sql("SELECT count(*) FROM outbound_dispatches WHERE message_id = :m"),
        {"m": message_id},
    )


async def reservas_por_kind(session, message_id: uuid.UUID, kind: str) -> int:
    return await session.scalar(
        sql("SELECT count(*) FROM outbound_dispatches WHERE message_id = :m AND kind = :k"),
        {"m": message_id, "k": kind},
    )


async def test_falha_retentavel_libera_a_reserva(session) -> None:
    """Sem isso, a resposta ao lead se perde em silencio e para sempre.

    A reserva ja esta commitada quando o envio falha, entao o sweeper
    reenfileira, o worker reivindica, e a guarda responde "ja entreguei isso".
    A Marina nunca recebe nada sobre aquele turno.
    """
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await reservas(session, message_id) == 0, "a reserva tem de sair do caminho"


async def test_apos_liberar_a_retentativa_entrega(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await outbound.send(message_id, KIND, {}) is True
    assert outbound.entregues == [message_id]


async def test_falha_permanente_mantem_a_reserva(session) -> None:
    """4xx nao volta a dar certo. Retentar so queima chamada de modelo."""
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRecusado("payload invalido"))

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRecusado:
        pass

    assert await reservas(session, message_id) == 1


async def test_apos_falha_permanente_a_retentativa_e_no_op(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRecusado("payload invalido"), falhas=1)

    try:
        await outbound.send(message_id, KIND, {})
    except EnvioRecusado:
        pass

    assert await outbound.send(message_id, KIND, {}) is False
    assert outbound.entregues == [], "a guarda suprimiu, nada foi entregue"


async def test_entrega_bem_sucedida_mantem_a_reserva(session) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)

    assert await outbound.send(message_id, KIND, {}) is True
    assert await reservas(session, message_id) == 1


async def test_falha_ao_liberar_nao_mascara_o_erro_original(session, caplog) -> None:
    """Se o delete da liberacao falhar, quem chama send() ainda ve EnvioRetentavel.

    Nao um erro de infra do release. Do contrario um retentavel vira
    permanente por engano e a reserva fica presa do mesmo jeito que a
    liberacao existe para evitar.
    """
    message_id = await uma_mensagem(session)
    outbound = OutboundLiberacaoFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    raised: Exception | None = None
    with caplog.at_level("ERROR"):
        try:
            await outbound.send(message_id, KIND, {})
        except Exception as exc:
            raised = exc

    assert isinstance(raised, EnvioRetentavel), f"esperava EnvioRetentavel, veio {raised!r}"
    assert "outbound.liberacao_falhou" in caplog.text
    # Sem o tipo no evento, um TypeError daqui de dentro fica indistinguivel
    # de um deadlock do banco -- nao ha nada de que depurar.
    assert "RuntimeError" in caplog.text


async def test_liberar_nao_arrasta_kind_de_outro_grupo(session) -> None:
    """O `IN (grupo)` e o que impede um reply liberado de arrastar o ack junto.

    Era `AND kind = :k` ate a TEC-273. O que mudou foi o recorte, nao a
    garantia: `ack` nao pertence a grupo nenhum, entao continua de pe.
    """
    message_id = await uma_mensagem(session)
    ack_outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)
    assert await ack_outbound.send(message_id, "ack", {}) is True

    reply_outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))
    try:
        await reply_outbound.send(message_id, KIND, {})
    except EnvioRetentavel:
        pass

    assert await reservas_por_kind(session, message_id, "ack") == 1, "a reserva do ack sobrevive"
    assert await reservas_por_kind(session, message_id, KIND) == 0


async def test_falha_retentavel_loga_reserva_liberada(session, caplog) -> None:
    message_id = await uma_mensagem(session)
    outbound = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("timeout"))

    with caplog.at_level("WARNING"):
        try:
            await outbound.send(message_id, KIND, {})
        except EnvioRetentavel:
            pass

    assert "outbound.reserva_liberada" in caplog.text


async def test_excecao_nao_mapeada_mantem_a_reserva(session) -> None:
    """O release so age em EnvioRetentavel -- uma excecao crua e caminho permanente.

    Isso deixa o contrato explicito: um adapter que nao embrulhar suas falhas
    em EnvioRetentavel/EnvioRecusado reabre o silencio que esta task fecha.
    """
    message_id = await uma_mensagem(session)
    outbound = OutboundQueEstoura(get_sessionmaker())

    try:
        await outbound.send(message_id, KIND, {})
    except RuntimeError:
        pass

    assert await reservas(session, message_id) == 1


async def test_liberar_apaga_a_reserva_da_parte_irma(session) -> None:
    """TEC-273. A parte 1 entregue perde a reserva quando a parte 2 falha.

    Sem isto, a retentativa do sweeper reentrega so a parte 2 -- com o texto
    de uma chamada NOVA ao modelo --, e o lead le a primeira metade de um
    texto colada na segunda metade de outro. Corrupcao silenciosa: ele nao
    tem como saber que leu duas fontes, e nada no sistema diz.
    """
    from mobia.domain.outbound.kinds import KINDS_DA_RESPOSTA

    message_id = await uma_mensagem(session)

    parte_1 = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)
    assert await parte_1.send(message_id, KINDS_DA_RESPOSTA[0], {}) is True
    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[0]) == 1

    parte_2 = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("http 429"))
    try:
        await parte_2.send(message_id, KINDS_DA_RESPOSTA[1], {})
    except EnvioRetentavel:
        pass

    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[1]) == 0
    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[0]) == 0, (
        "a reserva da parte JA ENTREGUE tem de cair junto -- e ela que faria a "
        "retentativa suprimir a parte 1 da geracao nova"
    )


class OutboundTravaNaSegundaParte(GuardedOutbound):
    """Reserva a parte 2, entra no `_deliver` dela e nunca sai.

    Precisa de um cancelamento de VERDADE (`tarefa.cancel()` numa task em
    voo), nao de um `raise asyncio.CancelledError()` direto -- e o mesmo
    ponto que `test_cancelamento_do_worker.py` ja registra: um cancelamento
    fabricado nao passa pelos mesmos pontos de suspensao do asyncio que o
    `except (EnvioRetentavel, asyncio.CancelledError)` de `GuardedOutbound.send`
    de fato intercepta em producao (`job_timeout` do worker, shutdown).
    """

    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entrou = asyncio.Event()

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entrou.set()
        await asyncio.Event().wait()


async def test_cancelamento_libera_a_reserva_da_parte_irma(session) -> None:
    """TEC-273, D3. Um CancelledError no meio da parte 2 libera a reserva da
    parte 1 tambem -- a mesma garantia que
    `test_liberar_apaga_a_reserva_da_parte_irma` ja prova para EnvioRetentavel,
    agora para o outro gatilho que passa pela MESMA clausula `except` em
    `GuardedOutbound.send`.

    O comentario daquela clausula diz que o que fazer e identico para as duas
    excecoes, e que duas copias divergiriam -- mas nada ali IMPEDE que
    divirjam de fato: um teste que so cobrisse EnvioRetentavel deixaria a
    metade do cancelamento sem fiador algum. Se `_liberar` regredisse para
    apagar so o kind que cancelou (a versao anterior a TEC-273, `AND kind =
    :k`), a reserva da parte 1 -- ja entregue -- sobreviveria, e a proxima
    retentativa do sweeper suprimiria a parte 1 da geracao nova e entregaria
    so a parte 2: a mesma corrupcao silenciosa que esta card fecha para o
    caminho retentavel, agora pelo caminho do cancelamento.

    `asyncio.CancelledError` e `BaseException`, nao `Exception` -- por isso
    `pytest.raises(asyncio.CancelledError)`, e nao um `except Exception` no
    corpo do teste, que simplesmente nao o capturaria.
    """
    from mobia.domain.outbound.kinds import KINDS_DA_RESPOSTA

    message_id = await uma_mensagem(session)

    parte_1 = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)
    assert await parte_1.send(message_id, KINDS_DA_RESPOSTA[0], {}) is True
    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[0]) == 1

    travado = OutboundTravaNaSegundaParte(get_sessionmaker())
    tarefa = asyncio.create_task(travado.send(message_id, KINDS_DA_RESPOSTA[1], {}))
    await travado.entrou.wait()
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[1]) == 0
    assert await reservas_por_kind(session, message_id, KINDS_DA_RESPOSTA[0]) == 0, (
        "o cancelamento tem de liberar o GRUPO, igual ao EnvioRetentavel -- "
        "senao a parte 1 ja entregue fica presa e a proxima retentativa mistura geracoes"
    )


async def test_liberar_uma_ficha_nao_arrasta_as_outras(session) -> None:
    """TEC-273, fronteira com a TEC-275. As fichas NAO formam grupo.

    A retentativa de uma apresentacao repete o lote persistido em vez de
    chamar o modelo, entao nao ha geracoes para misturar -- e a reserva de
    cada ficha e o sinal de que `_continuar_entrega` depende para saber o que
    ja saiu. Se alguem "simplificar" a liberacao para o `message_id` inteiro,
    este teste cai, e a continuacao da TEC-275 deixaria de ser tomada em
    silencio.
    """
    message_id = await uma_mensagem(session)

    entregue = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("nunca"), falhas=0)
    assert await entregue.send(message_id, "ficha_1", {}) is True

    falha = OutboundQueFalha(get_sessionmaker(), EnvioRetentavel("http 503"))
    try:
        await falha.send(message_id, "ficha_2", {})
    except EnvioRetentavel:
        pass

    assert await reservas_por_kind(session, message_id, "ficha_1") == 1, (
        "a reserva da ficha entregue tem de SOBREVIVER -- e ela que diz a "
        "continuacao da TEC-275 que aquela ficha ja chegou ao lead"
    )
    assert await reservas_por_kind(session, message_id, "ficha_2") == 0

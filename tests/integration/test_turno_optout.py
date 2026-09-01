"""O turno detecta o pedido de opt-out, grava e confirma (TEC-182 Task 5).

Reusa a mesma montagem de `executar_turno` que `tests/integration/test_turno.py`
ja faz -- os dubles (classificador, resumidor, contador, outbound, moderador)
vem das mesmas fixtures de `tests/conftest.py`. So a mensagem semeada muda:
aqui o texto do lead precisa ser controlado (a frase de opt-out, ou nao), e por
isso este arquivo tem seu proprio helper de semeadura em vez de reusar
`_entrada_do_lead`, que fixa o texto.
"""

import logging
import uuid
from typing import Any

import pytest
from conftest import ModeradorFake, OutboundFake
from sqlalchemy import func, select

from mobia.domain.agente.turno import KIND_DA_RESPOSTA, executar_turno
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
from mobia.infra.crypto import aad_de, decrypt, encrypt
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _mensagem_gravada(session, *, texto: str) -> Message:
    """Uma mensagem INBOUND com corpo cifrado, pronta para `executar_turno`.

    Espelha `_entrada_do_lead` de `tests/conftest.py`, mas com o texto
    parametrizado -- os testes de opt-out precisam controlar exatamente o que
    o lead escreveu (a frase de opt-out, ou uma fala qualquer).
    """
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=CONVERSA,
        recipient_external_id="222222222",
        conversation_key=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    return linha


async def _mensagem_sem_texto_gravada(session, *, content_type: MessageContentType) -> Message:
    """Uma mensagem INBOUND sem corpo (imagem ou audio), `text_body=None`.

    Existe so para provar que o silencio de quem ja pediu opt-out nao depende
    da mensagem ter texto -- ver a checagem `esta_em_optout` fora do
    `if corpo:` em `executar_turno`.
    """
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=CONVERSA,
        recipient_external_id="222222222",
        conversation_key=CONVERSA,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=content_type,
        text_body=None,
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    return linha


async def test_pedido_de_optout_grava_confirma_e_nao_paga_o_modelo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """O turno inteiro e economizado: nenhuma chamada ao classificador, e
    tambem nenhuma chamada de moderacao (fix da revisao -- a checagem de
    opt-out roda ANTES do bloco de moderacao de entrada, nao depois).

    E o mesmo motivo que poe a moderacao de entrada antes de montar contexto --
    bloquear cedo economiza o turno pago inteiro.
    """
    mensagem = await _mensagem_gravada(session, texto="parar")
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake()

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=moderador,
    )

    assert resultado == "opt_out"
    assert classificador.chamadas == 0
    assert moderador.entradas == 0, "opt-out e checado antes da moderacao -- ela nem roda"
    # `OutboundFake._deliver` grava o texto entregue (payload["texto"]), nao o
    # kind -- e o texto que confirma o registro ao lead.
    assert outbound.entregues == [TEXTO_DA_CONFIRMACAO_DE_OPTOUT]
    assert await esta_em_optout(
        session, channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )

    # RN-14.4, e a unica asserta que prova a evidencia: a confirmacao entregue
    # tem de virar linha de AGENTE em `messages`, como qualquer outra fala
    # nossa. Sem isto, o historico do lead fecha com o pedido dele e nada
    # depois -- e quem auditar o registro de conformidade nao acha o texto que
    # foi de fato entregue, so o evento em `optout_events`.
    faladas = (
        (await session.execute(select(Message).where(Message.role == MessageRole.AGENTE)))
        .scalars()
        .all()
    )
    textos = [decrypt(linha.text_body, aad_de(linha.id, "text_body")) for linha in faladas]
    assert textos == [TEXTO_DA_CONFIRMACAO_DE_OPTOUT]


async def test_pedido_de_optout_e_registrado_mesmo_com_entrada_bloqueada_pela_moderacao(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """CRITICAL da revisao: o registro de opt-out nao pode depender da
    moderacao aprovar a mensagem que o carrega.

    O bloco de moderacao de entrada tem `return` proprio. Se o bloco de
    opt-out rodasse depois dele (como estava antes deste fix), uma mensagem
    que e AO MESMO TEMPO um pedido de opt-out e algo que a moderacao reprova
    -- por exemplo "pare de mandar mensagem" com um xingamento junto -- nunca
    chegaria ao registro: a moderacao bloquearia e devolveria a recusa de
    entrada primeiro, e continuariamos mandando mensagem (a propria recusa)
    para quem pediu para sair. E a violacao que a D5 existe para evitar,
    entrando por outra porta. Este teste usa `bloqueia_entrada=True` para
    forcar exatamente esse cenario e provar que o opt-out ainda e registrado.
    """
    mensagem = await _mensagem_gravada(session, texto="pare de mandar mensagem, seu golpista")
    classificador = classificador_fake()
    outbound = outbound_fake()
    moderador = moderador_fake(bloqueia_entrada=True)

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=moderador,
    )

    assert resultado == "opt_out"
    assert moderador.entradas == 0, "o opt-out e checado antes -- a moderacao nunca roda"
    assert outbound.entregues == [TEXTO_DA_CONFIRMACAO_DE_OPTOUT]
    assert await esta_em_optout(
        session, channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )


async def test_lead_ja_silenciado_nao_recebe_nada_e_nao_paga(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A segunda mensagem de quem ja pediu para sair.

    D1: silencio total. Ele nao recebe resposta nem quando escreve primeiro.
    RN-14.4 (fix de revisao -- Important 3, movido para ca do teste que
    afirmava isso sem verificar): opt-out nao apaga historico nem para a
    ingestao -- a fala do lead ja silenciado continua gravada. `total == 1`
    prova que a linha, ja commitada antes do turno rodar (como a ingestao
    real faz), sobrevive ao turno que devolve "silenciado" -- nenhuma
    reescrita, nenhum apagamento.
    """
    await registrar_optout(
        get_sessionmaker(), channel=CANAL, conversation_key=CONVERSA, message_id=uuid.uuid4()
    )
    mensagem = await _mensagem_gravada(session, texto="mas eu queria ver um apartamento")
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=ModeradorFake(),
    )

    assert resultado == "silenciado"
    assert classificador.chamadas == 0
    assert outbound.entregues == []

    total = (await session.execute(select(func.count()).select_from(Message))).scalar_one()
    assert total == 1, "a fala do lead ja silenciado continua gravada -- nada some"
    ainda_la = await session.get(Message, mensagem.id)
    assert ainda_la is not None


async def test_mensagem_sem_texto_de_lead_silenciado_tambem_fica_em_silencio(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """IMPORTANT da revisao: a checagem de silencio fica FORA do `if corpo:`
    de proposito, e nenhum dos outros testes deste arquivo prova isso -- todos
    semeiam mensagem com corpo de texto, entao mover a checagem para DENTRO do
    `if corpo:` nao quebraria nenhum deles.

    O silencio e sobre o LEAD (o par channel/conversation_key), nao sobre a
    mensagem ter texto: uma imagem ou audio de quem ja pediu opt-out tambem
    nao pode receber resposta. `text_body=None` aqui simula exatamente isso.
    """
    await registrar_optout(
        get_sessionmaker(), channel=CANAL, conversation_key=CONVERSA, message_id=uuid.uuid4()
    )
    mensagem = await _mensagem_sem_texto_gravada(session, content_type=MessageContentType.AUDIO)
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=ModeradorFake(),
    )

    assert resultado == "silenciado"
    assert classificador.chamadas == 0
    assert outbound.entregues == []


async def test_optout_gravado_mesmo_quando_a_confirmacao_nao_sai(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """D5: grava antes de entregar, e a direcao do erro decide.

    Com o outbound recusando (EnvioRecusado), o lead fica sem confirmacao --
    ruim e conforme. Se a ordem fosse a inversa, teriamos opt-out nao
    registrado e continuariamos mandando mensagem, que e a violacao.
    """
    mensagem = await _mensagem_gravada(session, texto="descadastrar")

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(EnvioRecusado("400")),
        moderador=ModeradorFake(),
    )

    assert resultado == "sem_resposta"
    assert await esta_em_optout(
        session, channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )


async def test_confirmacao_e_reentregue_depois_de_uma_falha_retentavel(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """IMPORTANT da revisao final: a confirmacao NAO pode se perder para
    sempre num 5xx da Meta.

    Turno 1 grava o OPT_OUT e `_deliver` levanta `EnvioRetentavel`. A guarda
    libera a reserva (para a proxima tentativa poder entregar) e propaga: a
    linha vira FAILED e o sweeper reenfileira a MESMA mensagem. Antes do fix, o
    turno 2 batia no `esta_em_optout` incondicional do topo de
    `executar_turno`, devolvia "silenciado" e fechava em PROCESSED -- terminal
    -- e o lead nunca recebia a confirmacao de que o pedido dele foi atendido.

    A D5 aceitou "sem confirmacao" para as saidas TERMINAIS de
    `_entregar_texto_fixo`; falha retentavel nao e nenhuma delas. O fix e o
    `not pedido_de_optout` no short-circuit do topo: com o pedido em maos, o
    turno segue e reentrega.

    O segundo turno grava um segundo evento OPT_OUT, e isso e de proposito:
    a tabela e append-only e o estado e o ULTIMO evento, entao um OPT_OUT
    repetido nao muda estado nenhum -- e mentir sobre o historico (nao
    registrar a segunda passagem) seria pior que a linha a mais.
    """
    mensagem = await _mensagem_gravada(session, texto="parar")

    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=mensagem,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound_fake(EnvioRetentavel("http 503")),
            moderador=ModeradorFake(),
        )

    assert await esta_em_optout(
        session, channel=mensagem.channel, conversation_key=mensagem.conversation_key
    ), "o opt-out fica gravado mesmo com a confirmacao falhando"

    outbound = outbound_fake()
    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=ModeradorFake(),
    )

    assert resultado == "opt_out", "a retentativa nao pode virar 'silenciado'"
    assert outbound.entregues == [TEXTO_DA_CONFIRMACAO_DE_OPTOUT]


class _OutboundQueOptaNoMeio(OutboundFake):
    """Simula a corrida: outro turno da MESMA conversa termina de registrar o
    opt-out DEPOIS que este turno ja passou pela checagem `esta_em_optout` no
    topo de `executar_turno`, mas ANTES deste `send()`.

    Registrar dentro de `send()` (em vez de `_deliver`) e o ponto certo:
    `GuardedOutbound.send` consulta o opt-out antes da reserva, entao o
    registro precisa existir antes da chamada a `super().send()` para que a
    guarda de fato barre.
    """

    def __init__(self, session_factory: Any, *, channel: str, conversation_key: str) -> None:
        super().__init__(session_factory)
        self._channel = channel
        self._conversation_key = conversation_key

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        await registrar_optout(
            self._session_factory,
            channel=self._channel,
            conversation_key=self._conversation_key,
            message_id=uuid.uuid4(),
        )
        return await super().send(message_id, kind, payload)


async def test_bloqueio_da_guarda_por_optout_nao_vira_reentrega_suprimida(
    session, classificador_fake, resumidor_fake, contador_fake, caplog
) -> None:
    """A guarda (Task 4) barra o envio porque OUTRO turno da mesma conversa
    registrou o opt-out entre a checagem do topo deste turno e este envio.

    A guarda funcionou como desenhada -- nada foi perdido -- entao este
    desfecho nao pode se disfarcar de `reentrega_suprimida`: nem no
    `ResultadoDoTurno`, nem no nivel `error` que o log daquele desfecho usa
    para acordar o alerta de dado sumido. Fix da revisao da Task 4.
    """
    mensagem = await _mensagem_gravada(session, texto="quero saber mais sobre apartamentos")
    outbound = _OutboundQueOptaNoMeio(
        get_sessionmaker(), channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=mensagem,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(),
        )

    assert resultado == "bloqueado_por_optout"
    assert resultado != "reentrega_suprimida"
    assert outbound.entregues == [], "a guarda nunca chega a chamar _deliver"

    eventos_de_perda = [
        registro
        for registro in caplog.records
        if "turno.reentrega_suprimida" in registro.getMessage()
    ]
    assert eventos_de_perda == [], "o desfecho de opt-out nao pode logar a historia de perda"

    eventos_de_erro = [registro for registro in caplog.records if registro.levelno == logging.ERROR]
    assert eventos_de_erro == [], "a guarda funcionando nao e um alarme de error"

    eventos = [
        registro
        for registro in caplog.records
        if "turno.bloqueado_por_optout_concorrente" in registro.getMessage()
    ]
    assert eventos, "o desfecho tem de aparecer no log"
    assert all(registro.levelno == logging.INFO for registro in eventos)


async def test_bloqueio_da_guarda_na_entrada_bloqueada_tambem_nao_vira_reentrega(
    session, resumidor_fake, contador_fake, caplog
) -> None:
    """Mesma corrida, mas no caminho de `_entregar_texto_fixo` com o kind
    default (a recusa de entrada) -- prova que o parametro `kind` novo nao
    quebrou a distincao tambem neste chamador."""
    mensagem = await _mensagem_gravada(session, texto="algo que a moderacao vai bloquear")
    outbound = _OutboundQueOptaNoMeio(
        get_sessionmaker(), channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=mensagem,
            classificador=None,  # type: ignore[arg-type]
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(bloqueia_entrada=True),
        )

    assert resultado == "bloqueado_por_optout"
    assert resultado != "reentrega_suprimida"
    eventos_de_erro = [registro for registro in caplog.records if registro.levelno == logging.ERROR]
    assert not any(
        "turno.reentrega_suprimida" in registro.getMessage() for registro in eventos_de_erro
    )


async def test_confirmacao_de_optout_que_nao_entrega_nunca_vira_bloqueado_por_optout(
    session, classificador_fake, resumidor_fake, contador_fake, caplog
) -> None:
    """IMPORTANT da revisao: no chamador da CONFIRMACAO de opt-out, um `False`
    de `outbound.send` so pode vir de reserva duplicada de verdade -- nunca da
    guarda de opt-out.

    Este turno acabou de rodar `registrar_optout` antes de chegar em
    `_entregar_texto_fixo`, entao `esta_em_optout` devolveria True por
    construcao se fosse consultada aqui -- nao porque a guarda bloqueou desta
    vez, mas porque o proprio opt-out que ESTE turno gravou ainda esta la. E a
    guarda pula a checagem de opt-out para `KIND_DA_CONFIRMACAO_DE_OPTOUT`.
    Simula a reserva duplicada real (Task 3): outra tentativa anterior ja
    reservou o mesmo `(message_id, kind)` em `outbound_dispatches` antes deste
    turno rodar -- o cenario que `test_reentrega_suprimida_nao_grava_fala_fantasma`
    (test_turno.py) usa para o caminho principal, replicado aqui para o
    caminho de opt-out.
    """
    from mobia.domain.optout.deteccao import KIND_DA_CONFIRMACAO_DE_OPTOUT
    from mobia.domain.outbound.models import OutboundDispatch

    mensagem = await _mensagem_gravada(session, texto="parar")
    session.add(
        OutboundDispatch(
            id=uuid.uuid4(), message_id=mensagem.id, kind=KIND_DA_CONFIRMACAO_DE_OPTOUT
        )
    )
    await session.commit()
    outbound = OutboundFake(get_sessionmaker())

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=mensagem,
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(),
        )

    assert resultado == "reentrega_suprimida", (
        "reserva duplicada de verdade -- nao pode se disfarcar de bloqueado_por_optout"
    )
    eventos_de_erro = [
        registro
        for registro in caplog.records
        if "turno.reentrega_suprimida" in registro.getMessage()
    ]
    assert eventos_de_erro and all(r.levelno == logging.ERROR for r in eventos_de_erro), (
        "o alarme de dado sumido nao pode ser engolido pela checagem de opt-out"
    )
    # O opt-out em si foi registrado (aconteceu antes da tentativa de envio):
    # so a confirmacao nao saiu.
    assert await esta_em_optout(
        session, channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )


async def test_kind_da_entrega_de_texto_fixo_continua_reply_por_default(
    session, resumidor_fake, contador_fake
) -> None:
    """O default de `_entregar_texto_fixo` preserva os chamadores existentes:
    a recusa de entrada usa `KIND_DA_RESPOSTA`, nao um kind novo."""
    mensagem = await _mensagem_gravada(session, texto="qualquer coisa")

    class _OutboundQueRegistraKind(OutboundFake):
        def __init__(self, session_factory: Any) -> None:
            super().__init__(session_factory)
            self.kinds: list[str] = []

        async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
            self.kinds.append(kind)
            await super()._deliver(message_id, kind, payload)

    outbound = _OutboundQueRegistraKind(get_sessionmaker())

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=None,  # type: ignore[arg-type]
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=ModeradorFake(bloqueia_entrada=True),
    )

    assert resultado == "respondido"
    assert outbound.kinds == [KIND_DA_RESPOSTA]

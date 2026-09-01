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

from conftest import ModeradorFake, OutboundFake
from sqlalchemy import func, select

from mobia.domain.agente.turno import KIND_DA_RESPOSTA, executar_turno
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.port import EnvioRecusado
from mobia.infra.crypto import aad_de, encrypt
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


async def test_pedido_de_optout_grava_confirma_e_nao_paga_o_modelo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O turno inteiro e economizado: nenhuma chamada ao classificador.

    E o mesmo motivo que poe a moderacao de entrada antes de montar contexto --
    bloquear cedo economiza o turno pago inteiro.
    """
    mensagem = await _mensagem_gravada(session, texto="parar")
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

    assert resultado == "opt_out"
    assert classificador.chamadas == 0
    # `OutboundFake._deliver` grava o texto entregue (payload["texto"]), nao o
    # kind -- e o texto que confirma o registro ao lead.
    assert outbound.entregues == [TEXTO_DA_CONFIRMACAO_DE_OPTOUT]
    assert await esta_em_optout(
        session, channel=mensagem.channel, conversation_key=mensagem.conversation_key
    )


async def test_lead_ja_silenciado_nao_recebe_nada_e_nao_paga(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A segunda mensagem de quem ja pediu para sair.

    D1: silencio total. Ele nao recebe resposta nem quando escreve primeiro.
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


async def test_a_mensagem_do_lead_silenciado_continua_gravada(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """RN-14.4: opt-out nao apaga historico, e nao para a ingestao.

    A fala do lead que disparou o opt-out ja estava gravada antes do turno
    rodar (a ingestao grava antes do worker existir, como em todo turno) -- e
    continua la depois. A confirmacao que o turno entrega tambem vira linha.
    Duas mensagens no total: nenhuma sumiu.
    """
    mensagem = await _mensagem_gravada(session, texto="parar")

    resultado = await executar_turno(
        get_sessionmaker(),
        message=mensagem,
        classificador=classificador_fake(),
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound_fake(),
        moderador=ModeradorFake(),
    )

    assert resultado == "opt_out"
    total = (await session.execute(select(func.count()).select_from(Message))).scalar_one()
    assert total == 2, "a fala do lead e a confirmacao ficam gravadas, nenhuma some"


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

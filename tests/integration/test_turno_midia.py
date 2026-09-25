"""A midia sem texto recebe confirmacao fixa, sem modelo (TEC-132, D4).

Mesma montagem de `executar_turno` que `test_turno_optout.py` usa -- os dubles
vem de `tests/conftest.py`. A mensagem de midia e gravada direto, como a
ingestao grava: `content_type` IMAGEM ou DOCUMENTO e `text_body` nulo quando
nao ha legenda.

O que se prova: a confirmacao sai sem chamar o classificador, com kind e
subagente proprios; ela NAO sai para quem pediu silencio (opt-out, atendimento
humano); e havendo texto do lead -- na legenda ou numa irma pendente da
rajada -- o turno normal roda.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select, update

from mobia.domain.agendamento.agendador import AgendadorDeConfirmacaoNoop
from mobia.domain.agente.identificacao import (
    SEPARADOR_DA_IDENTIFICACAO,
    TEXTO_DA_IDENTIFICACAO,
)
from mobia.domain.agente.turno import executar_turno
from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.confirmacao import (
    KIND_DA_CONFIRMACAO_DE_MIDIA,
    SUBAGENTE_MIDIA,
    TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO,
    TEXTO_DA_CONFIRMACAO_DE_IMAGEM,
)
from mobia.domain.optout.repositorio import registrar_optout
from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA
from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911113333"


async def _gravar(
    session, *, content_type: str = MessageContentType.TEXTO, texto: str | None
) -> Message:
    """Uma INBOUND do lead; `texto=None` e a midia sem legenda.

    Cada chamada commita a sua, entao `created_at` (o `now()` da transacao)
    sai em ordem -- e o que a rajada com texto precisa.
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
        text_body=None if texto is None else encrypt(texto, aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    return linha


async def _rodar(message, classificador, outbound, resumidor_fake, contador_fake, moderador_fake):
    return await executar_turno(
        get_sessionmaker(),
        message=message,
        classificador=classificador,
        resumidor=resumidor_fake(),
        contador=contador_fake(),
        outbound=outbound,
        moderador=moderador_fake(),
        agendador=AgendadorNoop(),
        agendador_de_confirmacao=AgendadorDeConfirmacaoNoop(),
    )


async def _kinds(session, message_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.scalars(
                select(OutboundDispatch.kind).where(OutboundDispatch.message_id == message_id)
            )
        ).all()
    )


async def test_imagem_sem_legenda_recebe_texto_fixo_sem_chamar_o_modelo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    imagem = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        imagem, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 0
    # Primeiro contato: `_entregar_texto_fixo` prefixa a identificacao, e o
    # esperado e montado do mesmo jeito que ele monta.
    assert outbound.entregues == [
        f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{TEXTO_DA_CONFIRMACAO_DE_IMAGEM}"
    ]
    assert await _kinds(session, imagem.id) == [KIND_DA_CONFIRMACAO_DE_MIDIA]
    subagentes = (await session.scalars(select(MessageTelemetry.subagent))).all()
    assert subagentes == [SUBAGENTE_MIDIA]


async def test_documento_sem_legenda_recebe_o_texto_de_documento(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    documento = await _gravar(session, content_type=MessageContentType.DOCUMENTO, texto=None)
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        documento, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 0
    assert len(outbound.entregues) == 1
    assert outbound.entregues[0].endswith(TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO)
    assert await _kinds(session, documento.id) == [KIND_DA_CONFIRMACAO_DE_MIDIA]


async def test_optout_nao_recebe_confirmacao_de_midia(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Quem pediu silencio nao recebe "recebi sua imagem"."""
    await registrar_optout(
        get_sessionmaker(), channel=CANAL, conversation_key=CONVERSA, message_id=uuid.uuid4()
    )
    imagem = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        imagem, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "silenciado"
    assert outbound.entregues == []
    assert classificador.chamadas == 0


async def test_atendimento_humano_silencia_a_confirmacao(
    session,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    semear_corretor,
) -> None:
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(session, channel=CANAL, conversation_key=CONVERSA, corretor_id=corretor.id)
    await session.commit()
    imagem = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        imagem, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "atendimento_humano"
    assert outbound.entregues == []
    assert classificador.chamadas == 0


async def test_rajada_com_texto_roda_o_turno_normal(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """O "quero esse" + foto: o debounce roda o turno na foto, e o texto fixo
    ali deixaria o "quero esse" sem resposta."""
    await _gravar(session, texto="quero esse")
    imagem = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    classificador = classificador_fake()
    outbound = outbound_fake()

    await _rodar(imagem, classificador, outbound, resumidor_fake, contador_fake, moderador_fake)

    assert classificador.chamadas == 1
    assert not any(TEXTO_DA_CONFIRMACAO_DE_IMAGEM in texto for texto in outbound.entregues)
    assert KIND_DA_CONFIRMACAO_DE_MIDIA not in await _kinds(session, imagem.id)


async def test_imagem_com_legenda_roda_o_turno_normal(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    imagem = await _gravar(
        session, content_type=MessageContentType.IMAGEM, texto="esse aqui ta disponivel?"
    )
    classificador = classificador_fake()
    outbound = outbound_fake()

    await _rodar(imagem, classificador, outbound, resumidor_fake, contador_fake, moderador_fake)

    assert classificador.chamadas == 1
    assert not any(TEXTO_DA_CONFIRMACAO_DE_IMAGEM in texto for texto in outbound.entregues)
    assert KIND_DA_CONFIRMACAO_DE_MIDIA not in await _kinds(session, imagem.id)


async def test_retentativa_depois_do_turno_normal_nao_manda_a_confirmacao(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Fix round 1. "quero esse" + foto, e a passada 1 ja respondeu pelo turno
    normal -- reserva de `reply` na foto e fala OUTBOUND gravada -- mas o
    worker morreu antes de PROCESSED. Na retentativa, a fala do agente vira a
    fronteira de `ha_fala_pendente_antes` e o "quero esse" deixa de estar
    pendente; sem a checagem de kinds reservados, o turno tomaria o caminho
    fixo e mandaria "Recebi sua imagem!" depois de o agente ja ter respondido.
    Mesma classe da TEC-298, D1.
    """
    await _gravar(session, texto="quero esse")
    imagem = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=imagem.id, kind=KIND_DA_RESPOSTA))
    await session.commit()
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id="222222222",
            recipient_external_id=CONVERSA,
            conversation_key=CONVERSA,
            role=MessageRole.AGENTE,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("Temos sim! Te mando as opcoes?", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=None,  # como o recorder grava a fala do agente
        )
    )
    await session.commit()
    classificador = classificador_fake()
    outbound = outbound_fake()

    await _rodar(imagem, classificador, outbound, resumidor_fake, contador_fake, moderador_fake)

    assert not any(TEXTO_DA_CONFIRMACAO_DE_IMAGEM in texto for texto in outbound.entregues)
    assert KIND_DA_CONFIRMACAO_DE_MIDIA not in await _kinds(session, imagem.id)
    assert classificador.chamadas == 1


async def _recuar_a_conversa(session, minutos: int) -> None:
    """Empurra tudo o que a conversa ja tem `minutos` para o passado -- a foto
    anterior e a fala do agente que a confirmou --, para a proxima mensagem
    gravada chegar `minutos` depois delas."""
    await session.execute(
        update(Message)
        .where(Message.conversation_key == CONVERSA)
        .values(created_at=Message.created_at - timedelta(minutes=minutos))
    )
    await session.commit()


async def test_segunda_foto_logo_depois_da_confirmacao_fecha_em_silencio(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """I2 da revisao final. Duas fotos sem texto com mais de uma janela de
    debounce entre elas rodam dois turnos, e sem esta regra o lead recebia o
    mesmo texto fixo duas vezes seguidas."""
    primeira = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    assert (
        await _rodar(
            primeira,
            classificador_fake(),
            outbound_fake(),
            resumidor_fake,
            contador_fake,
            moderador_fake,
        )
        == "respondido"
    )
    await _recuar_a_conversa(session, 2)
    segunda = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await _rodar(
        segunda, classificador, outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "midia_ja_confirmada"
    assert outbound.entregues == []
    assert classificador.chamadas == 0
    assert await _kinds(session, segunda.id) == []


async def test_segunda_foto_depois_da_janela_confirma_de_novo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    primeira = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    await _rodar(
        primeira,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake,
        contador_fake,
        moderador_fake,
    )
    await _recuar_a_conversa(session, 11)
    segunda = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    outbound = outbound_fake()

    resultado = await _rodar(
        segunda, classificador_fake(), outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 1
    assert outbound.entregues[0].endswith(TEXTO_DA_CONFIRMACAO_DE_IMAGEM)
    assert await _kinds(session, segunda.id) == [KIND_DA_CONFIRMACAO_DE_MIDIA]


async def test_foto_depois_de_uma_resposta_do_agente_confirma_de_novo(
    session, classificador_fake, outbound_fake, resumidor_fake, contador_fake, moderador_fake
) -> None:
    """Foto, confirmacao, texto do lead respondido pelo agente, foto: a ultima
    fala do agente ja nao e a confirmacao, e a segunda foto confirma."""
    primeira = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    await _rodar(
        primeira,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake,
        contador_fake,
        moderador_fake,
    )
    texto = await _gravar(session, texto="quero um apartamento de dois quartos")
    outbound_do_texto = outbound_fake()
    await _rodar(
        texto,
        classificador_fake(),
        outbound_do_texto,
        resumidor_fake,
        contador_fake,
        moderador_fake,
    )
    assert outbound_do_texto.entregues, "o turno normal tinha de responder o texto"
    segunda = await _gravar(session, content_type=MessageContentType.IMAGEM, texto=None)
    outbound = outbound_fake()

    resultado = await _rodar(
        segunda, classificador_fake(), outbound, resumidor_fake, contador_fake, moderador_fake
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 1
    assert outbound.entregues[0].endswith(TEXTO_DA_CONFIRMACAO_DE_IMAGEM)

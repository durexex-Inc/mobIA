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

from sqlalchemy import select

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

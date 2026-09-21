"""A pergunta que decide quem, na rajada, e o turno (TEC-128, D3)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.rajada import superada_por_mais_nova
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

LEAD = "5511911112222"
CANAL = "whatsapp"


async def gravar(
    session,
    *,
    created_at: datetime,
    direction: str = MessageDirection.INBOUND,
    role: str = MessageRole.LEAD,
    conversation_key: str = LEAD,
    texto: str = "ainda tem o 2 quartos?",
) -> Message:
    """Grava uma linha com `created_at` EXPLICITO.

    Explicito e nao `server_default`: estes testes precisam controlar a ordem e
    o empate, que e justamente o que o default esconde.
    """
    identificador = uuid.uuid4()
    await session.execute(
        insert(Message).values(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador}",
            sender_external_id=conversation_key,
            recipient_external_id="222222222",
            conversation_key=conversation_key,
            role=role,
            direction=direction,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(texto, aad_de(identificador, "text_body")),
            status=MessageStatus.RECEIVED,
            created_at=created_at,
        )
    )
    await session.commit()
    linha = await session.get(Message, identificador)
    assert linha is not None
    return linha


async def test_mensagem_sozinha_nao_esta_superada(session) -> None:
    agora = datetime.now(UTC)
    unica = await gravar(session, created_at=agora)

    assert await superada_por_mais_nova(session, unica) is False


async def test_mensagem_antiga_esta_superada_pela_nova(session) -> None:
    agora = datetime.now(UTC)
    primeira = await gravar(session, created_at=agora)
    await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await superada_por_mais_nova(session, primeira) is True


async def test_a_mais_nova_nao_esta_superada(session) -> None:
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora)
    ultima = await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await superada_por_mais_nova(session, ultima) is False


async def test_irmas_do_mesmo_envelope_desempatam_por_id(session) -> None:
    """O caso que uma comparacao so por `created_at` perde inteiro.

    Um envelope da Meta com duas mensagens vira um `INSERT` so, numa transacao
    so, e `created_at` e o `now()` da TRANSACAO -- as duas nascem com o mesmo
    instante. Sem o desempate por `id`, cada uma se veria superada pela outra e
    NENHUMA responderia: o lead ficaria sem resposta, nao com duas.
    """
    mesmo_instante = datetime.now(UTC)
    a = await gravar(session, created_at=mesmo_instante)
    b = await gravar(session, created_at=mesmo_instante)

    menor, maior = sorted([a, b], key=lambda linha: linha.id)

    assert await superada_por_mais_nova(session, menor) is True
    assert await superada_por_mais_nova(session, maior) is False


async def test_fala_do_agente_nao_supera_o_lead(session) -> None:
    """A resposta do agente entra na mesma tabela, com o mesmo conversation_key."""
    agora = datetime.now(UTC)
    do_lead = await gravar(session, created_at=agora)
    await gravar(
        session,
        created_at=agora + timedelta(seconds=2),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="Temos sim! Posso te mandar as opcoes?",
    )

    assert await superada_por_mais_nova(session, do_lead) is False


async def test_mensagem_de_outro_lead_nao_supera(session) -> None:
    agora = datetime.now(UTC)
    minha = await gravar(session, created_at=agora)
    await gravar(
        session,
        created_at=agora + timedelta(seconds=2),
        conversation_key="5511999998888",
    )

    assert await superada_por_mais_nova(session, minha) is False

"""A pergunta que decide quem, na rajada, e o turno (TEC-128, D3)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, update

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.rajada import ha_fala_pendente_antes, superada_por_mais_nova
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
    channel: str = CANAL,
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
            channel=channel,
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


async def test_mensagem_de_outro_canal_nao_supera(session) -> None:
    """O filtro `channel` da D3, nao exercitado ate a onda final da TEC-128.

    A D3 do desenho (fora de escopo, TEC-129) declara o cross-canal como
    intencional enquanto os canais nao estiverem unificados: uma rajada que
    atravesse WhatsApp e web nao se agrupa. Sem este teste, uma regressao no
    filtro `channel` de `superada_por_mais_nova` (`messages/rajada.py`) seria
    silenciosa -- os outros cinco testes deste arquivo fixam `channel=CANAL`
    nos dois lados e nunca exercitam o predicado.
    """
    agora = datetime.now(UTC)
    minha = await gravar(session, created_at=agora, channel="whatsapp")
    await gravar(
        session,
        created_at=agora + timedelta(seconds=2),
        channel="web",
    )

    assert await superada_por_mais_nova(session, minha) is False


async def test_sem_nada_antes_nao_ha_fala_pendente(session) -> None:
    """Mensagem isolada: nao ha pergunta orfa para o turno bloqueado responder."""
    unica = await gravar(session, created_at=datetime.now(UTC))

    assert await ha_fala_pendente_antes(session, unica) is False


async def test_irma_mais_antiga_sem_resposta_conta(session) -> None:
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos ate 500 mil?")
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    assert await ha_fala_pendente_antes(session, ultima) is True


async def test_irma_mais_antiga_ja_bloqueada_nao_conta(session) -> None:
    """Fala bloqueada nao e pergunta legitima -- e a mesma definicao que o
    score e a cadencia de follow-up usam."""
    agora = datetime.now(UTC)
    bloqueada = await gravar(session, created_at=agora)
    await session.execute(
        update(Message).where(Message.id == bloqueada.id).values(bloqueada_em=agora)
    )
    await session.commit()
    ultima = await gravar(session, created_at=agora + timedelta(seconds=1))

    assert await ha_fala_pendente_antes(session, ultima) is False


async def test_fala_do_agente_entre_as_duas_fecha_a_pendencia(session) -> None:
    """O agente ja respondeu a primeira: nao ha nada pendente antes da segunda."""
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos?")
    await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="Temos sim! Posso te mandar as opcoes?",
    )
    ultima = await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await ha_fala_pendente_antes(session, ultima) is False


async def test_pendente_atras_de_uma_bloqueada_ainda_conta(session) -> None:
    """O caso que uma consulta ingenua perde.

    Olhar so a mensagem IMEDIATAMENTE anterior daria False aqui, porque a
    imediatamente anterior esta bloqueada -- e a pergunta legitima de antes
    dela ficaria orfa em silencio.
    """
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos ate 500 mil?")
    bloqueada = await gravar(session, created_at=agora + timedelta(seconds=1))
    await session.execute(
        update(Message)
        .where(Message.id == bloqueada.id)
        .values(bloqueada_em=agora + timedelta(seconds=1))
    )
    await session.commit()
    ultima = await gravar(session, created_at=agora + timedelta(seconds=2))

    assert await ha_fala_pendente_antes(session, ultima) is True


async def test_pendente_de_outro_lead_nao_conta(session) -> None:
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, conversation_key="5511999998888")
    minha = await gravar(session, created_at=agora + timedelta(seconds=1))

    assert await ha_fala_pendente_antes(session, minha) is False

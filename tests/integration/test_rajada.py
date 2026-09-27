"""A pergunta que decide quem, na rajada, e o turno (TEC-128, D3)."""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import pmid_do_whatsapp  # type: ignore[import-not-found]
from sqlalchemy import insert, update

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.rajada import ha_fala_pendente_antes, superada_por_mais_nova
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt, encrypt_json

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
    texto: str | None = "ainda tem o 2 quartos?",
    content_type: str = MessageContentType.TEXTO,
) -> Message:
    """Grava uma linha com `created_at` EXPLICITO.

    Explicito e nao `server_default`: estes testes precisam controlar a ordem e
    o empate, que e justamente o que o default esconde.

    `texto=None` grava a linha sem corpo, como chega uma imagem ou um
    documento sem legenda (TEC-132).
    """
    identificador = uuid.uuid4()
    await session.execute(
        insert(Message).values(
            id=identificador,
            channel=channel,
            # TEC-383: o HMAC na coluna e o wamid cru so no raw cifrado.
            provider_message_id=pmid_do_whatsapp(f"wamid.{identificador}"),
            raw_payload=encrypt_json(
                {"id": f"wamid.{identificador}"}, aad_de(identificador, "raw_payload")
            ),
            sender_external_id=conversation_key,
            recipient_external_id="222222222",
            conversation_key=conversation_key,
            role=role,
            direction=direction,
            content_type=content_type,
            text_body=None if texto is None else encrypt(texto, aad_de(identificador, "text_body")),
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


async def test_pendente_de_outro_canal_nao_conta(session) -> None:
    """Os dois pontos onde `ha_fala_pendente_antes` usa o filtro `channel`.

    Espelha `test_mensagem_de_outro_canal_nao_supera`: sem este teste, uma
    regressao no filtro `channel` -- seja no INBOUND pendente (a consulta
    principal) seja na subquery da ultima fala do agente -- seria silenciosa.

    Duas mensagens so cobrem o primeiro ponto: sem nenhum OUTBOUND semeado, a
    subquery da ultima fala do agente da NULL com ou sem o filtro de canal --
    apagar aquele filtro nao mudaria o resultado deste primeiro bloco. O
    segundo bloco usa `conversation_key` proprio para nao herdar o historico
    do primeiro, e semeia um OUTBOUND de outro canal DEPOIS da pendente
    legitima: sem o filtro de canal na subquery, aquele OUTBOUND viraria a
    "ultima fala do agente" da conversa errada e apagaria a pendencia real.
    """
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, channel="whatsapp")
    minha = await gravar(session, created_at=agora + timedelta(seconds=1), channel="web")

    assert await ha_fala_pendente_antes(session, minha) is False

    outra_conversa = "5511900001111"
    await gravar(
        session,
        created_at=agora + timedelta(seconds=2),
        channel="web",
        conversation_key=outra_conversa,
    )
    await gravar(
        session,
        created_at=agora + timedelta(seconds=3),
        channel="whatsapp",
        conversation_key=outra_conversa,
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
    )
    minha_2 = await gravar(
        session,
        created_at=agora + timedelta(seconds=4),
        channel="web",
        conversation_key=outra_conversa,
    )

    assert await ha_fala_pendente_antes(session, minha_2) is True


async def test_teto_do_agente_ignora_a_fala_posterior_a_ele(session) -> None:
    """TEC-298, D1. Com teto, a fala do agente posterior a ele nao fecha a pendencia.

    E o estado da retentativa: a recusa da passada anterior ja e a ultima fala
    OUTBOUND, e sem o teto ela apaga a pendencia da pergunta legitima. O teto
    reconstroi a fronteira que existia antes dela.
    """
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos ate 500 mil?")
    recusa = await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="nao consigo seguir com essa mensagem",
    )
    carregadora = await gravar(session, created_at=agora + timedelta(seconds=2))

    # Sem teto: a recusa e a ultima fala do agente e apaga a pendencia.
    assert await ha_fala_pendente_antes(session, carregadora) is False
    # Com teto no instante da recusa: ela sai da conta e a pergunta reaparece.
    assert (
        await ha_fala_pendente_antes(session, carregadora, teto_do_agente=recusa.created_at) is True
    )


async def test_teto_no_futuro_nao_muda_nada(session) -> None:
    """O teto so pode ESCONDER fala do agente, nunca revelar fala que nao existe."""
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="tem 2 quartos?")
    await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        direction=MessageDirection.OUTBOUND,
        role=MessageRole.AGENTE,
        texto="tenho estas opcoes",
    )
    carregadora = await gravar(session, created_at=agora + timedelta(seconds=2))

    teto = agora + timedelta(hours=1)
    assert await ha_fala_pendente_antes(session, carregadora, teto_do_agente=teto) is False


async def test_com_texto_ignora_midia_sem_legenda_pendente(session) -> None:
    """TEC-132, D4. Imagem sem legenda pendente nao e texto do lead.

    Sem `com_texto` ela conta como fala pendente, como sempre contou; com
    `com_texto=True` nao, e e isso que deixa a segunda imagem de uma rajada
    so de fotos receber a confirmacao fixa.
    """
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto=None, content_type=MessageContentType.IMAGEM)
    ultima = await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        texto=None,
        content_type=MessageContentType.IMAGEM,
    )

    assert await ha_fala_pendente_antes(session, ultima) is True
    assert await ha_fala_pendente_antes(session, ultima, com_texto=True) is False


async def test_com_texto_ainda_ve_o_texto_pendente(session) -> None:
    """O "quero esse" antes da foto: com ou sem `com_texto`, ele esta pendente."""
    agora = datetime.now(UTC)
    await gravar(session, created_at=agora, texto="quero esse")
    ultima = await gravar(
        session,
        created_at=agora + timedelta(seconds=1),
        texto=None,
        content_type=MessageContentType.IMAGEM,
    )

    assert await ha_fala_pendente_antes(session, ultima) is True
    assert await ha_fala_pendente_antes(session, ultima, com_texto=True) is True

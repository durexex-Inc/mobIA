"""A janela de literais le as sessoes vinculadas. TEC-129, D4."""

import uuid
from datetime import UTC, datetime, timedelta

from mobia.domain.context.janela import Marca, literais_apos
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus

WA_ID = "5548999990000"


def _fala(channel: str, chave: str, quando: datetime, bloqueada: bool = False) -> Message:
    return Message(
        channel=channel,
        conversation_key=chave,
        sender_external_id=chave,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.PROCESSED,
        created_at=quando,
        bloqueada_em=quando if bloqueada else None,
    )


async def test_sem_pares_e_como_antes(session) -> None:
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    session.add_all([_fala(CANAL_WHATSAPP, WA_ID, agora), _fala(CANAL_WEB, sessao, agora)])
    await session.commit()

    literais = await literais_apos(session, CANAL_WHATSAPP, WA_ID, None)

    assert [m.channel for m in literais] == [CANAL_WHATSAPP]


async def test_inclui_os_pares_em_ordem_cronologica(session) -> None:
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    session.add_all(
        [
            _fala(CANAL_WEB, sessao, agora - timedelta(hours=2)),
            _fala(CANAL_WHATSAPP, WA_ID, agora - timedelta(hours=1)),
            _fala(CANAL_WEB, sessao, agora - timedelta(minutes=30), bloqueada=True),
            _fala(CANAL_WEB, str(uuid.uuid4()), agora),  # outra sessao, sem vinculo
        ]
    )
    await session.commit()

    literais = await literais_apos(
        session, CANAL_WHATSAPP, WA_ID, None, pares_vinculados=[(CANAL_WEB, sessao)]
    )

    # A bloqueada pela moderacao continua fora, venha de que par vier.
    assert [m.channel for m in literais] == [CANAL_WEB, CANAL_WHATSAPP]


async def test_a_marca_vale_para_os_pares(session) -> None:
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    antiga = _fala(CANAL_WEB, sessao, agora - timedelta(hours=2))
    marco = _fala(CANAL_WHATSAPP, WA_ID, agora - timedelta(hours=1))
    nova = _fala(CANAL_WEB, sessao, agora)
    session.add_all([antiga, marco, nova])
    await session.commit()

    literais = await literais_apos(
        session,
        CANAL_WHATSAPP,
        WA_ID,
        Marca(created_at=marco.created_at, message_id=marco.id),
        pares_vinculados=[(CANAL_WEB, sessao)],
    )

    assert [m.id for m in literais] == [nova.id]

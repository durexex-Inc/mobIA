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


async def test_fala_vinculada_depois_do_instante_do_turno_fica_de_fora(session) -> None:
    """Revisao final da TEC-129 (I2): das sessoes vinculadas so entra o que foi
    dito ate a fala do turno. O proprio par nao tem esse limite."""
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    web_antes = _fala(CANAL_WEB, sessao, agora - timedelta(minutes=10))
    do_turno = _fala(CANAL_WHATSAPP, WA_ID, agora - timedelta(minutes=5))
    web_depois = _fala(CANAL_WEB, sessao, agora - timedelta(minutes=1))
    whatsapp_depois = _fala(CANAL_WHATSAPP, WA_ID, agora)
    session.add_all([web_antes, do_turno, web_depois, whatsapp_depois])
    await session.commit()

    literais = await literais_apos(
        session,
        CANAL_WHATSAPP,
        WA_ID,
        None,
        pares_vinculados=[(CANAL_WEB, sessao)],
        ate_das_vinculadas=do_turno.created_at,
    )

    assert [m.id for m in literais] == [web_antes.id, do_turno.id, whatsapp_depois.id]


async def test_fala_vinculada_no_mesmo_instante_do_turno_fica_de_fora(session) -> None:
    """O limite e estrito: no empate de `created_at` a ordem sai do `id`, e a
    fala web poderia ficar depois da do turno na lista."""
    agora = datetime.now(UTC)
    sessao = str(uuid.uuid4())
    do_turno = _fala(CANAL_WHATSAPP, WA_ID, agora)
    empatada = _fala(CANAL_WEB, sessao, agora)
    session.add_all([do_turno, empatada])
    await session.commit()

    literais = await literais_apos(
        session,
        CANAL_WHATSAPP,
        WA_ID,
        None,
        pares_vinculados=[(CANAL_WEB, sessao)],
        ate_das_vinculadas=do_turno.created_at,
    )

    assert [m.id for m in literais] == [do_turno.id]

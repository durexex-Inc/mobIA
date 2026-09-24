"""O vinculo sessao web -> telefone. TEC-129, D3."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.identidade.repositorio import sessoes_vinculadas, vincular_sessao
from mobia.domain.messages.canais import CANAL_WEB
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker

TELEFONE = "5548999990000"


async def _mensagem_web(session, sessao: str) -> uuid.UUID:
    linha = Message(
        channel=CANAL_WEB,
        conversation_key=sessao,
        sender_external_id=sessao,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.RECEIVED,
    )
    session.add(linha)
    await session.commit()
    return linha.id


async def test_cria_o_vinculo(session) -> None:
    sessao = str(uuid.uuid4())
    evidencia = await _mensagem_web(session, sessao)

    criou = await vincular_sessao(
        get_sessionmaker(),
        channel=CANAL_WEB,
        conversation_key=sessao,
        telefone=TELEFONE,
        message_id=evidencia,
    )

    assert criou is True
    linha = (await session.execute(select(VinculoDeSessao))).scalar_one()
    assert (linha.channel, linha.conversation_key, linha.telefone) == (CANAL_WEB, sessao, TELEFONE)
    assert linha.message_id == evidencia


async def test_o_primeiro_telefone_vence(session) -> None:
    sessao = str(uuid.uuid4())
    primeira = await _mensagem_web(session, sessao)
    segunda = await _mensagem_web(session, sessao)
    fabrica = get_sessionmaker()

    await vincular_sessao(
        fabrica, channel=CANAL_WEB, conversation_key=sessao, telefone=TELEFONE, message_id=primeira
    )
    criou = await vincular_sessao(
        fabrica,
        channel=CANAL_WEB,
        conversation_key=sessao,
        telefone="5548988881111",
        message_id=segunda,
    )

    assert criou is False
    assert (await session.execute(select(VinculoDeSessao.telefone))).scalar_one() == TELEFONE


async def test_duas_sessoes_para_o_mesmo_telefone(session) -> None:
    fabrica = get_sessionmaker()
    sessoes = [str(uuid.uuid4()), str(uuid.uuid4())]
    for sessao in sessoes:
        await vincular_sessao(
            fabrica,
            channel=CANAL_WEB,
            conversation_key=sessao,
            telefone=TELEFONE,
            message_id=await _mensagem_web(session, sessao),
        )

    assert await sessoes_vinculadas(session, TELEFONE) == [(CANAL_WEB, s) for s in sessoes]


async def test_telefone_sem_vinculo_devolve_vazio(session) -> None:
    assert await sessoes_vinculadas(session, TELEFONE) == []


async def test_com_limite_ficam_as_mais_recentes_em_ordem_cronologica(session) -> None:
    fabrica = get_sessionmaker()
    sessoes = [str(uuid.uuid4()) for _ in range(4)]
    for indice, sessao in enumerate(sessoes):
        await vincular_sessao(
            fabrica,
            channel=CANAL_WEB,
            conversation_key=sessao,
            telefone=TELEFONE,
            message_id=await _mensagem_web(session, sessao),
        )
        # `criado_em` e `now()` do servidor; force a ordem da lista.
        await session.execute(
            VinculoDeSessao.__table__.update()
            .where(VinculoDeSessao.conversation_key == sessao)
            .values(criado_em=datetime.now(UTC) - timedelta(hours=10 - indice))
        )
        await session.commit()

    assert await sessoes_vinculadas(session, TELEFONE, limite=3) == [
        (CANAL_WEB, s) for s in sessoes[1:]
    ]

"""O que a visitante ve ao reabrir o widget. TEC-124, D6."""

import uuid
from datetime import UTC, datetime

from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.historico import historico_da_sessao
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, encrypt

SESSAO = "8c0f0a3e-0000-4000-8000-0000000000aa"


async def _fala(
    session,
    *,
    papel: MessageRole,
    direcao: MessageDirection,
    texto: str,
    sessao: str = SESSAO,
    bloqueada: bool = False,
) -> None:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL_WEB,
            provider_message_id=None,
            sender_external_id=sessao,
            recipient_external_id=REMETENTE_DO_WIDGET,
            conversation_key=sessao,
            role=papel,
            direction=direcao,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(texto, aad_de(identificador, "text_body")),
            raw_payload=None,
            bloqueada_em=datetime.now(UTC) if bloqueada else None,
        )
    )
    await session.commit()


async def test_devolve_as_falas_em_ordem_cronologica(session, session_factory) -> None:
    await _fala(session, papel=MessageRole.LEAD, direcao=MessageDirection.INBOUND, texto="oi")
    await _fala(session, papel=MessageRole.AGENTE, direcao=MessageDirection.OUTBOUND, texto="olá!")

    falas = await historico_da_sessao(session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=50)

    assert [(f.papel, f.texto) for f in falas] == [("lead", "oi"), ("agente", "olá!")]


async def test_a_fala_bloqueada_pela_moderacao_nao_volta_a_tela(session, session_factory) -> None:
    # Mesmo criterio da TEC-236 e da Emenda E-01 da RN-02.2: ela nao entra em
    # contexto nem em resumo, e esta seria a unica tela onde reapareceria.
    await _fala(
        session,
        papel=MessageRole.LEAD,
        direcao=MessageDirection.INBOUND,
        texto="conteudo bloqueado",
        bloqueada=True,
    )

    falas = await historico_da_sessao(session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=50)

    assert falas == []


async def test_o_limite_corta_as_mais_antigas_e_preserva_a_ordem(session, session_factory) -> None:
    for indice in range(5):
        await _fala(
            session,
            papel=MessageRole.LEAD,
            direcao=MessageDirection.INBOUND,
            texto=f"fala {indice}",
        )

    falas = await historico_da_sessao(session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=2)

    assert [f.texto for f in falas] == ["fala 3", "fala 4"]


async def test_falas_do_corretor_e_do_sistema_ficam_de_fora(session, session_factory) -> None:
    await _fala(session, papel=MessageRole.LEAD, direcao=MessageDirection.INBOUND, texto="oi")
    await _fala(
        session, papel=MessageRole.SISTEMA, direcao=MessageDirection.OUTBOUND, texto="interno"
    )

    falas = await historico_da_sessao(session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=50)

    assert [f.texto for f in falas] == ["oi"]


async def test_outra_sessao_nao_vaza(session, session_factory) -> None:
    await _fala(
        session,
        papel=MessageRole.LEAD,
        direcao=MessageDirection.INBOUND,
        texto="de outra pessoa",
        sessao="8c0f0a3e-0000-4000-8000-0000000000ab",
    )

    falas = await historico_da_sessao(session_factory, canal=CANAL_WEB, sessao=SESSAO, limite=50)

    assert falas == []


async def test_sessao_desconhecida_devolve_vazio(session_factory) -> None:
    # UUID valido que nunca falou: `localStorage` de uma sessao ja encerrada,
    # ou de outro ambiente. Nao e erro.
    falas = await historico_da_sessao(
        session_factory,
        canal=CANAL_WEB,
        sessao="8c0f0a3e-0000-4000-8000-0000000000ff",
        limite=50,
    )
    assert falas == []

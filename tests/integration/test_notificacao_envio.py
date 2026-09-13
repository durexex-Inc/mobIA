"""A notificacao de ponta a ponta, com canais falsos."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.envio import KIND_DA_JANELA_HUMANA, notificar


class _CanalEspiao:
    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[tuple[str, str, str]] = []

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        self.recebidas.append((destino, assunto, corpo))


class _CanalQueFalha:
    def __init__(self, nome: str) -> None:
        self.nome = nome

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        raise FalhaDeCanal(f"{self.nome} recusou")


class _OutboundFalso:
    """Duble de `OutboundPort` que so registra as chamadas."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[uuid.UUID, str, dict[str, Any]]] = []

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        self.chamadas.append((message_id, kind, payload))
        return True


def _janela_fechada_para_agora() -> tuple[int, int]:
    """Uma janela (inicio, fim) que NAO contem a hora local de agora, com folga.

    `notificar` nao recebe `momento` por parametro -- le `datetime.now(UTC)`
    por dentro --, entao o teste nao pode fixar o relogio. A janela e
    escolhida em funcao da hora ATUAL, no mesmo fuso que `notificar` usa
    (`fuso_de_envio`), com pelo menos tres horas de folga para os dois lados:
    o suficiente para absorver o tempo entre este calculo e a chamada real,
    sem tornar o teste dependente da hora em que a suite roda.
    """
    hora = datetime.now(UTC).astimezone(get_settings().fuso_de_envio).hour
    if hora < 10:
        return 12, 23
    if hora > 11:
        return 0, 9
    return 14, 23


async def test_notifica_os_dois_canais_com_resumo_e_link(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Primeiro cenario do Gherkin, com dubles -- ver a L1 do desenho."""
    corretor = await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="## Quem e o lead\nfulano")
    email, whats = _CanalEspiao("email"), _CanalEspiao("whatsapp")

    assert await notificar(
        session_factory, canais=(email, whats), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    for canal in (email, whats):
        assert len(canal.recebidas) == 1
        _, _, corpo = canal.recebidas[0]
        assert "## Quem e o lead" in corpo
        assert "/conversas/whatsapp/" in corpo

    assert email.recebidas[0][0] == corretor.email
    assert whats.recebidas[0][0] == corretor.telefone


async def test_falha_de_um_canal_nao_cancela_o_outro(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Segundo cenario do Gherkin."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    email = _CanalEspiao("email")

    assert await notificar(
        session_factory,
        canais=(_CanalQueFalha("whatsapp"), email),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    assert len(email.recebidas) == 1
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is not None
    assert linha.aviso_manual_pendente is False


async def test_falha_dos_dois_marca_aviso_manual(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Terceiro cenario do Gherkin."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalQueFalha("email"), _CanalQueFalha("whatsapp")),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is None
    assert linha.aviso_manual_pendente is True


async def test_sem_destinatario_marca_aviso_manual(
    session, session_factory, semear_handoff_com_resumo
) -> None:
    """D4: nenhum corretor cadastrado."""
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.aviso_manual_pendente is True


async def test_handoff_sem_resumo_notifica_mesmo_assim(
    session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """D2: silencio seria pior que resumo faltando."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo=None)
    email = _CanalEspiao("email")

    assert await notificar(
        session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    _, _, corpo = email.recebidas[0]
    assert "nao pode ser gerado" in corpo


async def test_fora_da_jornada_do_corretor_avisa_o_lead_da_janela_humana(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    semear_handoff_com_resumo,
    semear_corretor,
) -> None:
    """Quarto cenario do Gherkin: jornada fechada, e o lead e avisado.

    A jornada testada e a DO CORRETOR (`horario_inicio`/`horario_fim` de
    `Corretor`), calculada em funcao do relogio de agora -- ver
    `_janela_fechada_para_agora` -- para o teste nao depender da hora em que
    a suite roda. O corretor ainda recebe a notificacao normalmente: a
    jornada fechada so acrescenta o aviso ao lead, e nao impede o envio ao
    corretor.
    """
    inicio, fim = _janela_fechada_para_agora()
    await semear_corretor(
        email="plantao@x.com", plantao=True, horario_inicio=inicio, horario_fim=fim
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal="whatsapp")
    handoff = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()

    mensagem_do_lead = Message(
        id=uuid.uuid4(),
        channel=handoff.channel,
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id=handoff.conversation_key,
        recipient_external_id="222222222",
        conversation_key=handoff.conversation_key,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
    )
    session.add(mensagem_do_lead)
    await session.commit()

    email = _CanalEspiao("email")
    outbound = _OutboundFalso()

    assert await notificar(
        session_factory, canais=(email,), outbound=outbound, handoff_id=handoff_id
    )

    assert len(email.recebidas) == 1

    assert len(outbound.chamadas) == 1
    message_id, kind, payload = outbound.chamadas[0]
    assert message_id == mensagem_do_lead.id
    assert kind == KIND_DA_JANELA_HUMANA
    assert payload["para"] == handoff.conversation_key
    assert payload["de"] == "222222222"
    assert f"{inicio}h" in payload["texto"]
    assert f"{fim}h" in payload["texto"]

"""Criterios de aceite da TEC-209 como testes de caos. RNF-27, RNF-32, RNF-33.

"Caos" aqui e o componente derrubado por dublê no ponto de integracao, com o
resto de verdade -- banco, turno, `process_message`, a reserva de saida (D6 do
desenho). Derrubar containers dentro da suite a tornaria tao fragil quanto o
`[WinError 64]` do CLAUDE.md descreve.

Tres dos seis cenarios vivem em outros arquivos, porque ja estavam cobertos
ou porque o ponto certo de testa-los e mais baixo:

- *primario indisponivel cai no secundario*:
  `tests/unit/test_cadeia_da_chamada_principal.py`, contra o cliente
  Anthropic falso -- e la que a cadeia existe;
- *sem indice vetorial, a busca continua*:
  `tests/integration/test_busca_hibrida.py::test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro`;
- *WhatsApp fora nao derruba o widget*:
  `tests/features/test_atendimento_pelo_widget_web.py::test_whatsapp_indisponivel_nao_afeta_o_canal_web`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import ClassificadorFake, ContadorFake, ModeradorFake, OutboundFake, ResumidorFake
from httpx import AsyncClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agente.classificador import ProvedorIndisponivel
from mobia.domain.agente.turno import TEXTO_DO_AVISO_DE_ERRO
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.domain.usuarios import tokens
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import ERRO_DA_INTERRUPCAO, process_message


def _ctx(outbound: OutboundFake, classificador: ClassificadorFake) -> dict[str, Any]:
    return {
        "session_factory": get_sessionmaker(),
        "outbound": outbound,
        "classificador": classificador,
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "agendador_de_avisos": AgendadorDeAvisosNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop(), CANAL_WEB: IndicadorNoop()},
    }


def _admin() -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), "ADMIN", mfa=True, corretor_id=None, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _linha(session: AsyncSession, message_id: uuid.UUID) -> Message:
    session.expire_all()
    linha = await session.get(Message, message_id)
    assert linha is not None
    return linha


async def _gatilhos(session: AsyncSession) -> list[str]:
    return list((await session.execute(text("SELECT gatilho FROM handoffs"))).scalars())


async def _forcar(session: AsyncSession, message_id: uuid.UUID, **valores: object) -> None:
    await session.execute(update(Message).where(Message.id == message_id).values(**valores))
    await session.commit()


# --- RNF-27: os dois provedores fora --------------------------------------------


async def test_os_dois_provedores_fora_geram_espera_e_handoff_na_mesma_passada(
    session: AsyncSession, semear_entrada: Any
) -> None:
    """Cenario 2: espera honesta e handoff, sem esperar a quinta falha.

    A linha fecha PROCESSED e `attempts` fica em zero: a cadeia ja retentou e
    ja tentou o secundario, e o sweeper nao tem o que refazer.
    """
    entrada = await semear_entrada(session, status=MessageStatus.QUEUED)
    outbound = OutboundFake(get_sessionmaker())
    classificador = ClassificadorFake(erro=ProvedorIndisponivel("cadeia esgotada"))

    resultado = await process_message(_ctx(outbound, classificador), str(entrada.id))

    assert resultado == "provedor_indisponivel"
    assert any(TEXTO_DO_AVISO_DE_ERRO in texto for texto in outbound.entregues)
    assert await _gatilhos(session) == ["ERRO_DO_AGENTE"]
    linha = await _linha(session, entrada.id)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.attempts == 0


# --- RNF-33: worker morto ------------------------------------------------------


async def test_worker_morto_e_reprocessado_sem_resposta_duplicada(
    session: AsyncSession, semear_entrada: Any
) -> None:
    """Cenario 5. O worker entregou e morreu antes de fechar a linha.

    A primeira passada responde; a linha e devolvida a PROCESSING, que e o
    que um SIGKILL depois do envio deixa para tras. A segunda conta a
    tentativa interrompida, roda o turno, e a reserva em `outbound_dispatches`
    impede a resposta de sair de novo.
    """
    entrada = await semear_entrada(session, status=MessageStatus.QUEUED)
    primeira = OutboundFake(get_sessionmaker())
    await process_message(_ctx(primeira, ClassificadorFake()), str(entrada.id))
    assert len(primeira.entregues) == 1
    # O lease do worker morto tambem vence: desde a TEC-218, PROCESSING com
    # `claimed_at` recente e de um worker VIVO, e ninguem o retoma. A retomada
    # real so acontece depois da janela, e e ela que este cenario descreve.
    await _forcar(
        session,
        entrada.id,
        status=MessageStatus.PROCESSING,
        claimed_at=datetime.now(UTC)
        - timedelta(seconds=get_settings().sweep_inflight_after_seconds + 1),
    )

    segunda = OutboundFake(get_sessionmaker())
    await process_message(_ctx(segunda, ClassificadorFake()), str(entrada.id))

    assert segunda.entregues == []
    linha = await _linha(session, entrada.id)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.attempts == 1
    assert linha.last_error == ERRO_DA_INTERRUPCAO


async def test_a_ultima_interrupcao_manda_para_a_dlq_sem_rodar_o_turno(
    session: AsyncSession, semear_entrada: Any
) -> None:
    """D4: a mensagem que ja matou cinco workers nao roda uma sexta vez."""
    entrada = await semear_entrada(session, status=MessageStatus.QUEUED)
    await _forcar(
        session,
        entrada.id,
        status=MessageStatus.PROCESSING,
        attempts=get_settings().sweep_max_attempts - 1,
    )
    classificador = ClassificadorFake()

    resultado = await process_message(
        _ctx(OutboundFake(get_sessionmaker()), classificador), str(entrada.id)
    )

    assert resultado == "esgotada"
    assert classificador.chamadas == 0
    assert (await _linha(session, entrada.id)).status == MessageStatus.ESGOTADA
    assert await _gatilhos(session) == ["ERRO_DO_AGENTE"]


# --- RNF-33: a dead-letter queue -----------------------------------------------


async def test_falha_permanente_vai_para_a_dlq_e_volta_pelo_reprocessamento(
    session: AsyncSession, semear_entrada: Any, client: AsyncClient
) -> None:
    """Cenario 6, de ponta a ponta: esgota, aparece na lista, volta, processa."""
    entrada = await semear_entrada(session, status=MessageStatus.QUEUED)
    await _forcar(session, entrada.id, attempts=get_settings().sweep_max_attempts - 1)
    quebrado = ClassificadorFake(erro=RuntimeError("falha permanente"))
    with pytest.raises(RuntimeError):
        await process_message(_ctx(OutboundFake(get_sessionmaker()), quebrado), str(entrada.id))
    assert (await _linha(session, entrada.id)).status == MessageStatus.ESGOTADA

    lista = (await client.get("/api/v1/mensagens/esgotadas", headers=_admin())).json()["itens"]
    assert [item["id"] for item in lista] == [str(entrada.id)]
    assert lista[0]["ultimoErro"] == "RuntimeError"
    assert "conversationKey" not in lista[0]

    resposta = await client.post(f"/api/v1/mensagens/{entrada.id}/reprocessar", headers=_admin())
    assert resposta.status_code == 200, resposta.text
    linha = await _linha(session, entrada.id)
    assert (linha.status, linha.attempts) == (MessageStatus.RECEIVED, 0)

    outbound = OutboundFake(get_sessionmaker())
    await process_message(_ctx(outbound, ClassificadorFake()), str(entrada.id))
    assert (await _linha(session, entrada.id)).status == MessageStatus.PROCESSED
    assert outbound.entregues


async def test_a_dlq_inclui_a_failed_esgotada_de_antes_da_0061(
    session: AsyncSession, semear_entrada: Any, client: AsyncClient
) -> None:
    """A migration nao reclassificou as antigas; a lista as acha pelo criterio."""
    entrada = await semear_entrada(session, status=MessageStatus.QUEUED)
    await _forcar(
        session,
        entrada.id,
        status=MessageStatus.FAILED,
        attempts=get_settings().sweep_max_attempts,
    )

    lista = (await client.get("/api/v1/mensagens/esgotadas", headers=_admin())).json()["itens"]

    assert [item["id"] for item in lista] == [str(entrada.id)]


async def test_reprocessar_o_que_nao_esta_na_dlq_e_409(
    session: AsyncSession, semear_entrada: Any, client: AsyncClient
) -> None:
    entrada = await semear_entrada(session, status=MessageStatus.QUEUED)
    await _forcar(session, entrada.id, status=MessageStatus.PROCESSED)

    resposta = await client.post(f"/api/v1/mensagens/{entrada.id}/reprocessar", headers=_admin())

    assert resposta.status_code == 409
    assert (await _linha(session, entrada.id)).status == MessageStatus.PROCESSED


async def test_reprocessar_mensagem_inexistente_e_404(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.post(f"/api/v1/mensagens/{uuid.uuid4()}/reprocessar", headers=_admin())
    assert resposta.status_code == 404


async def test_gerente_nao_opera_a_fila(client: AsyncClient, banco_limpo: None) -> None:
    token = tokens.emitir(
        uuid.uuid4(), "GERENTE", mfa=False, corretor_id=None, settings=get_settings()
    )
    resposta = await client.get(
        "/api/v1/mensagens/esgotadas", headers={"Authorization": f"Bearer {token}"}
    )
    assert resposta.status_code == 403

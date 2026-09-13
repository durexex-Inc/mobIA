"""A recuperacao do handoff PENDENTE sem prazo. TEC-279."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.recuperacao import recuperar_sem_prazo
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho, Status


class _ReenfileiradorEspiao:
    """Registra o que foi reenfileirado, e para qual handoff.

    E a unica prova da D3: sem ele o teste so saberia que algo foi
    reenfileirado, nao QUAL job -- e a escolha entre `gerar_resumo` e
    `notificar` e justamente a decisao que a D3 toma.
    """

    def __init__(self) -> None:
        self.resumos: list[uuid.UUID] = []
        self.notificacoes: list[uuid.UUID] = []

    async def agendar_resumo(self, handoff_id: uuid.UUID) -> None:
        self.resumos.append(handoff_id)

    async def agendar_notificacao(self, handoff_id: uuid.UUID) -> None:
        self.notificacoes.append(handoff_id)


async def _semear_handoff(session: AsyncSession, *, conversa: str) -> uuid.UUID:
    """Cria um handoff LEAD_QUENTE, PENDENTE, sem resumo e sem prazo -- o estado
    de construcao (D2). Cada teste ajusta as colunas que precisa por cima.
    """
    registro = await registrar_handoff(
        session, channel="whatsapp", conversation_key=conversa, gatilho=Gatilho.LEAD_QUENTE
    )
    await session.commit()
    return registro.id


async def _marcar(session: AsyncSession, *, handoff_id: uuid.UUID, **campos: object) -> None:
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(**campos))
    await session.commit()


async def test_handoff_sem_resumo_reenfileira_a_geracao(session, session_factory, banco_limpo):
    """Primeiro ramo da D3. `gerar_resumo` gera E enfileira `notificar` no fim.

    Reenfileirar `notificar` direto aqui perderia o resumo para sempre: o
    corretor receberia `TEXTO_SEM_RESUMO`, que e o caminho degradado da D2 da
    TEC-177 -- legitimo quando o resumo falhou, indevido quando ele nem foi
    tentado.
    """
    handoff_id = await _semear_handoff(session, conversa="5511900000001")
    criado_ha_20_minutos = datetime.now(UTC) - timedelta(minutes=20)
    await _marcar(session, handoff_id=handoff_id, criado_em=criado_ha_20_minutos)
    espiao = _ReenfileiradorEspiao()

    total = await recuperar_sem_prazo(session_factory, reenfileirador=espiao)

    assert total == 1
    assert espiao.resumos == [handoff_id]
    assert espiao.notificacoes == []


async def test_handoff_com_resumo_reenfileira_so_a_notificacao(
    session, session_factory, banco_limpo
):
    """Segundo ramo da D3, e a razao de ele existir.

    `gerar_resumo` NAO checa se o resumo ja existe -- ele carrega o dossie e
    chama o redator incondicionalmente. Reenfileira-lo aqui pagaria uma
    segunda chamada ao provedor por nada.
    """
    handoff_id = await _semear_handoff(session, conversa="5511900000002")
    criado_ha_20_minutos = datetime.now(UTC) - timedelta(minutes=20)
    # Bytes quaisquer -- a recuperacao so olha se `resumo` e nulo, nunca
    # decifra, entao nao ha necessidade de cifrar de verdade aqui.
    await _marcar(
        session,
        handoff_id=handoff_id,
        criado_em=criado_ha_20_minutos,
        resumo=b"conteudo cifrado de teste",
    )
    espiao = _ReenfileiradorEspiao()

    total = await recuperar_sem_prazo(session_factory, reenfileirador=espiao)

    assert total == 1
    assert espiao.notificacoes == [handoff_id]
    assert espiao.resumos == []


async def test_handoff_recem_criado_nao_e_recuperado(session, session_factory, banco_limpo):
    """Segundo cenario do Gherkin -- passa por construcao (D2).

    O caminho normal ainda pode concluir. Recuperar aqui competiria com ele:
    o `_job_id` fixo protege enquanto o job original esta vivo, mas nao
    depois que ele termina.
    """
    await _semear_handoff(session, conversa="5511900000003")
    espiao = _ReenfileiradorEspiao()

    total = await recuperar_sem_prazo(session_factory, reenfileirador=espiao)

    assert total == 0
    assert espiao.resumos == []
    assert espiao.notificacoes == []


async def test_handoff_ja_notificado_nao_e_recuperado(session, session_factory, banco_limpo):
    """Quarto cenario do Gherkin -- passa por construcao (D2).

    `notificado_em` preenchido significa que `notificar` rodou e um canal
    aceitou. Reenfileirar duplicaria a notificacao.
    """
    handoff_id = await _semear_handoff(session, conversa="5511900000004")
    criado_ha_20_minutos = datetime.now(UTC) - timedelta(minutes=20)
    await _marcar(
        session,
        handoff_id=handoff_id,
        criado_em=criado_ha_20_minutos,
        notificado_em=datetime.now(UTC),
    )
    espiao = _ReenfileiradorEspiao()

    total = await recuperar_sem_prazo(session_factory, reenfileirador=espiao)

    assert total == 0


async def test_handoff_com_aviso_manual_pendente_nao_e_recuperado(
    session, session_factory, banco_limpo
):
    """`notificar` rodou e NENHUM canal aceitou.

    Nao e um handoff perdido -- e um que o sistema ja viu e cujo desfecho ja
    esta gravado. A D1 exige `aviso_manual_pendente = false` exatamente por
    isso.
    """
    handoff_id = await _semear_handoff(session, conversa="5511900000005")
    criado_ha_20_minutos = datetime.now(UTC) - timedelta(minutes=20)
    await _marcar(
        session,
        handoff_id=handoff_id,
        criado_em=criado_ha_20_minutos,
        aviso_manual_pendente=True,
    )
    espiao = _ReenfileiradorEspiao()

    total = await recuperar_sem_prazo(session_factory, reenfileirador=espiao)

    assert total == 0


async def test_handoff_escalado_sem_destinatario_nao_e_recuperado(
    session, session_factory, banco_limpo
):
    """Terceiro cenario do Gherkin -- passa por construcao (D2).

    `notificar` marca ESCALADO quando nao ha corretor nenhum (emenda E-02 da
    RN-16.3), e o prazo fica nulo PARA SEMPRE. O `status = 'PENDENTE'` da D1
    ja o filtra -- este teste existe para provar que continua assim.
    """
    handoff_id = await _semear_handoff(session, conversa="5511900000006")
    criado_ha_20_minutos = datetime.now(UTC) - timedelta(minutes=20)
    await _marcar(
        session,
        handoff_id=handoff_id,
        criado_em=criado_ha_20_minutos,
        status=Status.ESCALADO.value,
        aviso_manual_pendente=True,
    )
    espiao = _ReenfileiradorEspiao()

    total = await recuperar_sem_prazo(session_factory, reenfileirador=espiao)

    assert total == 0

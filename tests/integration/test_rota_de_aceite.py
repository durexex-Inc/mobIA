"""O aceite do handoff pelo corretor. TEC-178, secao 6.5 do SRS, Task 6."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.handoff.escalada import escalar_vencidos
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status

TOKEN = "token-de-teste-de-aceite"


@pytest.fixture
async def cliente_http(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde de `app_com_token` em `test_rota_de_corretores.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app()`.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def _marcar(
    session: AsyncSession,
    *,
    handoff_id: uuid.UUID,
    status: Status | None = None,
    sla_limite_em: datetime | None = "sem_mudanca",  # type: ignore[assignment]
) -> None:
    """Sobrescreve status e/ou sla_limite_em de um handoff ja gravado, direto no banco.

    O sentinela `"sem_mudanca"` existe para distinguir "nao mexer no campo" de
    "gravar None" -- `sla_limite_em=None` e um valor valido (RN-16.3).
    """
    valores: dict[str, object] = {}
    if status is not None:
        valores["status"] = status.value
    if sla_limite_em != "sem_mudanca":
        valores["sla_limite_em"] = sla_limite_em
    if valores:
        await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(**valores))
        await session.commit()


async def _linha(session: AsyncSession, handoff_id: uuid.UUID) -> Handoff:
    return (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()


async def test_sem_token_e_403(cliente_http) -> None:
    resposta = await cliente_http.post(f"/api/v1/handoffs/{uuid.uuid4()}/aceitar")
    assert resposta.status_code == 403


async def test_handoff_inexistente_e_404(cliente_http) -> None:
    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/aceitar", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "handoff nao existe"


async def test_aceitar_registra_aceito_em_e_muda_status(
    cliente_http, session: AsyncSession, semear_handoff_com_resumo
) -> None:
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ACEITO"
    assert corpo["dentroDoSla"] is True  # sla_limite_em nulo -- sem prazo, dentro por vacuidade.
    aceito_em_resposta = datetime.fromisoformat(corpo["aceitoEm"])

    linha = await _linha(session, handoff_id)
    assert linha.status == Status.ACEITO
    assert linha.aceito_em is not None
    assert linha.aceito_em == aceito_em_resposta


async def test_segundo_aceite_devolve_409_e_nao_sobrescreve_aceito_em(
    cliente_http, session: AsyncSession, semear_handoff_com_resumo
) -> None:
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    primeira = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers={"X-Admin-Token": TOKEN}
    )
    assert primeira.status_code == 200
    aceito_em_original = (await _linha(session, handoff_id)).aceito_em
    assert aceito_em_original is not None

    segunda = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers={"X-Admin-Token": TOKEN}
    )

    assert segunda.status_code == 409
    linha = await _linha(session, handoff_id)
    assert linha.status == Status.ACEITO
    # O carimbo nao anda para frente -- e ele que alimenta a taxa de aceite
    # no prazo da RN-17.1 (ver o docstring da rota).
    assert linha.aceito_em == aceito_em_original


async def test_aceitar_handoff_escalado_e_permitido(
    cliente_http, session: AsyncSession, semear_handoff_com_resumo
) -> None:
    """Decisao da Task 6: aceitar depois da escalada e o caso real (o gerente
    cobrou e alguem pegou), e por isso e permitido -- ver o relatorio da task
    e a Emenda E-01 da secao 6.5 do SRS.
    """
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    prazo_vencido = datetime.now(UTC) - timedelta(hours=1)
    await _marcar(
        session, handoff_id=handoff_id, status=Status.ESCALADO, sla_limite_em=prazo_vencido
    )

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ACEITO"
    # O prazo ja tinha vencido quando escalou -- o aceite chega depois dele.
    assert corpo["dentroDoSla"] is False

    linha = await _linha(session, handoff_id)
    assert linha.status == Status.ACEITO
    assert linha.aceito_em is not None


async def test_handoff_aceito_deixa_de_ser_varrido_pela_escalada(
    cliente_http, session: AsyncSession, session_factory, semear_handoff_com_resumo
) -> None:
    """A prova da corrida (item 4 do brief): o UPDATE do aceite tira o handoff
    do conjunto que `escalar_vencidos` seleciona, mesmo com o prazo vencido --
    e mesmo que a varredura rode DEPOIS do aceite, nao antes.
    """
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    prazo_vencido = datetime.now(UTC) - timedelta(minutes=1)
    await _marcar(session, handoff_id=handoff_id, sla_limite_em=prazo_vencido)

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 200

    total = await escalar_vencidos(session_factory, canais=())

    assert total == 0
    linha = await _linha(session, handoff_id)
    assert linha.status == Status.ACEITO

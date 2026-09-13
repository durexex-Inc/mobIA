"""As duas rotas que silenciam/reativam o agente, e o aceite do handoff junto.

TEC-179, Task 6.
"""

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

TOKEN = "token-de-teste-de-conversas"
CHANNEL = "whatsapp"
CHAVE = "5511988887777"


@pytest.fixture
async def cliente_http(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde de `app_com_token` em `test_rota_de_corretores.py`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro,
    entao o token tem de estar no ambiente ANTES do `create_app()`.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def _handoff(session: AsyncSession, handoff_id: uuid.UUID) -> Handoff:
    return (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()


async def _marcar_handoff(
    session: AsyncSession,
    *,
    handoff_id: uuid.UUID,
    status: Status | None = None,
    sla_limite_em: datetime | None = "sem_mudanca",  # type: ignore[assignment]
) -> None:
    """Sobrescreve status e/ou sla_limite_em direto no banco, fora da rota.

    Mesmo sentinela `"sem_mudanca"` de `test_rota_de_aceite.py`: distingue
    "nao mexer no campo" de "gravar None", que e valor valido para
    `sla_limite_em` (RN-16.3).
    """
    valores: dict[str, object] = {}
    if status is not None:
        valores["status"] = status.value
    if sla_limite_em != "sem_mudanca":
        valores["sla_limite_em"] = sla_limite_em
    if valores:
        await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(**valores))
        await session.commit()


async def test_assumir_silencia_e_devolve_200(cliente_http, semear_corretor) -> None:
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")

    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={
            "channel": CHANNEL,
            "conversation_key": CHAVE,
            "corretor_id": str(corretor.id),
        },
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "SILENCIADA"
    assert corpo["assumidoPor"] == str(corretor.id)
    assert datetime.fromisoformat(corpo["assumidoEm"])


async def test_assumir_sem_token_e_403(cliente_http) -> None:
    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(uuid.uuid4())},
    )
    assert resposta.status_code == 403


async def test_sem_token_configurado_a_rota_nao_existe(
    monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool
) -> None:
    """404 e nao 403: rota que nao existe nao pode ser exposta por engano.

    Gemeo de `test_importacao_http.py::test_sem_token_configurado_a_rota_nao_existe`.
    Esta rota governa quem fala com qual lead, entao o argumento da TEC-156
    (D1) vale aqui com mais forca, nao menos.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", "")
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/api/v1/conversas/assumir",
            json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(uuid.uuid4())},
            headers={"X-Admin-Token": TOKEN},
        )
    assert resposta.status_code == 404
    get_settings.cache_clear()


async def test_assumir_com_corretor_inexistente_e_404(cliente_http) -> None:
    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(uuid.uuid4())},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 404


async def test_assumir_com_corretor_inativo_e_recusado(cliente_http, semear_corretor) -> None:
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com", ativo=False)

    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 404


async def test_outro_corretor_recebe_409(cliente_http, semear_corretor) -> None:
    """O 409 do SRS: "ja assumida por outro"."""
    paulo = await semear_corretor(email=f"paulo-{uuid.uuid4().hex[:8]}@ex.com")
    marina = await semear_corretor(email=f"marina-{uuid.uuid4().hex[:8]}@ex.com")
    cabecalho = {"X-Admin-Token": TOKEN}
    corpo_base = {"channel": CHANNEL, "conversation_key": CHAVE}

    primeira = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json=corpo_base | {"corretor_id": str(paulo.id)},
        headers=cabecalho,
    )
    assert primeira.status_code == 200

    segunda = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json=corpo_base | {"corretor_id": str(marina.id)},
        headers=cabecalho,
    )
    assert segunda.status_code == 409


async def test_reassumir_pela_mesma_pessoa_e_200_e_nao_move_o_carimbo(
    cliente_http, semear_corretor
) -> None:
    """D3 do desenho da TEC-179: idempotente, `assumidoEm` fica onde estava."""
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    cabecalho = {"X-Admin-Token": TOKEN}
    corpo = {"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)}

    primeira = await cliente_http.post("/api/v1/conversas/assumir", json=corpo, headers=cabecalho)
    assert primeira.status_code == 200

    segunda = await cliente_http.post("/api/v1/conversas/assumir", json=corpo, headers=cabecalho)

    assert segunda.status_code == 200
    assert segunda.json()["assumidoEm"] == primeira.json()["assumidoEm"]


async def test_devolver_reativa_o_agente(cliente_http, semear_corretor) -> None:
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    cabecalho = {"X-Admin-Token": TOKEN}
    corpo = {"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)}

    assumida = await cliente_http.post("/api/v1/conversas/assumir", json=corpo, headers=cabecalho)
    assert assumida.status_code == 200

    devolvida = await cliente_http.post("/api/v1/conversas/devolver", json=corpo, headers=cabecalho)

    assert devolvida.status_code == 200
    resposta = devolvida.json()
    assert resposta["status"] == "REATIVADA"
    assert resposta["assumidoPor"] == str(corretor.id)


async def test_devolver_o_que_ninguem_assumiu_e_409(cliente_http, semear_corretor) -> None:
    """Corretor existente e ativo, para exercitar o 409 e nao o 404 da
    validacao acrescentada pela revisao -- ver `test_devolver_com_corretor_*`
    para os dois casos que o `corretor_id` invalido cobre.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")

    resposta = await cliente_http.post(
        "/api/v1/conversas/devolver",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 409


async def test_devolver_com_corretor_inexistente_e_404(cliente_http, semear_corretor) -> None:
    """Achado da revisao (Major): sem validar, um `corretor_id` inexistente
    numa conversa de fato assumida faz o UPDATE achar a linha e violar a FK
    `fk_atendimento_devolvido_por` -- 500 em vez de 404. `devolver` valida o
    corretor do mesmo jeito que `assumir` (`_corretor_apto`), fechando o
    buraco.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    cabecalho = {"X-Admin-Token": TOKEN}
    await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers=cabecalho,
    )

    resposta = await cliente_http.post(
        "/api/v1/conversas/devolver",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(uuid.uuid4())},
        headers=cabecalho,
    )

    assert resposta.status_code == 404


async def test_devolver_com_corretor_inativo_e_recusado(cliente_http, semear_corretor) -> None:
    """Mesmo desfecho que `assumir` da para corretor inativo -- 404, pela
    mesma `_corretor_apto`.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    inativo = await semear_corretor(email=f"i-{uuid.uuid4().hex[:8]}@ex.com", ativo=False)
    cabecalho = {"X-Admin-Token": TOKEN}
    await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers=cabecalho,
    )

    resposta = await cliente_http.post(
        "/api/v1/conversas/devolver",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(inativo.id)},
        headers=cabecalho,
    )

    assert resposta.status_code == 404


async def test_assumir_aceita_o_handoff_pendente_junto(
    cliente_http, session: AsyncSession, semear_corretor, semear_handoff_com_resumo
) -> None:
    """D6. Sem isto o corretor atende e a gerente e cobrada ao mesmo tempo."""
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal=CHANNEL, conversa=CHAVE)

    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 200
    linha = await _handoff(session, handoff_id)
    assert linha.status == Status.ACEITO
    assert linha.aceito_em is not None


async def test_assumir_aceita_tambem_o_handoff_ja_escalado(
    cliente_http, session: AsyncSession, semear_corretor, semear_handoff_com_resumo
) -> None:
    """Mesmo argumento da Emenda E-01 da secao 6.5: assumir depois da
    escalada e o caso real, porque a escalada existe para alguem pegar.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal=CHANNEL, conversa=CHAVE)
    await _marcar_handoff(session, handoff_id=handoff_id, status=Status.ESCALADO)

    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 200
    linha = await _handoff(session, handoff_id)
    assert linha.status == Status.ACEITO
    assert linha.aceito_em is not None


async def test_assumir_sem_handoff_nenhum_funciona(cliente_http, semear_corretor) -> None:
    """Nem toda conversa gerou handoff. Assumir nao pode exigir um."""
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")

    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers={"X-Admin-Token": TOKEN},
    )

    assert resposta.status_code == 200


async def test_handoff_aceito_ao_assumir_para_de_ser_varrido(
    cliente_http,
    session: AsyncSession,
    session_factory,
    semear_corretor,
    semear_handoff_com_resumo,
) -> None:
    """A prova de que a D6 fecha o buraco que ela promete fechar: um handoff
    com prazo vencido, aceito por ter sido assumido, deixa de ser escalado
    por `escalar_vencidos`.
    """
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal=CHANNEL, conversa=CHAVE)
    prazo_vencido = datetime.now(UTC) - timedelta(minutes=1)
    await _marcar_handoff(session, handoff_id=handoff_id, sla_limite_em=prazo_vencido)

    resposta = await cliente_http.post(
        "/api/v1/conversas/assumir",
        json={"channel": CHANNEL, "conversation_key": CHAVE, "corretor_id": str(corretor.id)},
        headers={"X-Admin-Token": TOKEN},
    )
    assert resposta.status_code == 200

    total = await escalar_vencidos(session_factory, canais=())

    assert total == 0
    linha = await _handoff(session, handoff_id)
    assert linha.status == Status.ACEITO

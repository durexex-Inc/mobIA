"""Um handoff por conversa enquanto ele nao se encerra. TEC-278."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import CANAL_AGENTE, CONVERSA_AGENTE
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.agente.schemas import Intencao
from mobia.domain.handoff.escalada import escalar_vencidos
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho, Status

TOKEN = "token-de-teste-um-handoff-por-conversa"


@pytest.fixture
async def cliente_http(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde de `cliente_http` em `test_rota_de_conversas.py`.

    So o terceiro cenario precisa da rota HTTP -- os outros tres ficam no
    nivel do turno e do modelo.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_lead_escalado_que_continua_conversando_nao_gera_handoff_novo(
    session: AsyncSession,
    session_factory,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Primeiro cenario, e a razao de existir da card.

    Monte: handoff PENDENTE pelo turno, prazo vencido, `escalar_vencidos`
    marca ESCALADO e devolve 1. Depois rode outro turno que dispare o
    gatilho de intencao.

    Assere DUAS coisas: `SELECT count(*) FROM handoffs` continua 1, e uma
    segunda passagem de `escalar_vencidos` devolve 0. So a primeira
    asserta passaria mesmo se o handoff novo nascesse e ainda nao tivesse
    vencido -- e a cobranca dupla da gerente e o dano que a card nomeia.
    """
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    await session.execute(
        update(Handoff)
        .where(Handoff.channel == CANAL_AGENTE, Handoff.conversation_key == CONVERSA_AGENTE)
        .values(sla_limite_em=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()

    primeira_escalada = await escalar_vencidos(session_factory, canais=())
    assert primeira_escalada == 1

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    contagem = (await session.execute(text("SELECT count(*) FROM handoffs"))).scalar_one()
    assert contagem == 1

    segunda_escalada = await escalar_vencidos(session_factory, canais=())
    assert segunda_escalada == 0


async def test_lead_aceito_que_continua_conversando_nao_gera_handoff_novo(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Segundo cenario. Aqui o handoff esta ACEITO, e o turno roda mesmo
    assim -- a conversa NAO foi silenciada (o aceite veio pela rota de
    handoffs, nao por `assumir`). E exatamente o caminho da L2 do desenho.
    """
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    await session.execute(
        update(Handoff)
        .where(Handoff.channel == CANAL_AGENTE, Handoff.conversation_key == CONVERSA_AGENTE)
        .values(status=Status.ACEITO.value)
    )
    await session.commit()

    entregador = outbound_fake()
    resultado = await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado != "atendimento_humano", "a conversa nao deveria estar silenciada"
    assert entregador.entregues, "o lead deixou de receber resposta"
    contagem = (await session.execute(text("SELECT count(*) FROM handoffs"))).scalar_one()
    assert contagem == 1


async def test_conversa_concluida_aceita_um_handoff_novo(
    session: AsyncSession,
    cliente_http,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Terceiro cenario, e a prova de que a valvula da Task 2 funciona.

    Um lead atendido meses atras que volta merece handoff novo. Conclua o
    handoff (assumir e depois devolver, pela rota de verdade) e rode um
    turno com gatilho: nasce linha nova, e sao 2 no total.
    """
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )

    corpo = {
        "channel": CANAL_AGENTE,
        "conversation_key": CONVERSA_AGENTE,
        "corretor_id": str(corretor.id),
    }
    cabecalho = {"X-Admin-Token": TOKEN}
    await cliente_http.post("/api/v1/conversas/assumir", json=corpo, headers=cabecalho)
    resposta = await cliente_http.post("/api/v1/conversas/devolver", json=corpo, headers=cabecalho)
    assert resposta.status_code == 200

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    contagem = (await session.execute(text("SELECT count(*) FROM handoffs"))).scalar_one()
    assert contagem == 2

    abertos = (
        await session.execute(text("SELECT count(*) FROM handoffs WHERE status != 'CONCLUIDO'"))
    ).scalar_one()
    assert abertos == 1


async def test_o_gatilho_novo_acumula_em_gatilhos_adicionais(
    session: AsyncSession,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """O que a mesclagem de fato faz com o gatilho que nao virou handoff.

    Nao e so "nada acontece": o `ON CONFLICT` acumula o gatilho novo em
    `gatilhos_adicionais` sem duplicar, e escala `prioridade` para ALTA
    quando e o caso. Este teste existe para que a proxima pessoa saiba onde
    o sinal foi parar -- ele nao se perde, so nao chega a ninguem (L1).

    Os dois primeiros gatilhos vem do turno de verdade (LEAD_QUENTE cria,
    VENDA_IMOVEL acumula). `PEDIDO_DE_HUMANO` ainda nao tem CHAMADOR fiado
    a turno nenhum (ver o comentario de `Gatilho` em
    `handoff/vocabulario.py`) -- a escalada para ALTA e o "sem duplicar"
    dele entram chamando `registrar_handoff` direto, a mesma funcao que o
    turno chama por baixo.
    """
    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
        texto="quero agendar visita",
    )
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    await registrar_handoff(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()
    # De novo, com o MESMO gatilho -- prova que nao duplica.
    await registrar_handoff(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
    )
    await session.commit()

    resultado = await session.execute(
        text("SELECT gatilho, etiqueta, gatilhos_adicionais, prioridade FROM handoffs")
    )
    linhas = resultado.mappings().all()
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["gatilho"] == "LEAD_QUENTE"
    assert linha["etiqueta"] == "lead-quente"
    assert linha["gatilhos_adicionais"] == ["VENDA_IMOVEL", "PEDIDO_DE_HUMANO"]
    assert linha["prioridade"] == "ALTA"

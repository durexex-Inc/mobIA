"""Criterios de aceite do TEC-190 como testes executaveis. RF-17.

Tres dos quatro cenarios do Gherkin da card. **O quarto -- "Agendamento novo
reflete no painel" (CA-17.1) -- NAO esta aqui e nao pode estar**: nao existe
tabela de agendamento neste repo, e marcar visita e RF-11 e RF-12, epicos nao
construidos. Nao ha como criar o "agendamento criado agora" que o Dado do
cenario exige.

Escrever o cenario com uma tabela inventada so para ele passar e o modo de
falha que o CLAUDE.md nomeia -- teste que inventa a entidade que falta para se
auto-satisfazer. O que se testa no lugar e que o campo sai declaradamente sem
fonte, no `test_o_painel_declara_que_nao_sabe_de_visitas` abaixo. A CA-17.1
volta quando a RF-12 existir. Ver a D1 do desenho.

O cenario "Carregamento dentro do SLA" vive em
`tests/perf/test_funil_latency.py`, fora do run padrao.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import _lead, _recomendar
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.metricas.filtros import montar_recorte

TOKEN = "token-do-criterio-de-aceite"
ROTA = "/api/v1/metricas/funil"
PERIODO = {"de": "2026-08-01", "ate": "2026-08-31"}
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
async def app_com_token(monkeypatch: Any, caches_de_cliente_limpos, banco_limpo, redis_pool):
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


async def test_funil_mostra_as_seis_etapas_com_conversao(app_com_token, session) -> None:
    """Cenario: Funil mostra as seis etapas com conversao."""
    await _lead(
        session,
        conversa="5511900000001",
        nasceu_em=DENTRO,
        falas=3,
        qualificado_em=DENTRO + timedelta(minutes=5),
    )
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO, falas=3)
    await _lead(session, conversa="5511900000003", nasceu_em=DENTRO, falas=1)
    await _recomendar(session, conversa="5511900000001", em=DENTRO)

    corpo = (await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})).json()

    assert len(corpo["etapas"]) == 6
    assert corpo["etapas"][0]["quantidade"] == 3
    assert corpo["etapas"][1]["quantidade"] == 2
    # 2 de 3 leads falaram mais de uma vez.
    assert corpo["etapas"][1]["conversaoDaAnterior"] == pytest.approx(2 / 3)
    assert corpo["etapas"][2]["conversaoDaAnterior"] == pytest.approx(1 / 2)


async def test_filtro_por_canal_recalcula_os_indicadores(app_com_token, session) -> None:
    """Cenario: Filtro por canal recalcula os indicadores.

    O Gherkin fala de "leads de WhatsApp e de web", e os dois existem aqui
    como dado semeado: so `whatsapp` e produzido pelo ingresso real hoje -- o
    canal web e a TEC-124, que nao existe. `messages.channel` e `String(32)`
    livre, entao a semeadura e fiel ao que a coluna aceita.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO, canal="whatsapp")
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO, canal="whatsapp")
    await _lead(session, conversa="5511900000003", nasceu_em=DENTRO, canal="web")

    todos = (await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})).json()
    so_whatsapp = (
        await app_com_token.get(
            ROTA, params={**PERIODO, "canal": "whatsapp"}, headers={"X-Admin-Token": TOKEN}
        )
    ).json()

    assert todos["indicadores"]["leadsNovos"] == 3
    assert so_whatsapp["indicadores"]["leadsNovos"] == 2
    assert so_whatsapp["etapas"][0]["quantidade"] == 2


async def test_o_painel_declara_que_nao_sabe_de_visitas(app_com_token, session) -> None:
    """No lugar da CA-17.1, que nao e exercitavel. Ver a docstring do modulo.

    O que se afirma aqui e o CONTRARIO de um contador de agendamento: que o
    painel diz nao ter fonte, em vez de dizer zero.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)

    corpo = (await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})).json()

    agendado = next(e for e in corpo["etapas"] if e["nome"] == "Agendado")
    assert agendado["quantidade"] is None
    assert agendado["disponivel"] is False
    assert corpo["indicadores"]["taxaNoShow"] is None
    assert "taxaNoShow" in corpo["indisponiveis"]


async def test_o_recorte_do_periodo_usa_o_fuso_da_operacao() -> None:
    """Nao e cenario do Gherkin -- e a fronteira que o Gherkin pressupoe.

    "Um periodo com leads" so significa alguma coisa se o periodo tiver
    fronteira definida, e a daqui e a de `settings.fuso_de_envio`.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO)

    assert recorte.inicio == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
    assert recorte.fim == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)

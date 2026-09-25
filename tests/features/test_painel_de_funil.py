"""Criterios de aceite do TEC-190 como testes executaveis. RF-17.

Os quatro cenarios do Gherkin da card, desde a TEC-376. **O quarto --
"Agendamento novo reflete no painel" (CA-17.1) -- passou tres emendas sem
teste**, e as duas razoes foram diferentes:

- ate a TEC-190, IMPOSSIBILIDADE: nao existia tabela de agendamento, e nao
  havia como criar o "agendamento criado agora" que o Dado exige. Escreve-lo
  contra uma tabela inventada seria o modo de falha que o CLAUDE.md nomeia --
  teste que inventa a entidade que falta para se auto-satisfazer. No lugar
  dele ficou a afirmacao CONTRARIA, de que o painel declarava nao ter fonte;
- depois da TEC-371, ESCOPO: a tabela tinha linha criada por lead de verdade
  e o painel continuava devolvendo nulo. A Emenda E-02 da CA-17.1 registrou
  isso com todas as letras -- "hoje o painel tem fonte e nao a usa".

A TEC-376 acabou com as duas, e o criterio virou o teste que ele sempre
descreveu.

O cenario "Carregamento dentro do SLA" vive em
`tests/perf/test_funil_latency.py`, fora do run padrao.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import _agendar, _corretor, _lead, _recomendar
from httpx import ASGITransport, AsyncClient

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
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

    **Os dois canais do Gherkin existem de verdade desde a TEC-124**, que
    mergeou na `main` em 24/09 e trouxe o widget web: `widget.py` grava
    `channel=CANAL_WEB` pelo mesmo `IngestionService` do webhook. Ate aquela
    card este teste semeava `"web"` como valor plausivel de uma coluna livre;
    agora ele semeia o valor que producao de fato escreve, e os literais
    saem de `messages/canais.py` para nao existir uma segunda grafia.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO, canal=CANAL_WHATSAPP)
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO, canal=CANAL_WHATSAPP)
    await _lead(session, conversa="5511900000003", nasceu_em=DENTRO, canal=CANAL_WEB)

    todos = (await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})).json()
    so_whatsapp = (
        await app_com_token.get(
            ROTA, params={**PERIODO, "canal": CANAL_WHATSAPP}, headers={"X-Admin-Token": TOKEN}
        )
    ).json()

    assert todos["indicadores"]["leadsNovos"] == 3
    assert so_whatsapp["indicadores"]["leadsNovos"] == 2
    assert so_whatsapp["etapas"][0]["quantidade"] == 2


async def test_o_agendamento_criado_aparece_no_contador_do_painel(app_com_token, session) -> None:
    """CA-17.1, exercitada pela primeira vez. Ver a docstring do modulo.

    "Dado um agendamento criado, quando o dashboard e recarregado, entao o
    contador de agendamentos reflete a mudanca." Os 60 segundos do criterio
    sao sobre cache do frontend -- a consulta nao tem nenhum, e o painel
    recarregado le o banco.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)

    antes = (await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})).json()
    await _agendar(session, conversa="5511900000001", corretor_id=corretor)
    depois = (
        await app_com_token.get(ROTA, params=PERIODO, headers={"X-Admin-Token": TOKEN})
    ).json()

    assert antes["indicadores"]["agendamentosCriados"] == 0
    assert depois["indicadores"]["agendamentosCriados"] == 1
    assert depois["indicadores"]["agendamentosConfirmados"] == 1

    agendado = next(e for e in depois["etapas"] if e["nome"] == "Agendado")
    assert agendado["quantidade"] == 1
    assert agendado["disponivel"] is True
    assert depois["indisponiveis"] == []


async def test_o_recorte_do_periodo_usa_o_fuso_da_operacao() -> None:
    """Nao e cenario do Gherkin -- e a fronteira que o Gherkin pressupoe.

    "Um periodo com leads" so significa alguma coisa se o periodo tiver
    fronteira definida, e a daqui e a de `settings.fuso_de_envio`.
    """
    recorte = montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO)

    assert recorte.inicio == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
    assert recorte.fim == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)

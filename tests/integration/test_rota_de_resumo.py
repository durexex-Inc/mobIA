"""A porta de entrada da regeneracao (D8) e o link da RN-15.5."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mobia.api.routes import handoffs as rota_de_handoffs
from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.handoff import resumo as resumo_mod
from mobia.domain.handoff.resumo import MARCADORES, link_da_transcricao
from mobia.infra.db import get_sessionmaker

TOKEN = "token-de-teste"


def _resumo_valido() -> str:
    return "\n".join(f"{marcador}\ntexto padrao de teste." for marcador in MARCADORES)


def _resumo_invalido() -> str:
    """Falta o ultimo marcador: `validar()` reprova e o redator levanta.

    Desde a TEC-176 isso nao produz mais um ramo de erro na rota -- o redator
    que falha cai no template deterministico e `gerar_resumo` grava mesmo
    assim. Este texto continua util para exercitar exatamente esse caminho.
    """
    return "\n".join(f"{marcador}\ntexto padrao de teste." for marcador in MARCADORES[:-1])


class _ClienteFalso:
    """Duble minimo do AsyncAnthropic. Mesmo molde de test_handoff_redator.py."""

    def __init__(self, texto: str) -> None:
        resposta = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=texto)],
            usage=SimpleNamespace(input_tokens=900, output_tokens=400),
            stop_reason="end_turn",
        )
        self.messages = SimpleNamespace(create=AsyncMock(return_value=resposta))


async def _cliente_com_redator(monkeypatch, redis_pool, *, texto_do_redator: str):
    """O corpo comum de `cliente_http` e `cliente_http_redator_falha`.

    O router so e registrado quando `catalogo_admin_token` e verdadeiro, entao
    o token tem de estar no ambiente ANTES do `create_app()`. O redator real
    fala com a Anthropic -- substituir `get_client` pela referencia que
    `resumo.py` guardou (mesmo molde de `tests/unit/test_handoff_redator.py`)
    isola o teste da rede sem precisar tornar o redator injetavel na rota.
    """
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    monkeypatch.setattr(resumo_mod, "get_client", lambda: _ClienteFalso(texto_do_redator))
    app = create_app()
    app.state.redis_pool = redis_pool
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente
    get_settings.cache_clear()


@pytest.fixture
async def cliente_http(monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool):
    """Molde do `app_com_token` de `test_busca_endpoint.py`, com redator valido."""
    async for cliente in _cliente_com_redator(
        monkeypatch, redis_pool, texto_do_redator=_resumo_valido()
    ):
        yield cliente


@pytest.fixture
async def cliente_http_redator_falha(
    monkeypatch, caches_de_cliente_limpos, banco_limpo, redis_pool
):
    """Mesmo app de `cliente_http`, mas o redator devolve um resumo invalido.

    Existe para o teste do fallback pela rota: o handoff precisa estar no
    banco e o redator precisa falhar de verdade, para provar que a rota
    devolve o template em vez de propagar o erro (RN-15.4, TEC-176).
    """
    async for cliente in _cliente_com_redator(
        monkeypatch, redis_pool, texto_do_redator=_resumo_invalido()
    ):
        yield cliente


async def test_sem_token_e_403(cliente_http) -> None:
    resposta = await cliente_http.post(f"/api/v1/handoffs/{uuid.uuid4()}/resumo")
    assert resposta.status_code == 403


async def test_handoff_inexistente_e_404(cliente_http) -> None:
    """O uuid nunca foi gravado -- este e o unico ramo "nao gravou" da rota.

    Antes da TEC-176 havia um segundo ramo (502, handoff existente com
    redator que falhou) que este mesmo `not gravou` escondia atras do
    booleano de `gerar_resumo`. Desde a TEC-176 esse redator que falha grava
    o template e devolve `gravou=True` -- ver `test_geracao_de_resumo.py` --,
    entao dossie ausente e a UNICA causa que sobra para este 404.
    """
    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/resumo", headers={"X-Admin-Token": TOKEN}
    )
    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "handoff nao existe"


async def test_regenera_com_falha_do_redator_devolve_o_template(
    cliente_http_redator_falha, semear_lead_completo
) -> None:
    """RN-15.4: mesmo pela rota de regeneracao manual, o corretor nao fica
    sem resumo -- o redator que falha (bloco ausente) grava o template
    deterministico e a rota devolve 200, nao mais 502.

    `resumoFallback` e a UNICA indicacao disso que existe hoje -- o painel e
    a E8 e nao existe -- entao e ela que prova o segundo cenario do Gherkin
    ("fica indicado que se trata de resumo automatico simplificado"), e nao
    so o texto do template.
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    resposta = await cliente_http_redator_falha.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["modelo"] is None
    assert corpo["resumoFallback"] is True
    assert "[resumo automatico simplificado" in corpo["resumo"]


async def test_regenera_e_devolve_o_resumo_com_o_link(cliente_http, semear_lead_completo) -> None:
    """Primeiro cenario do Gherkin: os seis blocos, o limite e o link."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["resumo"]) <= 1500
    # O link e campo separado, e nao conteudo do resumo -- ver a D10.
    assert corpo["link"].endswith("/conversas/whatsapp/5511911112222")
    assert corpo["link"] not in corpo["resumo"]
    # O caminho feliz precisa provar a AUSENCIA da marca, ou a asserta do
    # teste de fallback acima fica meio testada -- mesmo argumento da D5.
    assert corpo["resumoFallback"] is False


def test_o_link_nao_e_composto_pelo_modelo() -> None:
    assert link_da_transcricao("whatsapp", "5511911112222").endswith(
        "/conversas/whatsapp/5511911112222"
    )


async def _acessos() -> list[EventoAuditoria]:
    async with get_sessionmaker()() as sessao:
        return list(
            (
                await sessao.execute(
                    select(EventoAuditoria).where(EventoAuditoria.acao == "DADO_PESSOAL_ACESSADO")
                )
            ).scalars()
        )


async def test_o_acesso_ao_resumo_vai_para_a_trilha_sem_o_resumo(
    cliente_http, semear_lead_completo
) -> None:
    """TEC-206, D7: `campo = resumo`, e o texto nao aparece em coluna nenhuma."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    resposta = await cliente_http.post(
        f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
    )

    assert resposta.status_code == 200
    (evento,) = await _acessos()
    assert evento.campo == "resumo"
    assert evento.entidade == "handoff"
    assert evento.entidade_id == str(handoff_id)
    assert evento.ator_tipo == "USUARIO"
    assert evento.ator_id == "token-compartilhado"
    assert evento.correlation_id == resposta.headers["X-Request-Id"]
    colunas = [
        evento.entidade_id,
        evento.campo,
        evento.lead_ref,
        str(evento.detalhes),
        evento.correlation_id,
        str(evento.ip),
    ]
    assert all(resposta.json()["resumo"] not in (valor or "") for valor in colunas)
    assert all("5511911112222" not in (valor or "") for valor in colunas)


async def test_sem_registro_o_resumo_nao_sai(
    cliente_http, semear_lead_completo, monkeypatch
) -> None:
    """Review Focus 4: se a escrita da trilha falha, a resposta e erro."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    async def _falha(*_: object, **__: object) -> None:
        raise RuntimeError("trilha fora do ar")

    monkeypatch.setattr(rota_de_handoffs, "registrar_evento", _falha)

    with pytest.raises(RuntimeError, match="trilha fora do ar"):
        await cliente_http.post(
            f"/api/v1/handoffs/{handoff_id}/resumo", headers={"X-Admin-Token": TOKEN}
        )

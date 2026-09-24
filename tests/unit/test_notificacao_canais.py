"""O canal de WhatsApp que entrega ao corretor. TEC-281.

Ate a TEC-281 este arquivo testava o `WhatsAppRegistrado`, que nunca
entregava e nunca levantava. Ele foi apagado com aquela card, e o que se
prova aqui mudou de "registra e segue" para "entrega por template aprovado,
ou falha alto".
"""

import json
import logging

import httpx
import pytest

from mobia.app.config import get_settings
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.mensagem import Aviso
from mobia.domain.outbound.whatsapp_notificacao import WhatsAppTemplate

# O corpo carrega o resumo -- prosa destilada do que o lead escreveu. Toda
# asserta de ausencia deste arquivo usa esta constante, e ela e do TOPO do
# modulo de proposito: a guarda da TEC-289 so reduz agulha que seja literal,
# constante do proprio arquivo ou import de `mobia.*`. Uma agulha vinda do
# `conftest` reprovaria aquele meta-teste.
SENTINELA = "SENTINELA-CORPO o lead mora na Rua das Palmeiras"

TEMPLATE = "aviso_lead_pronto"


def um_aviso(template: str | None = TEMPLATE) -> Aviso:
    return Aviso(
        assunto="Lead pronto [quente] prioridade alta",
        corpo=SENTINELA,
        etiqueta="quente",
        prioridade="alta",
        link="https://painel.example/conversas/abc",
        template=template,
    )


def cliente_que_captura(capturado: dict[str, object]) -> httpx.AsyncClient:
    """Guarda o corpo enviado, para a asserta poder ler o que foi para a Meta."""

    def _responde(requisicao: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(requisicao.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(_responde))


def cliente_que_estoura(erro: Exception) -> httpx.AsyncClient:
    def _levanta(_: httpx.Request) -> httpx.Response:
        raise erro

    return httpx.AsyncClient(transport=httpx.MockTransport(_levanta))


@pytest.fixture
def com_template_aprovado(monkeypatch: pytest.MonkeyPatch):
    """Aprova o template e da um `phone_number_id`, como a operacao faria."""
    configuracao = get_settings()
    monkeypatch.setattr(configuracao, "whatsapp_templates_aprovados", TEMPLATE)
    monkeypatch.setattr(configuracao, "whatsapp_phone_number_id", "222222222")
    monkeypatch.setattr(configuracao, "whatsapp_access_token", "token-de-teste")
    yield configuracao


async def test_entrega_manda_template_e_nunca_texto(com_template_aprovado) -> None:
    """CA-1 e CA-2 da card: o payload e do tipo template, nunca text.

    `type: "text"` fora da janela de 24h e recusa garantida com o codigo
    131047 -- e o corretor esta SEMPRE fora dela, porque nao conversa com o
    numero da empresa.
    """
    corpo: dict[str, object] = {}
    canal = WhatsAppTemplate(cliente=cliente_que_captura(corpo))

    await canal.enviar(destino="5511999998888", aviso=um_aviso())

    assert corpo["type"] == "template"
    assert corpo["type"] != "text"
    assert corpo["template"]["name"] == TEMPLATE  # type: ignore[index]


async def test_os_parametros_sao_etiqueta_prioridade_e_link(com_template_aprovado) -> None:
    corpo: dict[str, object] = {}
    canal = WhatsAppTemplate(cliente=cliente_que_captura(corpo))

    await canal.enviar(destino="5511999998888", aviso=um_aviso())

    parametros = corpo["template"]["components"][0]["parameters"]  # type: ignore[index]
    assert [p["text"] for p in parametros] == [
        "quente",
        "alta",
        "https://painel.example/conversas/abc",
    ]


async def test_o_resumo_nunca_vai_no_payload(com_template_aprovado) -> None:
    """A Meta revisa template humano por humano -- o resumo nao cabe e nao vai.

    E a razao pela qual a RN-16.2 precisa de emenda: os dois canais nao sao
    equivalentes, o e-mail leva o resumo e o WhatsApp leva o aviso.
    """
    corpo: dict[str, object] = {}
    canal = WhatsAppTemplate(cliente=cliente_que_captura(corpo))

    await canal.enviar(destino="5511999998888", aviso=um_aviso())

    assert SENTINELA not in json.dumps(corpo)


async def test_trocar_o_template_nao_exige_deploy(com_template_aprovado, monkeypatch) -> None:
    """CA-4 da card: o nome do template e dado, nao literal no codigo."""
    outro = "aviso_lead_pronto_v2"
    monkeypatch.setattr(com_template_aprovado, "whatsapp_templates_aprovados", outro)
    corpo: dict[str, object] = {}
    canal = WhatsAppTemplate(cliente=cliente_que_captura(corpo))

    await canal.enviar(destino="5511999998888", aviso=um_aviso(template=outro))

    assert corpo["template"]["name"] == outro  # type: ignore[index]


async def test_aviso_sem_template_falha_alto_e_loga(
    com_template_aprovado, caplog: pytest.LogCaptureFixture
) -> None:
    """D3 do desenho: explicito e barulhento, nunca fallback silencioso.

    O log nao e redundante com a excecao: `notificar` so imprime `motivos`
    quando NENHUM canal aceita, entao com o e-mail entregando esta falha nao
    apareceria em lugar nenhum.
    """
    canal = WhatsAppTemplate(cliente=cliente_que_captura({}))

    with caplog.at_level(logging.WARNING), pytest.raises(FalhaDeCanal):
        await canal.enviar(destino="5511999998888", aviso=um_aviso(template=None))

    assert "notificacao.whatsapp_sem_template" in caplog.text
    assert SENTINELA not in caplog.text


async def test_template_fora_dos_aprovados_falha_alto(
    com_template_aprovado, caplog: pytest.LogCaptureFixture
) -> None:
    """Configurar um nome nao basta: a Meta tem de te-lo aprovado."""
    canal = WhatsAppTemplate(cliente=cliente_que_captura({}))

    with caplog.at_level(logging.WARNING), pytest.raises(FalhaDeCanal):
        await canal.enviar(destino="5511999998888", aviso=um_aviso(template="nao_aprovado"))

    assert "nao esta entre os aprovados" in caplog.text


async def test_falha_da_cloud_api_vira_falha_de_canal(
    com_template_aprovado, caplog: pytest.LogCaptureFixture
) -> None:
    """CA-3 da card: o orquestrador precisa disto para tentar o e-mail do mesmo jeito."""
    canal = WhatsAppTemplate(cliente=cliente_que_estoura(httpx.ConnectError("sem rede")))

    with caplog.at_level(logging.WARNING), pytest.raises(FalhaDeCanal):
        await canal.enviar(destino="5511999998888", aviso=um_aviso())

    assert "notificacao.whatsapp_recusado" in caplog.text
    assert SENTINELA not in caplog.text


async def test_status_de_erro_tambem_vira_falha_de_canal(com_template_aprovado) -> None:
    """Um 400 da Meta e recusa tanto quanto um erro de rede."""
    cliente = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(400, json={"error": {}}))
    )
    canal = WhatsAppTemplate(cliente=cliente)

    with pytest.raises(FalhaDeCanal):
        await canal.enviar(destino="5511999998888", aviso=um_aviso())

import json
import uuid

import httpx
import pytest

from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRecusado, EnvioRetentavel
from mobia.domain.outbound.whatsapp import WhatsAppOutbound
from mobia.infra.db import get_sessionmaker

PAYLOAD = {"para": "5511911112222", "de": "222222222", "texto": "Ola! Em qual regiao voce procura?"}


def cliente_que_responde(resposta: httpx.Response) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _: resposta))


def cliente_que_estoura(erro: Exception) -> httpx.AsyncClient:
    def _levanta(_: httpx.Request) -> httpx.Response:
        raise erro

    return httpx.AsyncClient(transport=httpx.MockTransport(_levanta))


async def entregar(cliente: httpx.AsyncClient) -> None:
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente)
    await outbound._deliver(uuid.uuid4(), "reply", PAYLOAD)


async def test_entrega_bem_sucedida_nao_levanta(session) -> None:
    await entregar(
        cliente_que_responde(httpx.Response(200, json={"messages": [{"id": "wamid.X"}]}))
    )


async def test_erro_de_rede_e_retentavel(session) -> None:
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_estoura(httpx.ConnectError("sem rota")))


async def test_5xx_e_retentavel(session) -> None:
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_responde(httpx.Response(503, json={})))


async def test_429_e_retentavel(session) -> None:
    """429 e 4xx na faixa numerica, mas e o servidor pedindo para tentar depois.

    Nao e o cliente que errou -- classificar como permanente perde a resposta
    ao lead para sempre.
    """
    with pytest.raises(EnvioRetentavel):
        await entregar(
            cliente_que_responde(
                httpx.Response(429, json={"error": {"code": 4, "message": "rate limit"}})
            )
        )


async def test_408_e_retentavel(session) -> None:
    """Mesmo raciocinio do 429: timeout do servidor nao e payload invalido."""
    with pytest.raises(EnvioRetentavel):
        await entregar(cliente_que_responde(httpx.Response(408, json={})))


async def test_4xx_comum_e_recusa_permanente(session) -> None:
    """Payload invalido nao melhora com retentativa."""
    with pytest.raises(EnvioRecusado) as exc_info:
        await entregar(
            cliente_que_responde(
                httpx.Response(400, json={"error": {"code": 100, "message": "invalido"}})
            )
        )

    # A classificacao de tres vias e o ponto central desta tarefa: um 4xx
    # comum precisa cair no tipo base, nunca no subtipo de janela expirada.
    assert type(exc_info.value) is EnvioRecusado


async def test_fora_da_janela_de_24h_tem_excecao_propria(session) -> None:
    """Codigo 131047 da Meta: passaram mais de 24h desde a ultima fala do lead.

    Precisa ser distinguivel de um 4xx comum porque o turno termina como
    PROCESSED com log de aviso, nao como erro de payload.
    """
    with pytest.raises(EnvioForaDaJanela):
        await entregar(
            cliente_que_responde(
                httpx.Response(400, json={"error": {"code": 131047, "message": "reengagement"}})
            )
        )


async def test_erro_da_meta_nao_carrega_o_texto_no_log(session, caplog) -> None:
    """O texto enviado e fala do agente para o lead, e nao pode ir para o log."""
    import logging

    with caplog.at_level(logging.WARNING):
        with pytest.raises(EnvioRecusado):
            await entregar(
                cliente_que_responde(
                    httpx.Response(400, json={"error": {"code": 100, "message": "invalido"}})
                )
            )

    assert "Em qual regiao" not in caplog.text


PAYLOAD_DE_IMAGEM = {
    "tipo": "imagem",
    "para": "5511911112222",
    "de": "222222222",
    "link": "https://exemplo.com/ap-1004-1.jpg",
    "legenda": "Apartamento em Lagoa da Conceicao\nLagoa da Conceicao - R$ 516.464",
}


def cliente_que_captura(capturado: dict[str, object]) -> httpx.AsyncClient:
    """Guarda o corpo enviado para a asserta poder ler o que foi para a Meta."""

    def _responde(requisicao: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(requisicao.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(_responde))


async def test_payload_sem_tipo_continua_saindo_como_texto(session) -> None:
    """A retrocompatibilidade dos tres chamadores de hoje, afirmada.

    `turno.py`, `_entregar_texto_fixo` e os caminhos de follow-up mandam
    payload sem `tipo`. Se este teste falhar, a TEC-162 quebrou a resposta
    normal do agente -- que e todo turno que nao apresenta imovel.
    """
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente_que_captura(corpo))
    await outbound._deliver(uuid.uuid4(), "reply", PAYLOAD)

    assert corpo["type"] == "text"
    assert corpo["text"] == {"body": PAYLOAD["texto"]}


async def test_payload_de_imagem_sai_como_image_com_link_e_caption(session) -> None:
    """RN-10.2: uma imagem por imovel com legenda estruturada."""
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente_que_captura(corpo))
    await outbound._deliver(uuid.uuid4(), "ficha_1", PAYLOAD_DE_IMAGEM)

    assert corpo["type"] == "image"
    assert corpo["image"] == {
        "link": PAYLOAD_DE_IMAGEM["link"],
        "caption": PAYLOAD_DE_IMAGEM["legenda"],
    }


async def test_indicador_monta_o_corpo_que_a_meta_exige(session) -> None:
    """O corpo do indicador nao e um envio de mensagem. TEC-274.

    `status: "read"` nao e opcional -- a Meta nao oferece "digitando..."
    isolado, e e por isso que a Emenda E-01 da RN-04.7 registra que o
    indicador marca a fala do lead como lida. Este teste e o unico lugar que
    exercita o corpo: errar uma chave aqui e uma feature que nao funciona em
    producao e passa em todo o resto da suite.
    """
    from mobia.domain.outbound.whatsapp import WhatsAppIndicador

    corpo: dict[str, object] = {}
    indicador = WhatsAppIndicador(cliente=cliente_que_captura(corpo))
    await indicador.indicar_digitacao(provider_message_id="wamid.ABC", de="222222222")

    assert corpo["messaging_product"] == "whatsapp"
    assert corpo["status"] == "read"
    assert corpo["message_id"] == "wamid.ABC"
    assert corpo["typing_indicator"] == {"type": "text"}
    # O indicador nao e mensagem: nenhuma das chaves de envio pode aparecer,
    # ou a Meta recusa o corpo inteiro.
    assert "to" not in corpo
    assert "type" not in corpo


async def test_indicador_usa_o_numero_do_canal_na_url(session) -> None:
    """A URL leva o `phone_number_id`, que mora em `recipient_external_id`."""
    from mobia.domain.outbound.whatsapp import WhatsAppIndicador

    urls: list[str] = []

    def _responde(requisicao: httpx.Request) -> httpx.Response:
        urls.append(str(requisicao.url))
        return httpx.Response(200, json={"success": True})

    indicador = WhatsAppIndicador(
        cliente=httpx.AsyncClient(transport=httpx.MockTransport(_responde))
    )
    await indicador.indicar_digitacao(provider_message_id="wamid.ABC", de="222222222")

    assert urls[0].endswith("/222222222/messages")


async def test_indicador_recusado_nao_levanta(session) -> None:
    """A D6 do desenho: toda falha e a mesma falha, e nenhuma escapa daqui.

    Nao ha reserva a liberar nem retentativa a decidir, entao 4xx e 5xx nao
    precisam ser distinguidos -- ao contrario de `_deliver`, onde o TIPO da
    excecao decide o desfecho do turno.
    """
    from mobia.domain.outbound.whatsapp import WhatsAppIndicador

    indicador = WhatsAppIndicador(
        cliente=cliente_que_responde(httpx.Response(400, json={"error": {"code": 100}}))
    )
    await indicador.indicar_digitacao(provider_message_id="wamid.ABC", de="222222222")


async def test_envio_por_template_monta_o_corpo_da_cloud_api(session) -> None:
    """TEC-186: fora da janela, o corpo e type=template com name/language/body."""
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente_que_captura(corpo))
    await outbound._deliver(
        uuid.uuid4(),
        "followup_2",
        {
            "para": "5511911112222",
            "de": "222222222",
            "tipo": "template",
            "template": "followup_queda_de_preco",
            "idioma": "pt_BR",
            "parametros": ["Apartamento", "R$ 620.000", "R$ 590.000"],
        },
    )
    assert corpo["type"] == "template"
    template = corpo["template"]
    assert template["name"] == "followup_queda_de_preco"
    assert template["language"] == {"code": "pt_BR"}
    body = template["components"][0]
    assert body["type"] == "body"
    assert [p["text"] for p in body["parameters"]] == ["Apartamento", "R$ 620.000", "R$ 590.000"]


async def test_template_sem_parametros_nao_manda_components(session) -> None:
    """O convite nao tem placeholder: um `components` de corpo vazio seria recusado."""
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente_que_captura(corpo))
    await outbound._deliver(
        uuid.uuid4(),
        "followup_1",
        {
            "para": "5511911112222",
            "de": "222222222",
            "tipo": "template",
            "template": "followup_convite",
            "idioma": "pt_BR",
            "parametros": [],
        },
    )
    assert "components" not in corpo["template"]

"""Cenarios Gherkin de TEC-132.

Funcionalidade: Registrar midia recebida sem interpretar o conteudo

O caminho inteiro roda pelos tres estagios reais, como
`test_recepcao_de_mensagem.py` e `test_historico_unificado.py` ja fazem para
os deles: o envelope da Meta entra pela rota do webhook, `process_message`
roda o turno com os dubles de `_ctx()`, e `baixar_midia` roda contra uma Graph
API falsa (`httpx.MockTransport`) e um `ArmazemLocal(tmp_path)`. Publicar a
mao em `midias_recebidas` ou chamar `executar_turno` direto testaria o
dominio, e nao o recebimento ponta a ponta que a card pede.
"""

import json
from typing import Any

import httpx
from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agente.identificacao import SEPARADOR_DA_IDENTIFICACAO, TEXTO_DA_IDENTIFICACAO
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.identidade.indice import chave_de
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.confirmacao import (
    TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO,
    TEXTO_DA_CONFIRMACAO_DE_IMAGEM,
)
from mobia.domain.midia.models import MidiaRecebida, MotivoDaMidia, StatusDaMidia
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.db import get_sessionmaker
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature
from mobia.workers.jobs.baixar_midia import baixar_midia
from mobia.workers.jobs.process_message import process_message

TELEFONE = "5511911112222"

# Bytes quaisquer: nenhum cenario desta suite confere sha256 -- o envelope de
# teste nunca traz o digest, e sem ele `baixar_midia` pula a conferencia (D3).
DADOS_DA_MIDIA = b"\xff\xd8\xff" + b"conteudo de teste" * 4

URL_DA_META = "https://lookaside.fbsbx.com/x"


def _envelope(*, tipo: str, midia: dict[str, Any], provider_message_id: str) -> dict[str, Any]:
    mensagem = {
        "from": TELEFONE,
        "id": provider_message_id,
        "timestamp": "1758700000",
        "type": tipo,
        tipo: midia,
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [mensagem],
                        },
                    }
                ],
            }
        ],
    }


def _envelope_de_imagem(
    provider_message_id: str, media_id: str, *, mime: str = "image/jpeg"
) -> dict[str, Any]:
    return _envelope(
        tipo="image",
        midia={"id": media_id, "mime_type": mime},
        provider_message_id=provider_message_id,
    )


def _envelope_de_documento(
    provider_message_id: str, media_id: str, *, mime: str = "application/pdf"
) -> dict[str, Any]:
    # O `filename` chega no envelope e fica cifrado em `raw_payload` -- a D2
    # da spec decidiu que ele nao vira coluna propria.
    return _envelope(
        tipo="document",
        midia={"id": media_id, "mime_type": mime, "filename": "contrato.pdf"},
        provider_message_id=provider_message_id,
    )


def _corpo_assinado(envelope: dict[str, Any], secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(envelope).encode("utf-8")
    return body, {
        SIGNATURE_HEADER: compute_signature(secret, body),
        "Content-Type": "application/json",
    }


def _com_identificacao(texto: str) -> str:
    """A confirmacao herda a apresentacao do agente no primeiro contato (D4).

    Todo numero destes cenarios chega novo -- `banco_limpo` trunca antes de
    cada teste --, entao `e_conversa_nova` e sempre verdadeiro e todo texto
    fixo que `_entregar_texto_fixo` entrega vem com este prefixo na frente.
    """
    return f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{texto}"


class WhatsAppQueRegistra:
    """A porta da Meta que registra o envio em vez de falar com a rede de
    verdade -- mesmo duble de `test_historico_unificado.py`."""

    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.envios.append(payload)
        return True


def _ctx_do_turno(whatsapp: Any, classificador: Any) -> dict[str, Any]:
    """O `ctx` que `workers/main.py` monta para `process_message`, com dubles
    no lugar dos modelos -- mesmo padrao de `test_atendimento_pelo_widget_web.py`."""
    return {
        "session_factory": get_sessionmaker(),
        "outbound": whatsapp,
        "classificador": classificador,
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "agendador_de_avisos": AgendadorDeAvisosNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop()},
    }


def _cliente_da_meta(
    *, mime: str = "image/jpeg", status_resolucao: int = 200, status_download: int = 200
) -> httpx.AsyncClient:
    """Duble minimo da Graph API (D3): o primeiro GET (no `media_id`) resolve
    a URL temporaria, o segundo (na URL) entrega os bytes -- mesma forma de
    `tests/integration/test_baixar_midia.py`, simplificada para o que estes
    cenarios precisam."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == URL_DA_META:
            return httpx.Response(status_download, content=DADOS_DA_MIDIA)
        return httpx.Response(status_resolucao, json={"url": URL_DA_META, "mime_type": mime})

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _ctx_do_job(cliente: httpx.AsyncClient, armazem: Any, settings: Any) -> dict[str, Any]:
    return {
        "session_factory": get_sessionmaker(),
        "settings": settings,
        "armazem": armazem,
        "cliente_http_da_meta": cliente,
    }


async def _linha_da_mensagem(session, provider_message_id: str) -> Message:
    return (
        await session.execute(
            select(Message).where(Message.provider_message_id == provider_message_id)
        )
    ).scalar_one()


async def _midia(session, message_id) -> MidiaRecebida:
    # A linha foi gravada por outra sessao (a de `process_message`/
    # `baixar_midia`, que vem de `get_sessionmaker()`), entao a sessao do
    # teste precisa expirar o que tinha em cache antes de reler -- mesmo
    # cuidado de `_linha` em `test_baixar_midia.py`.
    session.expire_all()
    linha = await session.get(MidiaRecebida, message_id)
    assert linha is not None
    return linha


async def test_reconhecer_imagem_recebida_sem_interpretar(
    client, session, settings, tmp_path
) -> None:
    """Cenario: Reconhecer imagem recebida sem interpretar o conteudo.

    A linha vira IMAGEM, o classificador nunca e chamado -- a garantia de "nao
    interpretar" e nao ter chamada nenhuma ao modelo --, o texto que sai e o
    fixo de imagem, e `midias_recebidas` fecha ARMAZENADA depois do job.
    """
    envelope = _envelope_de_imagem("wamid.IMG1", "media-imagem-1")
    body, headers = _corpo_assinado(envelope, settings.whatsapp_app_secret)

    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200

    linha = await _linha_da_mensagem(session, "wamid.IMG1")
    assert linha.content_type == MessageContentType.IMAGEM
    assert linha.status == MessageStatus.QUEUED
    message_id = linha.id

    classificador = ClassificadorFake()
    whatsapp = WhatsAppQueRegistra()
    resultado = await process_message(_ctx_do_turno(whatsapp, classificador), str(message_id))

    assert resultado == "respondido"
    assert classificador.chamadas == 0, "midia sem texto nao pode chamar o modelo"
    # TEC-203: `para` e a chave do lead, nao o `wa_id` cru -- e' o `wa_id` que
    # `WhatsAppOutbound._deliver` revela na hora do POST de verdade.
    assert whatsapp.envios == [
        {
            "para": chave_de(CANAL_WHATSAPP, TELEFONE),
            "de": "222222222",
            "texto": _com_identificacao(TEXTO_DA_CONFIRMACAO_DE_IMAGEM),
        }
    ]

    resultado_do_job = await baixar_midia(
        _ctx_do_job(_cliente_da_meta(), ArmazemLocal(tmp_path), settings), str(message_id)
    )
    assert resultado_do_job == "armazenada"
    assert (await _midia(session, message_id)).status == StatusDaMidia.ARMAZENADA


async def test_pedir_por_texto_a_informacao_que_a_midia_traria(
    client, session, settings, tmp_path
) -> None:
    """Cenario: Pedir por texto a informacao que a midia traria.

    Sem nenhum texto do lead na rajada, a imagem recebe uma pergunta -- e nao
    silencio, nem uma descricao inventada do que a imagem mostraria.
    """
    envelope = _envelope_de_imagem("wamid.IMG2", "media-imagem-2")
    body, headers = _corpo_assinado(envelope, settings.whatsapp_app_secret)

    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200

    linha = await _linha_da_mensagem(session, "wamid.IMG2")
    message_id = linha.id
    whatsapp = WhatsAppQueRegistra()
    resultado = await process_message(_ctx_do_turno(whatsapp, ClassificadorFake()), str(message_id))

    assert resultado == "respondido"
    [envio] = whatsapp.envios
    assert "me conta em texto" in envio["texto"].lower()

    resultado_do_job = await baixar_midia(
        _ctx_do_job(_cliente_da_meta(), ArmazemLocal(tmp_path), settings), str(message_id)
    )
    assert resultado_do_job == "armazenada"


async def test_documento_recebido_segue_a_mesma_regra(client, session, settings, tmp_path) -> None:
    """Cenario: Documento recebido segue a mesma regra.

    PDF vira DOCUMENTO, fecha ARMAZENADA depois do job, e o texto fixo e o de
    documento -- nao o de imagem.
    """
    envelope = _envelope_de_documento("wamid.DOC1", "media-doc-1")
    body, headers = _corpo_assinado(envelope, settings.whatsapp_app_secret)

    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200

    linha = await _linha_da_mensagem(session, "wamid.DOC1")
    assert linha.content_type == MessageContentType.DOCUMENTO
    message_id = linha.id

    whatsapp = WhatsAppQueRegistra()
    resultado = await process_message(_ctx_do_turno(whatsapp, ClassificadorFake()), str(message_id))

    assert resultado == "respondido"
    assert whatsapp.envios[0]["texto"] == _com_identificacao(TEXTO_DA_CONFIRMACAO_DE_DOCUMENTO)

    resultado_do_job = await baixar_midia(
        _ctx_do_job(_cliente_da_meta(mime="application/pdf"), ArmazemLocal(tmp_path), settings),
        str(message_id),
    )
    assert resultado_do_job == "armazenada"
    assert (await _midia(session, message_id)).status == StatusDaMidia.ARMAZENADA


async def test_confirmacao_sai_mesmo_quando_o_download_falha_depois(
    client, session, settings, tmp_path
) -> None:
    """Review Focus 5: a confirmacao nao depende do download (D3/D4).

    A Graph API recusa a resolucao com 404 -- midia expirada ou token
    invalido, RECUSADA_PELA_META -- e mesmo assim a confirmacao ja tinha
    saido: `midias_recebidas` fecha FALHOU e a mensagem fecha PROCESSED, sem
    que nada disso desfaca ou espere a resposta que o turno ja deu.
    """
    envelope = _envelope_de_imagem("wamid.IMG404", "media-expirada")
    body, headers = _corpo_assinado(envelope, settings.whatsapp_app_secret)

    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200

    linha = await _linha_da_mensagem(session, "wamid.IMG404")
    message_id = linha.id
    whatsapp = WhatsAppQueRegistra()
    resultado = await process_message(_ctx_do_turno(whatsapp, ClassificadorFake()), str(message_id))

    assert resultado == "respondido"
    assert whatsapp.envios[0]["texto"] == _com_identificacao(TEXTO_DA_CONFIRMACAO_DE_IMAGEM)

    resultado_do_job = await baixar_midia(
        _ctx_do_job(_cliente_da_meta(status_resolucao=404), ArmazemLocal(tmp_path), settings),
        str(message_id),
    )
    assert resultado_do_job == "falhou"
    midia = await _midia(session, message_id)
    assert midia.status == StatusDaMidia.FALHOU
    assert midia.motivo == MotivoDaMidia.RECUSADA_PELA_META

    session.expire_all()
    mensagem = await session.get(Message, message_id)
    assert mensagem is not None
    assert mensagem.status == MessageStatus.PROCESSED

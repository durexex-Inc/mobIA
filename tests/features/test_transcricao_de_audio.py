"""Cenarios Gherkin de TEC-131.

Funcionalidade: Transcricao de audio recebido

Ponta a ponta pelos estagios reais, como `test_recebimento_de_midia.py`: o
envelope entra pela rota do webhook; o primeiro `process_message` encontra o
audio sem transcricao e espera (D1); `transcrever_audio` roda contra uma Graph
API falsa, um `ArmazemLocal(tmp_path)` e o `TranscritorFake`; e o segundo
`process_message` -- o que o job acordou -- responde.
"""

import json
from typing import Any

import httpx
from conftest import (
    ClassificadorFake,
    ContadorFake,
    ModeradorFake,
    ResumidorFake,
    TranscritorFake,
    ogg_opus,
    pmid_do_whatsapp,
)
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.agente.identificacao import SEPARADOR_DA_IDENTIFICACAO, TEXTO_DA_IDENTIFICACAO
from mobia.domain.context.montagem import _texto_das
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.models import Message
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.confirmacao import TEXTO_DO_AUDIO_LONGO, TEXTO_DO_AUDIO_NAO_TRANSCRITO
from mobia.domain.midia.models import (
    MidiaRecebida,
    MotivoDaTranscricao,
    StatusDaMidia,
    StatusDaTranscricao,
)
from mobia.domain.midia.transcricao import TranscricaoIndisponivel
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature
from mobia.workers.jobs.process_message import process_message
from mobia.workers.jobs.transcrever_audio import transcrever_audio

TELEFONE = "5511955556666"
URL_DA_META = "https://lookaside.fbsbx.com/audio"
FALA = "oi, eu procuro um apartamento de 2 quartos"


def _envelope_de_audio(provider_message_id: str) -> dict[str, Any]:
    mensagem = {
        "from": TELEFONE,
        "id": provider_message_id,
        "timestamp": "1758700000",
        "type": "audio",
        "audio": {"id": f"media-{provider_message_id}", "mime_type": "audio/ogg; codecs=opus"},
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


class WhatsAppQueRegistra:
    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.envios.append(payload)
        return True


class ClassificadorQueGuarda(ClassificadorFake):
    """Guarda o contexto que o turno montou: e onde se ve o que o modelo leu."""

    def __init__(self) -> None:
        super().__init__()
        self.contextos: list[Any] = []

    async def classificar(self, contexto, *, porta=None):
        self.contextos.append(contexto)
        return await super().classificar(contexto, porta=porta)


class FilaQueRegistra:
    def __init__(self) -> None:
        self.acordados: list[str] = []

    async def enqueue_job(self, nome: str, *args: Any, **_: Any):
        self.acordados.append(args[0])
        return object()


def _ctx_do_turno(whatsapp: Any, classificador: Any) -> dict[str, Any]:
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


def _ctx_do_job(
    dados: bytes, tmp_path, settings, transcritor: TranscritorFake, fila: FilaQueRegistra
) -> dict[str, Any]:
    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == URL_DA_META:
            return httpx.Response(200, content=dados)
        return httpx.Response(200, json={"url": URL_DA_META, "mime_type": "audio/ogg"})

    return {
        "session_factory": get_sessionmaker(),
        "settings": settings,
        "armazem": ArmazemLocal(tmp_path),
        "cliente_http_da_meta": httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
        "transcritor": transcritor,
        "redis": fila,
    }


def _com_identificacao(texto: str) -> str:
    return f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{texto}"


async def _receber(client, session, settings, provider_message_id: str) -> Message:
    body = json.dumps(_envelope_de_audio(provider_message_id)).encode("utf-8")
    headers = {
        SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body),
        "Content-Type": "application/json",
    }
    resposta = await client.post("/webhooks/whatsapp", content=body, headers=headers)
    assert resposta.status_code == 200
    procurado = pmid_do_whatsapp(provider_message_id)
    linha = (
        await session.execute(select(Message).where(Message.provider_message_id == procurado))
    ).scalar_one()
    assert linha.content_type == MessageContentType.AUDIO
    return linha


async def _processar(
    client,
    session,
    settings,
    tmp_path,
    *,
    provider_message_id: str,
    segundos: float,
    transcritor: TranscritorFake,
    classificador: Any,
    whatsapp: WhatsAppQueRegistra,
) -> tuple[Message, str]:
    """Webhook, turno que espera, transcricao, turno acordado. Devolve a linha
    e o desfecho do segundo turno."""
    linha = await _receber(client, session, settings, provider_message_id)
    ctx_do_turno = _ctx_do_turno(whatsapp, classificador)

    # O debounce enfileira o turno junto com a transcricao, e o turno chega
    # primeiro: ele espera, sem reivindicar nada, e sem mandar nada.
    assert await process_message(ctx_do_turno, str(linha.id)) == "aguardando_transcricao"
    assert whatsapp.envios == []

    fila = FilaQueRegistra()
    await transcrever_audio(
        _ctx_do_job(ogg_opus(segundos), tmp_path, settings, transcritor, fila), str(linha.id)
    )
    # O job acorda o turno -- do proprio audio, que e a mensagem mais nova.
    assert fila.acordados == [str(linha.id)]

    return linha, await process_message(ctx_do_turno, str(linha.id))


async def _midia(session, message_id) -> MidiaRecebida:
    session.expire_all()
    linha = await session.get(MidiaRecebida, message_id)
    assert linha is not None
    return linha


async def test_audio_dentro_do_limite_e_atendido_como_texto(
    client, session, settings, tmp_path
) -> None:
    """Cenario: Audio dentro do limite e atendido como texto.

    Dado um audio de 40 segundos em que o lead diz que procura apartamento de 2
    quartos: a transcricao fica registrada junto a mensagem, e o agente responde
    considerando o conteudo falado -- o contexto que chega ao modelo carrega a
    fala transcrita.
    """
    classificador = ClassificadorQueGuarda()
    whatsapp = WhatsAppQueRegistra()

    linha, resultado = await _processar(
        client,
        session,
        settings,
        tmp_path,
        provider_message_id="wamid.AUD40",
        segundos=40.0,
        transcritor=TranscritorFake(FALA),
        classificador=classificador,
        whatsapp=whatsapp,
    )

    assert resultado == "respondido"
    gravada = await session.get(Message, linha.id, populate_existing=True)
    assert gravada is not None
    assert decrypt(gravada.text_body, aad_de(gravada.id, "text_body")) == FALA
    midia = await _midia(session, linha.id)
    assert midia.status_da_transcricao == StatusDaTranscricao.TRANSCRITA
    assert midia.status == StatusDaMidia.ARMAZENADA

    assert classificador.chamadas == 1
    [contexto] = classificador.contextos
    lido_pelo_modelo = _texto_das(contexto.literais)
    assert "(audio transcrito)" in lido_pelo_modelo
    assert FALA in lido_pelo_modelo
    assert len(whatsapp.envios) == 1


async def test_audio_longo_e_recusado_com_cordialidade(client, session, settings, tmp_path) -> None:
    """Cenario: Audio longo e recusado com cordialidade.

    Dado um audio de 150 segundos: ele nao e transcrito -- a Whisper nunca e
    chamada --, e o lead recebe o pedido cordial para mandar por texto.
    """
    transcritor = TranscritorFake()
    classificador = ClassificadorFake()
    whatsapp = WhatsAppQueRegistra()

    linha, resultado = await _processar(
        client,
        session,
        settings,
        tmp_path,
        provider_message_id="wamid.AUD150",
        segundos=150.0,
        transcritor=transcritor,
        classificador=classificador,
        whatsapp=whatsapp,
    )

    assert resultado == "respondido"
    assert transcritor.chamadas == []
    assert classificador.chamadas == 0
    assert [envio["texto"] for envio in whatsapp.envios] == [
        _com_identificacao(TEXTO_DO_AUDIO_LONGO)
    ]
    midia = await _midia(session, linha.id)
    assert midia.status_da_transcricao == StatusDaTranscricao.RECUSADA
    assert midia.motivo_da_transcricao == MotivoDaTranscricao.ACIMA_DA_DURACAO


async def test_audio_exatamente_no_limite_e_aceito(client, session, settings, tmp_path) -> None:
    """Cenario: Audio exatamente no limite e aceito.

    Dado um audio de exatamente 120 segundos: a transcricao e realizada
    normalmente.
    """
    transcritor = TranscritorFake(FALA)
    classificador = ClassificadorFake()

    linha, resultado = await _processar(
        client,
        session,
        settings,
        tmp_path,
        provider_message_id="wamid.AUD120",
        segundos=120.0,
        transcritor=transcritor,
        classificador=classificador,
        whatsapp=WhatsAppQueRegistra(),
    )

    assert resultado == "respondido"
    assert len(transcritor.chamadas) == 1
    assert classificador.chamadas == 1
    midia = await _midia(session, linha.id)
    assert midia.status_da_transcricao == StatusDaTranscricao.TRANSCRITA
    assert midia.duracao_segundos == 120.0


async def test_falha_da_transcricao_nao_deixa_o_lead_sem_resposta(
    client, session, settings, tmp_path
) -> None:
    """Cenario: Falha do servico de transcricao nao deixa o lead sem resposta.

    Com a transcricao indisponivel, o lead recebe o pedido para mandar por
    texto, e a falha fica registrada -- FALHOU, com o motivo e a hora, na linha
    de midia -- para reprocessamento.
    """
    classificador = ClassificadorFake()
    whatsapp = WhatsAppQueRegistra()

    linha, resultado = await _processar(
        client,
        session,
        settings,
        tmp_path,
        provider_message_id="wamid.AUDFALHA",
        segundos=40.0,
        transcritor=TranscritorFake(erro=TranscricaoIndisponivel("APIConnectionError")),
        classificador=classificador,
        whatsapp=whatsapp,
    )

    assert resultado == "respondido"
    assert classificador.chamadas == 0
    assert [envio["texto"] for envio in whatsapp.envios] == [
        _com_identificacao(TEXTO_DO_AUDIO_NAO_TRANSCRITO)
    ]
    midia = await _midia(session, linha.id)
    assert midia.status_da_transcricao == StatusDaTranscricao.FALHOU
    assert midia.motivo_da_transcricao == MotivoDaTranscricao.SERVICO_INDISPONIVEL
    assert midia.transcrita_em is not None
    # O audio original continua guardado: a falha foi da transcricao, nao do
    # download, e e esse arquivo que um reprocessamento leria.
    assert midia.status == StatusDaMidia.ARMAZENADA

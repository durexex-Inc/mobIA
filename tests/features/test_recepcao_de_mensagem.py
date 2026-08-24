"""Cenarios Gherkin de TEC-122.

Funcionalidade: Recepcao de mensagem do WhatsApp
"""

import json
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from mobia.api.deps import get_ingestion_service
from mobia.app.main import create_app
from mobia.domain.messages.models import Message
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature

ENVELOPE = {
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
                        "messages": [
                            {
                                "from": "5511911112222",
                                "id": "wamid.GHERKIN",
                                "timestamp": "1755900000",
                                "type": "text",
                                "text": {"body": "Boa noite, ainda tem o 2 quartos?"},
                            }
                        ],
                    },
                }
            ],
        }
    ],
}


def corpo_assinado(secret: str) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(ENVELOPE).encode("utf-8")
    return body, {
        SIGNATURE_HEADER: compute_signature(secret, body),
        "Content-Type": "application/json",
    }


def evento_de_log(caplog, evento: str) -> dict:
    """Decodifica o primeiro registro cujo `event` (JSONRenderer do structlog) bate.

    O structlog e configurado com `JSONRenderer` como ultimo processor, entao
    cada mensagem capturada pelo caplog e um JSON serializado, nao texto livre.
    Buscar por campo em vez de substring prova a forma do log, nao so que uma
    palavra apareceu em algum lugar do buffer.
    """
    for record in caplog.records:
        try:
            dados = json.loads(record.getMessage())
        except (json.JSONDecodeError, TypeError):
            continue
        if dados.get("event") == evento:
            return dados
    raise AssertionError(f"nenhum registro de log com event={evento!r} encontrado")


async def test_confirmar_recebimento_antes_de_processar(
    client, session, redis_pool, settings
) -> None:
    """Cenario: Confirmar recebimento antes de processar."""
    body, headers = corpo_assinado(settings.whatsapp_app_secret)

    response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200

    linha = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.GHERKIN")
    )
    assert linha is not None
    assert linha.status == MessageStatus.QUEUED
    assert linha.text_body == "Boa noite, ainda tem o 2 quartos?"

    jobs = await redis_pool.queued_jobs()
    assert len(jobs) == 1, "a mensagem tem de estar na fila de processamento"

    import mobia.api.routes.whatsapp as rota

    assert not [nome for nome in dir(rota) if "llm" in nome.lower()], (
        "nenhuma dependencia de LLM pode existir no ciclo da requisicao"
    )


async def test_descartar_payload_com_assinatura_invalida(
    client, session, redis_pool, caplog
) -> None:
    """Cenario: Descartar payload com assinatura invalida."""
    body = json.dumps(ENVELOPE).encode("utf-8")
    headers = {SIGNATURE_HEADER: "sha256=" + "f" * 64, "Content-Type": "application/json"}

    with caplog.at_level("WARNING"):
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    assert await redis_pool.queued_jobs() == []

    dados = evento_de_log(caplog, "webhook.rejected")
    assert dados["reason"] == "invalid_signature"
    assert dados.get("remote_ip"), "remote_ip precisa estar no log de rejeicao"


async def test_assinatura_ausente_tambem_e_descartada(client, session, caplog) -> None:
    body = json.dumps(ENVELOPE).encode("utf-8")

    with caplog.at_level("WARNING"):
        response = await client.post(
            "/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    dados = evento_de_log(caplog, "webhook.rejected")
    assert dados["reason"] == "missing_signature", "ausente e invalida tem de se distinguir no log"


async def test_json_malformado_nao_derruba_o_endpoint(client, session, settings, caplog) -> None:
    body = b"{nao e json"
    headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

    with caplog.at_level("WARNING"):
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0

    dados = evento_de_log(caplog, "webhook.rejected")
    assert dados["reason"] == "malformed_json"
    assert dados.get("remote_ip"), "remote_ip precisa estar no log de rejeicao"


async def test_envelope_estruturalmente_invalido_nao_vira_500(
    client, session, settings, caplog
) -> None:
    """A rota responde 200 em todo caminho, inclusive no erro inesperado.

    Um 500 faria a Meta re-entregar um payload que ninguem consegue interpretar,
    e a re-entrega falharia no mesmo ponto -- retentativa a toa.
    """
    body = json.dumps({"object": "whatsapp_business_account", "entry": ["nao e dict"]}).encode(
        "utf-8"
    )
    headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

    with caplog.at_level("ERROR"):
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    assert evento_de_log(caplog, "webhook.error")["reason"] == "AttributeError"


async def test_notificacao_de_status_nao_vira_mensagem(client, session, settings) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "222222222"},
                            "statuses": [{"id": "wamid.X", "status": "read"}],
                        }
                    }
                ]
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body)}

    response = await client.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize(
    ("token", "modo", "esperado_status", "esperado_corpo"),
    [
        ("valido", "subscribe", 200, "42"),
        ("errado", "subscribe", 403, None),
        ("ausente", "subscribe", 403, None),
        ("valido", "unsubscribe", 403, None),
    ],
)
async def test_handshake_de_verificacao(
    client, settings, token, modo, esperado_status, esperado_corpo
) -> None:
    params = {"hub.mode": modo, "hub.challenge": "42"}
    if token == "valido":
        params["hub.verify_token"] = settings.whatsapp_verify_token
    elif token == "errado":
        params["hub.verify_token"] = "token-errado"

    response = await client.get("/webhooks/whatsapp", params=params)

    assert response.status_code == esperado_status
    if esperado_corpo is not None:
        assert response.text == esperado_corpo


class SessaoQueFalhaNoCommit:
    """Sessao real cujo COMMIT levanta, como Postgres fora do ar faria.

    Delega tudo o mais para a sessao verdadeira, entao o caminho exercitado e o
    `_persist` de producao inteiro -- so a confirmacao da transacao quebra.
    """

    def __init__(self, sessao) -> None:
        self._sessao = sessao

    def __getattr__(self, nome: str):
        return getattr(self._sessao, nome)

    async def commit(self) -> None:
        raise OperationalError("COMMIT", {}, Exception("pool esgotado"))


def fabrica_com_commit_quebrado(fabrica):
    @asynccontextmanager
    async def _fabrica():
        async with fabrica() as sessao:
            yield SessaoQueFalhaNoCommit(sessao)

    return _fabrica


def fabrica_com_segundo_commit_quebrado(fabrica):
    """Primeira sessao real; da segunda em diante o COMMIT levanta.

    `_persist` e a virada de status pegam cada um a sua sessao da fabrica, nessa
    ordem, entao contar as sessoes entregues separa exatamente os dois commits:
    o do lote passa e as linhas ficam durable, o do `UPDATE ... SET status` cai.
    E o unico jeito de reproduzir a janela que interessa -- ja existe linha
    gravada e mesmo assim algo depois do `_persist` quebra.
    """
    entregues = 0

    @asynccontextmanager
    async def _fabrica():
        nonlocal entregues
        entregues += 1
        quebrada = entregues > 1
        async with fabrica() as sessao:
            yield SessaoQueFalhaNoCommit(sessao) if quebrada else sessao

    return _fabrica


async def test_falha_de_persistencia_nao_pode_responder_200(
    session, redis_pool, settings, caplog
) -> None:
    """Se a linha nao foi gravada, a Meta precisa re-entregar.

    O 200 e correto quando nao ha o que perder (assinatura invalida, JSON
    malformado, envelope estranho). Aqui ha: o payload era valido e o commit
    caiu. Responder 200 faz a Meta marcar a entrega como bem-sucedida e nunca
    re-enviar -- a mensagem some sem deixar linha, e o sweeper, unico caminho de
    recuperacao do desenho, nao tem o que achar.

    Re-entrega nao duplica: `_persist` commita o lote inteiro numa transacao so,
    entao quando ele levanta nada foi escrito.
    """
    app = create_app()
    app.state.redis_pool = redis_pool
    app.dependency_overrides[get_ingestion_service] = lambda: IngestionService(
        fabrica_com_commit_quebrado(get_sessionmaker()), redis_pool
    )
    body, headers = corpo_assinado(settings.whatsapp_app_secret)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as cliente:
        with caplog.at_level("ERROR"):
            response = await cliente.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 500, "a Meta so re-entrega em nao-2xx"
    assert await session.scalar(select(func.count()).select_from(Message)) == 0
    assert await redis_pool.queued_jobs() == []

    dados = evento_de_log(caplog, "webhook.persist_failed")
    assert dados["reason"] == "OperationalError"
    assert dados.get("payload_sha256"), "o hash do payload precisa estar no log da falha"
    assert dados.get("remote_ip"), "remote_ip precisa estar no log da falha"


async def test_falha_ao_virar_status_nao_pode_propagar(
    session, redis_pool, settings, caplog
) -> None:
    """Depois que o `_persist` commita, nenhuma falha pode virar 500.

    Este e o espelho do cenario acima e a fronteira entre os dois e o commit do
    lote. Antes dele nada foi escrito e o 500 e obrigatorio, senao a mensagem
    some sem deixar linha para o sweeper achar. Depois dele as linhas ja existem
    e o 500 nao serve para nada: desde o TEC-125 a re-entrega seria descartada
    pela UNIQUE, e a linha ja em RECEIVED e recuperada pelo sweeper sozinha.

    O 500 tambem nao compraria nada aqui: a linha ficou em RECEIVED e o sweeper
    a recupera sem depender da Meta.
    """
    app = create_app()
    app.state.redis_pool = redis_pool
    app.dependency_overrides[get_ingestion_service] = lambda: IngestionService(
        fabrica_com_segundo_commit_quebrado(get_sessionmaker()), redis_pool
    )
    body, headers = corpo_assinado(settings.whatsapp_app_secret)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as cliente:
        with caplog.at_level("WARNING"):
            response = await cliente.post("/webhooks/whatsapp", content=body, headers=headers)

    assert response.status_code == 200, "a linha ja esta gravada; re-entrega da Meta duplicaria"

    linha = await session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.GHERKIN")
    )
    assert linha is not None, "o commit do lote passou, a linha tem de estar la"
    assert linha.status == MessageStatus.RECEIVED, "a virada de status falhou; o sweeper recupera"
    assert linha.queued_at is None

    assert len(await redis_pool.queued_jobs()) == 1, "o enqueue passou, quem caiu foi o UPDATE"

    dados = evento_de_log(caplog, "queued_flag.failed")
    assert dados["reason"] == "OperationalError"
    assert dados["message_id"] == str(linha.id)

"""O simulador de WhatsApp: identidade por telefone, sem Cloud API da Meta."""

import base64

import pytest
from sqlalchemy import select

from mobia.app.config import get_settings
from mobia.domain.identidade.indice import chave_de
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.messages.canais import CANAL_SIMULADOR, REMETENTE_DO_SIMULADOR
from mobia.domain.messages.models import Message

_CAMINHO = "/dev/simulador-whatsapp/chat"


async def _cumprimentar(ws, telefone: str) -> str:
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "telefone": telefone})
    frame = await ws.receber()
    assert frame["tipo"] == "sessao"
    return str(frame["telefone"])


async def test_identificacao_pelo_telefone_normaliza_e_devolve_historico(ws_cliente) -> None:
    async with ws_cliente(caminho=_CAMINHO) as ws:
        telefone = await _cumprimentar(ws, "11 98888-7777")
        historico = await ws.receber()

    assert telefone == normalizar("11988887777")
    assert historico == {"tipo": "historico", "mensagens": []}


async def test_mensagem_vira_linha_no_canal_simulador(ws_cliente, session) -> None:
    async with ws_cliente(caminho=_CAMINHO) as ws:
        telefone = await _cumprimentar(ws, "11988880001")
        await ws.receber()  # historico, vazio
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "quero um apartamento"})
        assert await ws.receber() == {"tipo": "ack", "messageId": "m-1"}

    chave = chave_de(CANAL_SIMULADOR, telefone)
    linha = (
        await session.execute(select(Message).where(Message.conversation_key == chave))
    ).scalar_one()
    assert linha.channel == CANAL_SIMULADOR
    assert linha.provider_message_id == f"{chave}:m-1"
    # TEC-203: a coluna guarda o HMAC do remetente, nao o telefone cru --
    # mesmo padrao de `test_widget_handshake.py::test_a_mensagem_vira_linha_no_canal_web`.
    assert linha.sender_external_id == chave
    assert linha.recipient_external_id == REMETENTE_DO_SIMULADOR


async def test_telefone_invalido_recusa_e_fecha(ws_cliente) -> None:
    async with ws_cliente(caminho=_CAMINHO) as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "telefone": "abc"})
        erro = await ws.receber()
        assert erro["codigo"] == "telefone_invalido"
        assert await ws.fechamento() == 1002


async def test_reconectar_com_o_mesmo_telefone_devolve_a_conversa(ws_cliente) -> None:
    telefone = "11988880002"
    async with ws_cliente(caminho=_CAMINHO) as ws:
        await _cumprimentar(ws, telefone)
        await ws.receber()  # historico, vazio
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "primeira"})
        await ws.receber()

    async with ws_cliente(caminho=_CAMINHO) as ws:
        await _cumprimentar(ws, telefone)
        historico = await ws.receber()

    assert [(fala["papel"], fala["texto"]) for fala in historico["mensagens"]] == [
        ("lead", "primeira")
    ]


async def test_telefones_diferentes_nao_compartilham_conversa(ws_cliente) -> None:
    async with ws_cliente(caminho=_CAMINHO) as ws:
        await _cumprimentar(ws, "11988880003")
        await ws.receber()
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "so meu"})
        await ws.receber()

    async with ws_cliente(caminho=_CAMINHO) as ws:
        await _cumprimentar(ws, "21977770004")
        historico = await ws.receber()

    assert historico == {"tipo": "historico", "mensagens": []}


def _producao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mesma guarda de `test_worker_startup.py::_producao`: as OUTRAS
    validacoes de producao tem de estar satisfeitas, ou o teste passaria pelo
    motivo errado."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("JWT_SEGREDO", "segredo-de-jwt-proprio-com-32-bytes-ou-mais")
    monkeypatch.setenv("AUDITORIA_CHAVE_DO_LEAD", "chave-do-lead-propria")
    monkeypatch.setenv("LEAD_INDICE_CHAVE", "chave-de-indice-propria")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-de-teste")


async def test_em_producao_o_handshake_e_recusado(
    ws_cliente, monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    _producao(monkeypatch)
    get_settings.cache_clear()

    async with ws_cliente(caminho=_CAMINHO) as ws:
        status, _ = await ws.recusa()
        assert status == 404

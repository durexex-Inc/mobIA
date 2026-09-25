"""Cenarios Gherkin de TEC-124.

Funcionalidade: Atendimento pelo widget web

Os tres cenarios rodam o CICLO INTEIRO, e nao uma publicacao feita a mao: a
visitante escreve pelo socket, a linha entra na fila, `process_message` roda o
turno com os dubles de `_ctx()`, o roteador escolhe o `WebOutbound`, e a fala
do agente volta pelo pub/sub ao mesmo socket. Publicar a mao no Redis testaria
o Redis, e nao o atendimento.
"""

from typing import Any

from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeConfirmacaoNoop
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import EnvioRetentavel
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebOutbound
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

PERGUNTA = "esse apartamento da zona sul ainda está disponível?"


class WhatsAppForaDoAr:
    """A integracao com a Meta indisponivel: todo envio falha como retentavel."""

    def __init__(self) -> None:
        self.tentativas = 0

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.tentativas += 1
        raise EnvioRetentavel("graph.facebook.com fora do ar")


def _ctx_do_worker(redis_pool: Any, whatsapp: Any) -> dict[str, Any]:
    """O `ctx` que `workers/main.py` monta, com dubles no lugar dos modelos.

    As duas portas de saida sao as de producao, montadas do mesmo jeito que o
    `startup` as monta: e o roteamento real que estes cenarios exercitam.
    """
    session_factory = get_sessionmaker()
    return {
        "session_factory": session_factory,
        "outbound": RoteadorPorCanal(
            session_factory,
            {CANAL_WHATSAPP: whatsapp, CANAL_WEB: WebOutbound(session_factory, redis_pool)},
        ),
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "agendador_de_confirmacao": AgendadorDeConfirmacaoNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop(), CANAL_WEB: IndicadorNoop()},
    }


async def _abrir(ws_cliente, sessao: str | None = None) -> tuple[Any, str]:
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    return ws, (await ws.receber())["sessao"]


async def _linha_da_sessao(session, sessao: str) -> Message:
    return (
        await session.execute(
            select(Message).where(
                Message.conversation_key == sessao, Message.role == MessageRole.LEAD
            )
        )
    ).scalar_one()


async def test_conversar_pelo_chat_do_site(ws_cliente, session, redis_pool) -> None:
    """Cenario: Conversar pelo chat do site."""
    # Dada uma sessao de widget web aberta
    ws, sessao = await _abrir(ws_cliente)
    try:
        # Quando a visitante envia a pergunta
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": PERGUNTA})
        assert (await ws.receber())["tipo"] == "recebido"

        # Entao a mensagem entra na fila de processamento com canal WEB
        linha = await _linha_da_sessao(session, sessao)
        assert linha.channel == CANAL_WEB
        assert linha.status == MessageStatus.QUEUED
        assert await redis_pool.zscore("arq:queue", f"msg:{linha.id}") is not None

        # E a resposta do agente chega na mesma sessao
        await process_message(_ctx_do_worker(redis_pool, WhatsAppForaDoAr()), str(linha.id))
        resposta = await ws.receber()
        assert resposta["tipo"] == "mensagem"
        assert resposta["texto"]
    finally:
        await ws.__aexit__()


async def test_reconectar_sem_perder_o_que_ja_foi_dito(ws_cliente, session, redis_pool) -> None:
    """Cenario: Reconectar sem perder o que ja foi dito."""
    # Dada uma conversa em andamento no widget web
    ws, sessao = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "quero dois quartos"})
        await ws.receber()
        linha = await _linha_da_sessao(session, sessao)
    finally:
        # Quando a conexao cai...
        await ws.__aexit__()

    # ...e o agente responde enquanto ninguem ouve
    await process_message(_ctx_do_worker(redis_pool, WhatsAppForaDoAr()), str(linha.id))

    # ...e a visitante recarrega a pagina
    ws, _ = await _abrir(ws_cliente, sessao)
    try:
        historico = await ws.receber()
    finally:
        await ws.__aexit__()

    # Entao a sessao e retomada com o historico da conversa visivel
    assert historico["tipo"] == "historico"
    papeis = [fala["papel"] for fala in historico["mensagens"]]
    assert papeis[0] == "lead"
    assert historico["mensagens"][0]["texto"] == "quero dois quartos"
    # E nenhuma mensagem ja recebida pelo servidor e perdida -- nem a da
    # visitante, nem a resposta que saiu com a aba fechada.
    assert "agente" in papeis


async def test_whatsapp_indisponivel_nao_afeta_o_canal_web(ws_cliente, session, redis_pool) -> None:
    """Cenario: WhatsApp indisponivel nao afeta o canal web."""
    # Dado que a integracao com o WhatsApp esta fora do ar
    whatsapp = WhatsAppForaDoAr()

    # Quando uma visitante escreve pelo widget web
    ws, sessao = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "oi"})
        await ws.receber()
        linha = await _linha_da_sessao(session, sessao)

        resultado = await process_message(_ctx_do_worker(redis_pool, whatsapp), str(linha.id))

        # Entao o atendimento acontece normalmente
        assert resultado == "respondido"
        assert (await ws.receber())["tipo"] == "mensagem"
    finally:
        await ws.__aexit__()

    # E nada do canal web passou pela integracao que caiu -- se o roteador
    # tivesse mandado por ela, o turno teria falhado e nada teria chegado.
    assert whatsapp.tentativas == 0

"""O aperto de mao do widget e a entrada de mensagem. TEC-124, D2 e D3."""

import uuid

from sqlalchemy import select

from mobia.app.config import get_settings
from mobia.domain.messages.canais import CANAL_WEB, REMETENTE_DO_WIDGET
from mobia.domain.messages.models import Message


async def _cumprimentar(ws, sessao: str | None = None) -> str:
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    frame = await ws.receber()
    assert frame["tipo"] == "sessao"
    return str(frame["sessao"])


async def test_sem_sessao_o_servidor_emite_um_uuid(ws_cliente) -> None:
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)

    assert str(uuid.UUID(sessao)) == sessao


async def test_a_mensagem_vira_linha_no_canal_web(ws_cliente, session) -> None:
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar(
            {"tipo": "mensagem", "id": "m-1", "texto": "esse apê da zona sul ainda está?"}
        )
        assert await ws.receber() == {"tipo": "recebido", "id": "m-1"}

    linha = (
        await session.execute(select(Message).where(Message.conversation_key == sessao))
    ).scalar_one()
    assert linha.channel == CANAL_WEB
    assert linha.provider_message_id == "m-1"
    assert linha.recipient_external_id == REMETENTE_DO_WIDGET
    assert linha.sender_external_id == sessao


async def test_primeiro_frame_que_nao_e_ola_fecha_com_1002(ws_cliente) -> None:
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "mensagem", "texto": "oi"})
        assert await ws.fechamento() == 1002


async def test_frame_que_nao_e_json_fecha_com_1002(ws_cliente) -> None:
    # Review Focus 1: nao pode virar 500 nem traceback do uvicorn.
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar_cru("nao sou json")
        assert await ws.fechamento() == 1002


async def test_frame_que_nao_e_json_depois_do_cumprimento_fecha_com_1002(ws_cliente) -> None:
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar_cru("{quebrado")
        assert await ws.fechamento() == 1002


async def test_sessao_que_nao_e_uuid_fecha_com_1002(ws_cliente) -> None:
    # Review Focus 2: aceitar deixaria o cliente escolher a `conversation_key`
    # -- inclusive a de outra conversa.
    async with ws_cliente() as ws:
        await ws.aceitar()
        await ws.enviar({"tipo": "ola", "sessao": "abc"})
        assert await ws.fechamento() == 1002


async def test_sessao_em_maiuscula_e_normalizada(ws_cliente) -> None:
    # A mesma sessao escrita de duas formas nao pode virar duas conversas.
    sessao = "8C0F0A3E-0000-4000-8000-0000000000EE"
    async with ws_cliente() as ws:
        devolvida = await _cumprimentar(ws, sessao)
        await ws.receber()  # o historico, vazio

    assert devolvida == sessao.lower()


async def test_texto_vazio_nao_vira_linha_e_a_conexao_segue(ws_cliente, session) -> None:
    # Review Focus 3: viraria turno, com chamada paga ao modelo, para nada.
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "   "})
        assert await ws.receber() == {"tipo": "erro", "motivo": "texto_vazio"}

        await ws.enviar({"tipo": "mensagem", "id": "m-2", "texto": "agora vai"})
        assert (await ws.receber())["tipo"] == "recebido"

    linhas = (await session.execute(select(Message))).scalars().all()
    assert [linha.provider_message_id for linha in linhas] == ["m-2"]


async def test_texto_acima_do_teto_e_recusado_sem_derrubar(
    ws_cliente, monkeypatch, caches_de_cliente_limpos
) -> None:
    # Review Focus 4: derrubar transformaria um Ctrl+V infeliz em perda da
    # conversa inteira.
    monkeypatch.setenv("TAMANHO_MAXIMO_DO_TEXTO_DO_WIDGET", "10")
    get_settings.cache_clear()

    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "x" * 11})
        assert await ws.receber() == {"tipo": "erro", "motivo": "texto_longo_demais"}

        await ws.enviar({"tipo": "mensagem", "id": "m-2", "texto": "curto"})
        assert (await ws.receber())["tipo"] == "recebido"


async def test_retomar_devolve_o_historico(ws_cliente) -> None:
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "primeira"})
        await ws.receber()

    async with ws_cliente() as ws:
        assert await _cumprimentar(ws, sessao) == sessao
        historico = await ws.receber()

    assert historico["tipo"] == "historico"
    assert [(fala["papel"], fala["texto"]) for fala in historico["mensagens"]] == [
        ("lead", "primeira")
    ]


async def test_sessao_nova_nao_recebe_historico(ws_cliente) -> None:
    # Sem sessao reapresentada nao ha o que reler: o proximo frame depois do
    # `sessao` e o `recebido` da primeira mensagem, e nao um `historico` vazio.
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "oi"})
        assert (await ws.receber())["tipo"] == "recebido"


async def test_id_repetido_nao_grava_duas_linhas(ws_cliente, session) -> None:
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        for _ in range(2):
            await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "primeira"})
            await ws.receber()

    linhas = (await session.execute(select(Message))).scalars().all()
    assert len(linhas) == 1


async def test_falha_ao_gravar_fecha_com_1011_e_nao_sobe_crua(ws_cliente, app_do_widget) -> None:
    """A falha do `ingest` nao pode escapar do endpoint.

    Escapando, quem a loga e o uvicorn -- fora do structlog e do saneamento da
    TEC-293 -- com a mensagem inteira da excecao, que para um erro do asyncpg
    inclui a linha `DETAIL` que o servidor escreve. O webhook aceita isso
    porque precisa do 500 para a Meta reentregar; o widget nao precisa: o
    equivalente da reentrega e o cliente reenviar com o mesmo `id`, e a UNIQUE
    segura a duplicata. Fechar com 1011 e o sinal para ele reconectar.
    """
    from mobia.api.deps import get_ingestion_service

    class ServicoQueCai:
        async def ingest(self, parsed, channel=None):
            raise RuntimeError("banco fora")

    app_do_widget.dependency_overrides[get_ingestion_service] = ServicoQueCai

    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "oi"})
        assert await ws.fechamento() == 1011

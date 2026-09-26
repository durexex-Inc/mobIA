"""A rota do widget grava o vinculo quando a fala traz um telefone. TEC-129, D3."""

from typing import Any

from sqlalchemy import select

from mobia.domain.identidade.models import VinculoDeSessao


async def _abrir(ws_cliente, sessao: str | None = None) -> tuple[Any, str]:
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    return ws, (await ws.receber())["sessao"]


async def _vinculos(session) -> list[VinculoDeSessao]:
    return list((await session.execute(select(VinculoDeSessao))).scalars())


async def test_fala_com_telefone_vincula_a_sessao(ws_cliente, session) -> None:
    ws, sessao = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "meu whats e (48) 99999-0000"})
        assert (await ws.receber())["tipo"] == "ack"
    finally:
        await ws.__aexit__()

    [vinculo] = await _vinculos(session)
    assert (vinculo.conversation_key, vinculo.telefone) == (sessao, "5548999990000")


async def test_fala_sem_telefone_nao_vincula(ws_cliente, session) -> None:
    ws, _ = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "quero dois quartos"})
        await ws.receber()
    finally:
        await ws.__aexit__()

    assert await _vinculos(session) == []


async def test_reenvio_nao_tenta_vincular_de_novo(ws_cliente, session, monkeypatch) -> None:
    import mobia.api.routes.widget as rota

    chamadas: list[str] = []
    original = rota.vincular_sessao

    async def contando(*args: Any, **kwargs: Any) -> bool:
        chamadas.append(kwargs["conversation_key"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(rota, "vincular_sessao", contando)
    ws, _ = await _abrir(ws_cliente)
    try:
        for _ in range(2):
            await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "(48) 99999-0000"})
            assert (await ws.receber())["tipo"] == "ack"
    finally:
        await ws.__aexit__()

    # A UNIQUE descartou o reenvio, `ingest` devolveu vazio, e o vinculo nao
    # foi tentado de novo.
    assert len(chamadas) == 1


async def test_falha_no_vinculo_nao_derruba_a_conversa(ws_cliente, session, monkeypatch) -> None:
    import mobia.api.routes.widget as rota

    async def quebrado(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("banco sumiu no meio")

    monkeypatch.setattr(rota, "vincular_sessao", quebrado)
    ws, _ = await _abrir(ws_cliente)
    try:
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "(48) 99999-0000"})
        # A mensagem ja estava persistida: o `ack` chega, e o socket segue.
        assert (await ws.receber())["tipo"] == "ack"
        await ws.enviar({"tipo": "mensagem", "id": "m-2", "texto": "e dois quartos"})
        assert (await ws.receber())["tipo"] == "ack"
    finally:
        await ws.__aexit__()


async def test_fala_com_dois_telefones_diferentes_nao_vincula(ws_cliente, session) -> None:
    """D2: nao ha como saber qual dos dois e o da pessoa, e vincular o errado
    poe o que ela disse no contexto do WhatsApp de outra."""
    ws, _ = await _abrir(ws_cliente)
    try:
        await ws.enviar(
            {
                "tipo": "mensagem",
                "id": "m-1",
                "texto": "o meu e (48) 99999-0000, o da minha esposa e (48) 98888-1111",
            }
        )
        assert (await ws.receber())["tipo"] == "ack"
    finally:
        await ws.__aexit__()

    assert await _vinculos(session) == []

"""A resposta do agente volta na sessao aberta. TEC-124, D4.

Nenhum destes testes dorme antes de publicar, e isso e o que eles provam: o
endpoint assina o canal da sessao ANTES de anunciar a sessao ao cliente, entao
quem recebeu o frame `sessao` ja tem para onde a publicacao ir. Com a ordem
inversa, um `publish` logo depois do anuncio podia chegar ao Redis antes do
`SUBSCRIBE`, e pub/sub nao guarda nada para quem ainda nao ouve.
"""

import json

from mobia.domain.outbound.web import canal_da_sessao


def _fala(texto: str) -> str:
    return json.dumps({"tipo": "mensagem", "texto": texto, "kind": "resposta"})


async def _abrir(ws_cliente, sessao: str | None = None):
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    frame = await ws.receber()
    if sessao is not None:
        await ws.receber()  # o historico
    return ws, frame["sessao"]


async def test_a_publicacao_logo_depois_do_anuncio_chega(ws_cliente, redis_pool) -> None:
    ws, sessao = await _abrir(ws_cliente)
    try:
        await redis_pool.publish(canal_da_sessao(sessao), _fala("olá!"))
        assert await ws.receber() == {"tipo": "mensagem", "texto": "olá!", "kind": "resposta"}
    finally:
        await ws.__aexit__()


async def test_duas_abas_na_mesma_sessao_recebem_as_duas(ws_cliente, redis_pool) -> None:
    # Review Focus 5. O que nao pode acontecer e uma derrubar a outra.
    primeira, sessao = await _abrir(ws_cliente)
    segunda, _ = await _abrir(ws_cliente, sessao=sessao)
    try:
        await redis_pool.publish(canal_da_sessao(sessao), _fala("olá!"))
        assert (await primeira.receber())["texto"] == "olá!"
        assert (await segunda.receber())["texto"] == "olá!"
    finally:
        await primeira.__aexit__()
        await segunda.__aexit__()


async def test_fechar_uma_aba_nao_cala_a_outra(ws_cliente, redis_pool) -> None:
    primeira, sessao = await _abrir(ws_cliente)
    segunda, _ = await _abrir(ws_cliente, sessao=sessao)
    try:
        await primeira.__aexit__()
        await redis_pool.publish(canal_da_sessao(sessao), _fala("ainda aqui"))
        assert (await segunda.receber())["texto"] == "ainda aqui"
    finally:
        await segunda.__aexit__()


async def test_publicacao_de_outra_sessao_nao_vaza(ws_cliente, redis_pool) -> None:
    """A fala alheia sai primeiro, a propria depois -- e a primeira a chegar e a propria.

    Afirmar so a ausencia da alheia nao reprova nunca: sem assinatura nenhuma,
    nada vaza. A segunda publicacao e o que obriga o canal a estar vivo para o
    teste passar, e a ordem das duas e o que faz um vazamento aparecer.
    """
    ws, sessao = await _abrir(ws_cliente)
    try:
        await redis_pool.publish(
            canal_da_sessao("8c0f0a3e-0000-4000-8000-0000000000bb"), _fala("de outra pessoa")
        )
        await redis_pool.publish(canal_da_sessao(sessao), _fala("minha"))
        assert (await ws.receber())["texto"] == "minha"
    finally:
        await ws.__aexit__()


async def test_a_desconexao_solta_a_assinatura(ws_cliente, redis_pool) -> None:
    # Uma conexao do pool por aba aberta: se a assinatura sobrevivesse ao
    # socket, cada aba fechada vazaria uma conexao do Redis para sempre.
    ws, sessao = await _abrir(ws_cliente)
    assert await redis_pool.pubsub_numsub(canal_da_sessao(sessao)) == [
        (canal_da_sessao(sessao).encode(), 1)
    ]
    await ws.__aexit__()

    assert await redis_pool.pubsub_numsub(canal_da_sessao(sessao)) == [
        (canal_da_sessao(sessao).encode(), 0)
    ]

"""A entrega no canal web. TEC-124, D4."""

import asyncio
import json
from typing import Any

from conftest import _entrada_do_lead
from redis.exceptions import ConnectionError as ErroDeConexaoDoRedis

from mobia.domain.messages.canais import CANAL_WEB
from mobia.domain.outbound.web import WebOutbound, canal_da_sessao


async def _linha_web(session, sessao: str):
    linha = await _entrada_do_lead(session, texto="oi")
    linha.channel = CANAL_WEB
    linha.conversation_key = sessao
    await session.commit()
    return linha


async def _assinar(redis_pool, sessao: str) -> Any:
    """Assina e ESPERA a confirmacao do servidor.

    Sem esperar, o `publish` do teste pode chegar ao Redis antes do
    `SUBSCRIBE`, e pub/sub nao guarda nada para quem ainda nao ouve.
    """
    ouvinte = redis_pool.pubsub()
    await ouvinte.subscribe(canal_da_sessao(sessao))
    confirmacao = await ouvinte.get_message(timeout=5)
    assert confirmacao is not None and confirmacao["type"] == "subscribe"
    return ouvinte


async def _proxima(ouvinte: Any) -> dict[str, Any]:
    """A proxima publicacao, com teto: sem ele um teste vermelho pendura."""

    async def _esperar() -> dict[str, Any]:
        while True:
            evento = await ouvinte.get_message(ignore_subscribe_messages=True, timeout=1)
            if evento is not None:
                return json.loads(evento["data"])

    return await asyncio.wait_for(_esperar(), timeout=5)


async def test_publica_o_texto_na_sessao(session, session_factory, redis_pool) -> None:
    sessao = "8c0f0a3e-0000-4000-8000-000000000001"
    linha = await _linha_web(session, sessao)
    ouvinte = await _assinar(redis_pool, sessao)

    porta = WebOutbound(session_factory, redis_pool)
    try:
        assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is True
        assert await _proxima(ouvinte) == {"tipo": "mensagem", "texto": "ola", "kind": "resposta"}
    finally:
        await ouvinte.aclose()


async def test_sem_ouvinte_o_envio_e_bem_sucedido(session, session_factory, redis_pool) -> None:
    # A aba fechou. A fala ja esta em `messages` e a reconexao a mostra --
    # levantar aqui faria o sweeper rodar o turno inteiro de novo, com
    # chamada nova e paga ao modelo, para reentregar o que ja esta no banco.
    sessao = "8c0f0a3e-0000-4000-8000-000000000002"
    linha = await _linha_web(session, sessao)

    porta = WebOutbound(session_factory, redis_pool)
    assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is True


async def test_redis_indisponivel_nao_derruba_o_turno(session, session_factory) -> None:
    class RedisQueCai:
        async def publish(self, canal: str, mensagem: str) -> int:
            raise ErroDeConexaoDoRedis("redis fora")

    sessao = "8c0f0a3e-0000-4000-8000-000000000003"
    linha = await _linha_web(session, sessao)

    porta = WebOutbound(session_factory, RedisQueCai())
    assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is True


async def test_a_ficha_com_imagem_viaja_com_link_e_legenda(
    session, session_factory, redis_pool
) -> None:
    sessao = "8c0f0a3e-0000-4000-8000-000000000004"
    linha = await _linha_web(session, sessao)
    ouvinte = await _assinar(redis_pool, sessao)

    porta = WebOutbound(session_factory, redis_pool)
    try:
        await porta.send(
            linha.id,
            "ficha_1",
            {"para": sessao, "tipo": "imagem", "link": "http://f/1.jpg", "legenda": "Apê"},
        )
        assert await _proxima(ouvinte) == {
            "tipo": "imagem",
            "link": "http://f/1.jpg",
            "legenda": "Apê",
            "kind": "ficha_1",
        }
    finally:
        await ouvinte.aclose()


async def test_o_opt_out_barra_a_publicacao(session, session_factory, redis_pool) -> None:
    """A heranca de `GuardedOutbound` e o que traz a guarda -- e so ela.

    Um adaptador escrito direto contra o Protocol tiparia igual e mandaria
    mensagem para quem pediu para parar. Este teste e o que reprova se alguem
    trocar a base da classe.
    """
    from mobia.domain.optout.repositorio import registrar_optout

    sessao = "8c0f0a3e-0000-4000-8000-000000000005"
    linha = await _linha_web(session, sessao)
    await registrar_optout(
        session_factory, channel=CANAL_WEB, conversation_key=sessao, message_id=linha.id
    )

    porta = WebOutbound(session_factory, redis_pool)
    assert await porta.send(linha.id, "resposta", {"para": sessao, "texto": "ola"}) is False


_CARD = {
    "id": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    "titulo": "Casa 3 quartos",
    "bairro": "Lagoa da Conceição",
    "precoCentavos": 90000000,
    "condominioCentavos": None,
    "quartos": 3,
    "vagas": 2,
    "areaUtilM2": 140,
    "diferencial": "piscina",
    "foto": "http://f/1.jpg",
    "url": None,
}


async def test_a_ficha_vira_imovel_com_o_card_e_a_prosa(
    session, session_factory, redis_pool
) -> None:
    """TEC-364, D2: o card estruturado, e a prosa solta -- nao a legenda."""
    sessao = "8c0f0a3e-0000-4000-8000-000000000005"
    linha = await _linha_web(session, sessao)
    ouvinte = await _assinar(redis_pool, sessao)

    porta = WebOutbound(session_factory, redis_pool)
    try:
        await porta.send(
            linha.id,
            "ficha_1",
            {
                "para": sessao,
                "tipo": "imagem",
                "link": "http://f/1.jpg",
                "legenda": "Achei esta. Casa 3 quartos...",
                "imovel": _CARD,
                "prosa": "Achei esta.",
            },
        )
        assert await _proxima(ouvinte) == {
            "tipo": "imovel",
            "imovel": _CARD,
            "texto": "Achei esta.",
            "kind": "ficha_1",
        }
    finally:
        await ouvinte.aclose()


async def test_a_ficha_sem_foto_tambem_vira_imovel(session, session_factory, redis_pool) -> None:
    """Sem foto o payload e de texto, e o web ainda precisa do card para o
    placeholder com o bairro da TEC-349. A segunda ficha nao leva prosa."""
    sessao = "8c0f0a3e-0000-4000-8000-000000000006"
    linha = await _linha_web(session, sessao)
    ouvinte = await _assinar(redis_pool, sessao)
    sem_foto = {**_CARD, "foto": None}

    porta = WebOutbound(session_factory, redis_pool)
    try:
        await porta.send(
            linha.id,
            "ficha_2",
            {"para": sessao, "texto": "Casa 3 quartos...", "imovel": sem_foto, "prosa": None},
        )
        assert await _proxima(ouvinte) == {
            "tipo": "imovel",
            "imovel": sem_foto,
            "texto": None,
            "kind": "ficha_2",
        }
    finally:
        await ouvinte.aclose()

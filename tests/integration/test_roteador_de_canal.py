"""O roteador que escolhe o adaptador pela linha. TEC-124, D5."""

import uuid
from typing import Any

import pytest
from conftest import _entrada_do_lead

from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.outbound.roteador import CanalSemPorta, RoteadorPorCanal


class PortaEspia:
    def __init__(self) -> None:
        self.chamadas: list[tuple[uuid.UUID, str, dict[str, Any]]] = []

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        self.chamadas.append((message_id, kind, payload))
        return True


async def test_roteia_para_o_adaptador_do_canal_da_linha(session, session_factory) -> None:
    linha = await _entrada_do_lead(session, texto="oi")
    linha.channel = CANAL_WEB
    await session.commit()

    whatsapp, web = PortaEspia(), PortaEspia()
    roteador = RoteadorPorCanal(session_factory, {CANAL_WHATSAPP: whatsapp, CANAL_WEB: web})

    assert await roteador.send(linha.id, "resposta", {"texto": "ola"}) is True
    assert [chamada[0] for chamada in web.chamadas] == [linha.id]
    assert whatsapp.chamadas == []


async def test_a_linha_whatsapp_continua_indo_pelo_whatsapp(session, session_factory) -> None:
    # A outra metade: um dicionario lido do lado errado mandaria o WhatsApp
    # para o adaptador do web, e o teste acima sozinho nao veria.
    linha = await _entrada_do_lead(session, texto="oi")

    whatsapp, web = PortaEspia(), PortaEspia()
    roteador = RoteadorPorCanal(session_factory, {CANAL_WHATSAPP: whatsapp, CANAL_WEB: web})

    await roteador.send(linha.id, "resposta", {"texto": "ola"})
    assert [chamada[0] for chamada in whatsapp.chamadas] == [linha.id]
    assert web.chamadas == []


async def test_linha_inexistente_levanta_alto(session_factory) -> None:
    # Defeito de chamador, nao indisponibilidade: engolir deixaria o lead sem
    # resposta com um log de `info`.
    roteador = RoteadorPorCanal(session_factory, {CANAL_WHATSAPP: PortaEspia()})
    with pytest.raises(CanalSemPorta):
        await roteador.send(uuid.uuid4(), "resposta", {"texto": "ola"})


async def test_canal_sem_porta_levanta_alto(session, session_factory) -> None:
    linha = await _entrada_do_lead(session, texto="oi")
    linha.channel = CANAL_WEB
    await session.commit()

    roteador = RoteadorPorCanal(session_factory, {CANAL_WHATSAPP: PortaEspia()})
    with pytest.raises(CanalSemPorta):
        await roteador.send(linha.id, "resposta", {"texto": "ola"})

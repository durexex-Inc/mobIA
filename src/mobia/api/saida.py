"""A porta de saida da API: por onde a fala do corretor chega ao lead. TEC-194.

Ate a TEC-194 so o worker montava um `RoteadorPorCanal` -- todo envio saia de
dentro de um job. A fala do corretor e sincrona (D3 do desenho): a tela precisa
saber, na resposta, se a mensagem saiu ou se a janela de 24h do WhatsApp ja
fechou, e uma fila responderia "aceito" antes de saber.

**O mesmo roteador, os mesmos adaptadores e as mesmas guardas do worker.** Um
adaptador montado aqui sem herdar de `GuardedOutbound` falaria com quem pediu
opt-out -- o aviso do docstring de `OutboundPort`. Montar a partir das mesmas
classes e o que impede isso.

**Preguicosa, e nao no `lifespan`**: o `ASGITransport` dos testes nao roda o
`lifespan`, e o teste que troca a porta por uma falsa grava em
`app.state.outbound` antes da primeira requisicao. A primeira chamada monta e
guarda; as seguintes reusam.
"""

from typing import Any

from fastapi import Request

from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.outbound.port import OutboundPort
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebOutbound
from mobia.domain.outbound.whatsapp import WhatsAppOutbound
from mobia.infra.db import get_sessionmaker


def porta_de_saida(request: Request) -> OutboundPort:
    estado: Any = request.app.state
    porta: OutboundPort | None = getattr(estado, "outbound", None)
    if porta is None:
        session_factory = get_sessionmaker()
        porta = RoteadorPorCanal(
            session_factory,
            {
                CANAL_WHATSAPP: WhatsAppOutbound(session_factory),
                # O pool que o `lifespan` abre e o mesmo em que a central do
                # widget escuta (TEC-124) -- publicar nele e o que faz a fala
                # chegar a aba aberta do visitante.
                CANAL_WEB: WebOutbound(session_factory, getattr(estado, "redis_pool", None)),
            },
        )
        estado.outbound = porta
    return porta

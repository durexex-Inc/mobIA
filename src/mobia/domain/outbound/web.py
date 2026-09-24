"""A entrega no canal web: publicar na sessao aberta. TEC-124, D4.

**Este adaptador nao levanta excecao nenhuma, e isso diverge de proposito do
contrato que `OutboundPort` escreve.** La, falha de rede e `EnvioRetentavel`
porque no WhatsApp a rede e o UNICO caminho ate o lead: sem ela, ele nunca
recebe. Aqui nao e. A fala do agente ja foi gravada em `messages` por
`MessageRecorder` antes de qualquer publicacao, e a reconexao a mostra (ver
`domain/messages/historico.py`) -- a publicacao e o atalho que a faz chegar
AGORA, nao o caminho que a faz chegar. Retentar custaria uma chamada nova e
paga ao modelo para reentregar o que ja esta no banco, por causa de uma aba
que a visitante fechou.

Por isso publicacao sem ouvinte sai em `info` e e o caso NORMAL, nao falha.

**`EnvioForaDaJanela` tambem nunca sai daqui**: o canal web nao tem janela, e
o docstring de `OutboundPort` ja registrava isso antes desta card existir.

**Kind que nao seja texto nem imagem nao e publicado.** Nenhum caminho manda
template para o web -- as varreduras que os enviam filtram por
`CANAIS_COM_REENGAJAMENTO` --, entao chegar um aqui e defeito de roteamento
nosso. Fechar o turno em falha puniria o lead por isso; o `warning` e o que
sobra.
"""

import json
import uuid
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.outbound.port import GuardedOutbound

log = structlog.get_logger(__name__)

# O namespace das publicacoes. Fora do `arq:` da fila e do `ratelimit:` do
# limitador, que sao os outros dois deste Redis.
PREFIXO_DA_SESSAO = "mobia:web"


def canal_da_sessao(sessao: str) -> str:
    return f"{PREFIXO_DA_SESSAO}:{sessao}"


class WebOutbound(GuardedOutbound):
    """Publica a fala do agente no canal da sessao.

    Herda de `GuardedOutbound` porque e a rota segura: e a heranca que traz as
    guardas de opt-out e de atendimento humano, que o Protocol nao forca e que
    um adaptador escrito direto contra ele nao teria.

    `redis` e `Any` e nao `Redis`: o que se usa dele e so `publish`, e o
    worker passa o `ArqRedis` do `ctx` -- uma subclasse, mas o teste de falha
    precisa de um duble que so tenha esse metodo.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Any,
    ) -> None:
        super().__init__(session_factory)
        self._redis = redis

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        corpo = _frame_de(kind, payload)
        if corpo is None:
            log.warning(
                "web.kind_sem_forma",
                message_id=str(message_id),
                kind=kind,
                tipo=payload.get("tipo"),
            )
            return

        if self._redis is None:
            log.warning("web.sem_redis", message_id=str(message_id), kind=kind)
            return

        try:
            ouvintes = await self._redis.publish(
                canal_da_sessao(str(payload["para"])), json.dumps(corpo)
            )
        except RedisError as exc:
            # So o nome da classe, como no resto do projeto.
            log.warning(
                "web.publicacao_falhou",
                message_id=str(message_id),
                kind=kind,
                reason=type(exc).__name__,
            )
            return

        # `ouvintes == 0` e o caso normal de uma aba fechada, nao falha -- ver
        # o docstring do modulo.
        log.info("web.publicado", message_id=str(message_id), kind=kind, ouvintes=int(ouvintes))


def _frame_de(kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Traduz o payload da porta para o frame que o navegador le.

    `tipo` ausente e texto, pelo mesmo default que `WhatsAppOutbound` aplica:
    os chamadores anteriores a TEC-162 nao mandam a chave.
    """
    tipo = payload.get("tipo")
    if tipo is None:
        return {"tipo": "mensagem", "texto": payload["texto"], "kind": kind}
    if tipo == "imagem":
        return {
            "tipo": "imagem",
            "link": payload["link"],
            "legenda": payload["legenda"],
            "kind": kind,
        }
    return None

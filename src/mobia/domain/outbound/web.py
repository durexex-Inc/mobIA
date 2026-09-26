"""A entrega no canal web: publicar na sessao aberta. TEC-124, D4.

**Este adaptador nao levanta excecao nenhuma, e isso diverge de proposito do
contrato que `OutboundPort` escreve.** La, falha de rede e `EnvioRetentavel`
porque no WhatsApp a rede e o UNICO caminho ate o lead: sem ela, ele nunca
recebe. Aqui nao e. Assim que `send` devolve, o turno grava a fala do agente
em `messages` pelo `MessageRecorder` -- a ordem em `turno.py` e entregar e so
entao gravar --, e a reconexao a mostra (ver `domain/messages/historico.py`).
Como este adaptador nunca levanta, a gravacao nao depende de haver alguem
ouvindo: a publicacao e o atalho que faz a fala chegar AGORA, nao o caminho
que a faz chegar. Retentar custaria uma chamada nova e paga ao modelo para
reentregar o que a gravacao seguinte ja vai guardar, por causa de uma aba que
a visitante fechou.

Por isso publicacao sem ouvinte sai em `info` e e o caso NORMAL, nao falha.

**A janela que sobra e o worker cancelado ENTRE publicar e gravar** -- o
`job_timeout` do ARQ, um shutdown. A reserva em `outbound_dispatches` ja esta
commitada, entao a retentativa do sweeper cai na supressao de reentrega e a
fala nunca chega a `messages`; se ninguem ouvia naquele instante, a visitante
nao a ve nem na reconexao. O WhatsApp tem a mesma janela -- la o lead recebeu,
aqui talvez nao --, e fecha-la exigiria inverter a ordem do turno para os dois
canais, que nao e escopo da TEC-124.

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
from datetime import UTC, datetime, timedelta
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


# Quanto tempo o cliente deve manter o indicador aceso. **O 25 vem do
# WhatsApp**: a Emenda E-01 da RN-04.7 registra que o indicador da Meta some
# sozinho apos 25 s, e a L1 da TEC-274 registra que aquela card nao o renova.
# Igualar e o ponto -- um valor diferente aqui faria o MESMO turno parecer
# diferente em cada canal, sem nada no produto que justificasse.
#
# Constante e nao `Settings`: no WhatsApp esta duracao nao e nossa, e um botao
# que configurasse so o lado web seria um botao para desalinhar os canais.
DURACAO_DO_INDICADOR = timedelta(seconds=25)


class WebIndicador:
    """Publica o evento `digitando` na sessao aberta. TEC-362, RN-04.7.

    **Fecha a lacuna que a D5 da TEC-124 declarou** -- la o web ficou com
    `IndicadorNoop` porque publicar exigiria a sessao na assinatura do
    `IndicadorDePresencaPort`, e aquela card nao mexeu no contrato. Esta mexeu:
    `para` e a sessao.

    **Nao herda de `GuardedOutbound`**, pela mesma razao que o
    `WhatsAppIndicador` escreve: nao ha o que reservar, o indicador nao e
    mensagem e nao tem `kind`, e herdar obrigaria a inventar um kind sintetico
    numa tabela cuja UNIQUE existe para dedup de MENSAGEM. As guardas de
    opt-out e de atendimento humano moram no agendador
    (`domain/outbound/presenca.py`) e rodam no instante do disparo.

    **Excecao propaga crua**, ao contrario de `WebOutbound._deliver` logo
    acima. Nao e descuido: `OutboundPort.send` tem semantica de excecao -- o
    tipo decide o desfecho do turno --, e `IndicadorDePresencaPort` declara o
    oposto, que o agendador engole tudo e loga. Capturar aqui daria duas linhas
    de log para o mesmo evento.
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def indicar_digitacao(
        self, *, provider_message_id: str, de: str, para: str | None
    ) -> None:
        # `provider_message_id` e `de` sao ignorados aqui: no web o frame nao
        # e anotacao sobre a mensagem recebida, e sim evento proprio. Quem
        # identifica o destino e `para`, que e a chave da sessao (TEC-203).
        if para is None:
            log.info("web.indicador_sem_sessao")
            return
        if self._redis is None:
            log.warning("web.indicador_sem_redis")
            return

        ate = datetime.now(UTC) + DURACAO_DO_INDICADOR
        # `ate` e o que permite ao cliente parar SOZINHO. No WhatsApp quem
        # expira e a Meta, sem nos dizer quando; aqui o instante viaja no
        # frame, e isso e de graca.
        corpo = {"tipo": "digitando", "ate": ate.isoformat()}
        ouvintes = await self._redis.publish(canal_da_sessao(para), json.dumps(corpo))

        # Zero ouvintes e o caso NORMAL da aba fechada -- e aqui menos grave
        # que na entrega: um indicador nao vale nada fora do instante, entao
        # nao ha o que recuperar depois nem se quer.
        log.info("web.indicador_publicado", ouvintes=int(ouvintes))


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

"""Uma assinatura no Redis por processo, e a distribuicao em memoria. TEC-124.

**Por que nao uma assinatura por aba.** Era o desenho da primeira versao do
widget, e a revisao final da TEC-124 mostrou o custo: cada conexao anonima
segurava uma conexao do pool do Redis enquanto vivesse, e o limite por IP
conta handshakes por minuto, nao conexoes simultaneas. Um IP so esgotaria o
`maxclients` do MESMO Redis que e a fila do ARQ -- e derrubaria a ingestao do
WhatsApp e o worker junto com o widget.

Aqui ha uma conexao so, com `PSUBSCRIBE` no namespace do widget, e cada aba
aberta e uma fila em memoria. O custo por aba passa a ser memoria do processo
da API, e nao um recurso compartilhado.

**A assinatura e confirmada antes de qualquer aba ser registrada.** `abrir`
espera a central estar ouvindo, e so entao devolve a fila: quem recebeu a
fila ja tem para onde a publicacao ir. E a mesma garantia que a assinatura
por aba dava esperando o `SUBSCRIBE`, sem a corrida entre publicar e assinar.

**A queda do Redis nao mata a central.** A escuta se refaz sozinha, e as filas
das abas abertas sobrevivem a queda. O que se publica durante o intervalo nao
chega ao vivo -- e esta gravado em `messages`, e a reconexao da aba o mostra
(ver `domain/outbound/web.py`).
"""

import asyncio
from contextlib import suppress
from typing import Any

import structlog

from mobia.domain.outbound.web import PREFIXO_DA_SESSAO

log = structlog.get_logger(__name__)

# So o namespace do widget: um padrao largo (`*`) faria a central receber
# tambem o que o ARQ e o limitador fazem passar pelo mesmo Redis.
PADRAO = f"{PREFIXO_DA_SESSAO}:*"

# Quanto uma aba nova espera a central estar ouvindo. Sem isso, anunciar a
# sessao seria prometer uma conversa que talvez so funcione num sentido.
SEGUNDOS_PARA_ESTAR_OUVINDO = 5.0

# Pausa entre tentativas de refazer a escuta quando o Redis cai. Curta, porque
# enquanto ela dura as abas abertas nao recebem nada ao vivo.
SEGUNDOS_ENTRE_TENTATIVAS = 1.0


class CentralIndisponivel(Exception):
    """A central nao conseguiu ouvir o Redis a tempo de atender a aba."""


class CentralDoWidget:
    def __init__(self, redis: Any) -> None:
        self._redis = redis
        self._filas: dict[str, set[asyncio.Queue[str]]] = {}
        self._ouvindo = asyncio.Event()
        self._escuta: asyncio.Task[None] | None = None

    async def abrir(self, sessao: str) -> asyncio.Queue[str]:
        """Registra uma aba e devolve a fila onde as falas dela vao chegar."""
        if self._escuta is None or self._escuta.done():
            self._escuta = asyncio.create_task(self._escutar())
        try:
            await asyncio.wait_for(self._ouvindo.wait(), timeout=SEGUNDOS_PARA_ESTAR_OUVINDO)
        except TimeoutError as exc:
            raise CentralIndisponivel("a central nao esta ouvindo o Redis") from exc

        fila: asyncio.Queue[str] = asyncio.Queue()
        self._filas.setdefault(sessao, set()).add(fila)
        return fila

    def fechar(self, sessao: str, fila: asyncio.Queue[str]) -> None:
        filas = self._filas.get(sessao)
        if filas is None:
            return
        filas.discard(fila)
        if not filas:
            # Sem isso, cada sessao que ja passou por este processo deixaria
            # uma chave vazia para sempre.
            del self._filas[sessao]

    async def encerrar(self) -> None:
        if self._escuta is not None:
            self._escuta.cancel()
            with suppress(asyncio.CancelledError):
                await self._escuta
            self._escuta = None
        self._ouvindo.clear()

    async def _escutar(self) -> None:
        while True:
            assinatura = self._redis.pubsub()
            try:
                await assinatura.psubscribe(PADRAO)
                confirmacao = await assinatura.get_message(timeout=SEGUNDOS_PARA_ESTAR_OUVINDO)
                if confirmacao is None:
                    raise TimeoutError("o Redis nao confirmou o PSUBSCRIBE")
                self._ouvindo.set()
                log.info("widget.central_ouvindo")
                async for evento in assinatura.listen():
                    self._distribuir(evento)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Nunca deixa a tarefa morrer: uma escuta morta calaria todas
                # as abas deste processo, sem log e sem erro. So o nome da
                # classe, como no resto do projeto.
                self._ouvindo.clear()
                log.warning("widget.central_caiu", reason=type(exc).__name__)
                await asyncio.sleep(SEGUNDOS_ENTRE_TENTATIVAS)
            finally:
                with suppress(Exception):
                    await assinatura.aclose()

    def _distribuir(self, evento: dict[str, Any]) -> None:
        if evento.get("type") != "pmessage":
            return
        canal = _texto(evento["channel"])
        sessao = canal.removeprefix(f"{PREFIXO_DA_SESSAO}:")
        dado = _texto(evento["data"])
        # `tuple(...)`: uma aba fechando no meio da iteracao mexe no conjunto.
        for fila in tuple(self._filas.get(sessao, ())):
            fila.put_nowait(dado)


def _texto(valor: bytes | str) -> str:
    return valor.decode() if isinstance(valor, bytes) else valor


def central_de(app: Any) -> CentralDoWidget | None:
    """A central deste app, criada na primeira aba que precisar dela.

    Sem `await` entre ler e gravar `app.state`, entao duas abas chegando juntas
    nao criam duas centrais -- o event loop nao troca de tarefa no meio.
    `None` quando o app nao tem Redis montado.
    """
    pool = getattr(app.state, "redis_pool", None)
    if pool is None:
        return None
    central = getattr(app.state, "central_do_widget", None)
    if central is None:
        central = CentralDoWidget(pool)
        app.state.central_do_widget = central
    return central

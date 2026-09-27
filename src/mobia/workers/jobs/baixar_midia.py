"""Baixar a midia do lead, conferir e guardar cifrada. TEC-132, D3.

**Nada daqui toca a conversa** (D3): o turno ja confirmou o recebimento sem
esperar este job, e "recebi" continua verdade se o download falhar.

O unico estado e a linha de `midias_recebidas`. Toda saida grava um estado
terminal por `marcar`, que so muda linha ainda PENDENTE -- entao o job e
idempotente para o re-enqueue da varredura, e perde de forma limpa a corrida
contra `expirar_pendentes` e `esgotar_pendentes`.
"""

import base64
import binascii
import hashlib
import uuid
from typing import Any

import httpx
import structlog
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import Settings, get_settings
from mobia.domain.midia import graph
from mobia.domain.midia.armazem import ArmazemDeMidia
from mobia.domain.midia.models import MotivoDaMidia, StatusDaMidia
from mobia.domain.midia.politica import chave_do_objeto, tipo_permitido
from mobia.domain.midia.repositorio import ler_midia, marcar
from mobia.infra.crypto import aad_de, encrypt_bytes

log = structlog.get_logger(__name__)

MAXIMO_DE_TENTATIVAS = 5  # o mesmo `max_tries` do registro em workers/main.py

# Segundos por tentativa ja feita: 30, 60, 90, 120. Os ~5 minutos somados
# cabem com folga nos 7 dias de retencao da Meta, e espacam o bastante para
# um soluco da Graph API passar.
_SEGUNDOS_DE_BACKOFF = 30


class DesfechoDoDownload(Exception):
    """Um estado terminal decidido no meio do caminho.

    Publico desde a TEC-131: `transcrever_audio` baixa pela mesma sequencia
    (`baixar_e_guardar`) e grava o mesmo desfecho.
    """

    def __init__(self, status: StatusDaMidia, motivo: MotivoDaMidia) -> None:
        super().__init__(motivo.value)
        self.status = status
        self.motivo = motivo


def _sha256_confere(dados: bytes, esperado: str) -> bool:
    """Aceita o digest em hex ou em base64.

    O envelope do webhook e a resposta da resolucao nao documentam o mesmo
    formato, e a D3 nao fixa um. Aceitar os dois nao afrouxa a conferencia:
    os dois sao o mesmo digest de 32 bytes, so escritos diferente.
    """
    digest = hashlib.sha256(dados).digest()
    if esperado.lower() == digest.hex():
        return True
    try:
        return base64.b64decode(esperado, validate=True) == digest
    except (binascii.Error, ValueError):
        return False


async def baixar_midia(ctx: dict[str, Any], message_id: str) -> str:
    """Devolve o status gravado, em minusculas, ou `nada_a_fazer`.

    Nao ha retorno "retentar": o pedido de nova tentativa e o `Retry` do ARQ,
    levantado.
    """
    identificador = uuid.UUID(message_id)
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    async with session_factory() as sessao:
        midia = await ler_midia(sessao, identificador)
    if midia is None or midia.status != StatusDaMidia.PENDENTE:
        return "nada_a_fazer"
    media_id = midia.media_id_da_meta
    sha256_esperado = midia.sha256

    tentativa: int = ctx.get("job_try", 1)
    injetado: httpx.AsyncClient | None = ctx.get("cliente_http_da_meta")
    # Sem cliente no ctx, um por job, como o `WhatsAppOutbound` faz por
    # entrega: o `startup` nao guarda um cliente longo para a Meta, e este job
    # nao e quente o bastante para o reuso de conexao pagar a diferenca.
    cliente = injetado or httpx.AsyncClient(timeout=graph.TIMEOUT_SEGUNDOS)
    try:
        chave, dados = await baixar_e_guardar(
            identificador,
            media_id,
            sha256_esperado,
            teto=settings.midia_teto_bytes,
            cliente=cliente,
            armazem=ctx["armazem"],
        )
    except DesfechoDoDownload as desfecho:
        return await gravar_desfecho(
            session_factory, identificador, desfecho.status, desfecho.motivo
        )
    except graph.MidiaIndisponivel as exc:
        if tentativa < MAXIMO_DE_TENTATIVAS:
            log.info(
                "midia.retentar",
                message_id=message_id,
                tentativa=tentativa,
                motivo=str(exc),
            )
            raise Retry(defer=_SEGUNDOS_DE_BACKOFF * tentativa) from exc
        return await gravar_desfecho(
            session_factory,
            identificador,
            StatusDaMidia.FALHOU,
            MotivoDaMidia.TENTATIVAS_ESGOTADAS,
        )
    finally:
        if injetado is None:
            await cliente.aclose()

    return await gravar_desfecho(
        session_factory,
        identificador,
        StatusDaMidia.ARMAZENADA,
        None,
        chave=chave,
        tamanho=len(dados),
    )


async def baixar_e_guardar(
    identificador: uuid.UUID,
    media_id: str,
    sha256_esperado: str | None,
    *,
    teto: int,
    cliente: httpx.AsyncClient,
    armazem: ArmazemDeMidia,
) -> tuple[str, bytes]:
    """A sequencia da D3. Devolve a chave e os bytes em claro.

    Os bytes, e nao so o tamanho, desde a TEC-131: quem transcreve precisa do
    audio que acabou de baixar, e reler do armazem seria decifrar o que ainda
    esta na memoria.

    Todo estado terminal sai como `DesfechoDoDownload` -- inclusive a recusa da
    Meta e o estouro do teto no streaming, que antes eram traduzidos por quem
    chamava. Com dois chamadores, a traducao mora aqui. So o retentavel
    (`graph.MidiaIndisponivel`) escapa, porque cada chamador o trata de um
    jeito: `baixar_midia` pede `Retry`, a transcricao desiste.
    """
    try:
        meta = await graph.resolver(media_id, cliente=cliente)
        # O tipo da RESOLUCAO, e nao o do envelope: e o que a Meta diz do
        # arquivo que ela vai entregar.
        if not tipo_permitido(meta.mime_type):
            raise DesfechoDoDownload(StatusDaMidia.RECUSADA, MotivoDaMidia.TIPO_NAO_PERMITIDO)
        if meta.tamanho is not None and meta.tamanho > teto:
            raise DesfechoDoDownload(StatusDaMidia.RECUSADA, MotivoDaMidia.ACIMA_DO_TETO)

        dados = await graph.baixar(meta.url, teto=teto, cliente=cliente)
    except graph.MidiaRecusada as exc:
        raise DesfechoDoDownload(StatusDaMidia.FALHOU, MotivoDaMidia.RECUSADA_PELA_META) from exc
    except graph.MidiaAcimaDoTeto as exc:
        raise DesfechoDoDownload(StatusDaMidia.RECUSADA, MotivoDaMidia.ACIMA_DO_TETO) from exc

    # So quando o envelope trouxe um: sem digest nao ha contra o que conferir,
    # e recusar por isso perderia toda midia de um envelope que nao o manda.
    if sha256_esperado and not _sha256_confere(dados, sha256_esperado):
        raise DesfechoDoDownload(StatusDaMidia.FALHOU, MotivoDaMidia.SHA256_DIVERGENTE)

    blob = encrypt_bytes(dados, aad_de(identificador, "midia"))
    chave = chave_do_objeto(identificador)
    try:
        await armazem.guardar(chave, blob)
    except Exception as exc:
        # Disco cheio, S3 fora: o arquivo ainda existe na Meta, entao e o
        # mesmo caso de uma Graph API fora do ar -- retenta.
        raise graph.MidiaIndisponivel(f"armazem: {type(exc).__name__}") from exc
    return chave, dados


async def gravar_desfecho(
    session_factory: async_sessionmaker[AsyncSession],
    identificador: uuid.UUID,
    status: StatusDaMidia,
    motivo: MotivoDaMidia | None,
    *,
    chave: str | None = None,
    tamanho: int | None = None,
) -> str:
    mudou = await marcar(
        session_factory, identificador, status=status, motivo=motivo, chave=chave, tamanho=tamanho
    )
    if not mudou:
        # A varredura fechou a linha (EXPIRADA, ou TENTATIVAS_ESGOTADAS pelo
        # teto de re-enfileiramentos) enquanto este job rodava. Nao e erro:
        # o estado terminal dela vale, e este desfecho e descartado.
        # Se foi um sucesso, o blob ja gravado fica orfao no armazem: cifrado,
        # na chave da propria mensagem, e sem linha que aponte para ele.
        log.info(
            "midia.corrida_perdida",
            message_id=str(identificador),
            status=status.value,
            motivo=motivo.value if motivo else None,
        )
        return "nada_a_fazer"
    rotulo = status.value.lower()
    # FALHOU em WARNING, qualquer que seja o motivo: e midia que o sistema
    # desistiu de guardar, e e o nivel que pode alimentar alerta. RECUSADA
    # (tipo ou tamanho fora da politica) e ARMAZENADA sao o caminho previsto, e
    # ficam em INFO.
    emitir = log.warning if status == StatusDaMidia.FALHOU else log.info
    emitir(
        f"midia.{rotulo}",
        message_id=str(identificador),
        status=status.value,
        motivo=motivo.value if motivo else None,
    )
    return rotulo

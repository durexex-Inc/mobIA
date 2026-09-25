"""O job que baixa a midia do lead e a guarda cifrada. TEC-132, D3.

A Graph API e simulada por `httpx.MockTransport`: o primeiro `GET` (no
`media_id`) resolve a URL temporaria, o segundo (na URL) entrega os bytes. O
armazem e um diretorio temporario, para o teste poder ler o que foi gravado.
"""

import base64
import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from arq import Retry
from conftest import eventos_de_log

from mobia.app.config import get_settings
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.models import MidiaRecebida, MotivoDaMidia, StatusDaMidia
from mobia.domain.midia.repositorio import ler_midia
from mobia.infra.crypto import aad_de, decrypt_bytes
from mobia.infra.db import get_sessionmaker
from mobia.infra.queue import BAIXAR_MIDIA_JOB
from mobia.workers.jobs.baixar_midia import MAXIMO_DE_TENTATIVAS, baixar_midia
from mobia.workers.main import WorkerSettings

TOKEN = "token-de-teste"
URL_DA_META = "https://lookaside.fbsbx.com/x"
DADOS = b"\x89PNG" + b"a" * 60
TETO = 100


@pytest.fixture
def configuracao(monkeypatch: pytest.MonkeyPatch):
    """O token e o teto que o job e a Graph leem, no mesmo objeto de settings."""
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_access_token", TOKEN)
    monkeypatch.setattr(settings, "midia_teto_bytes", TETO)
    return settings


async def _gravar_midia(
    session, *, sha256: str | None = None, mime: str = "image/png", sem_sha: bool = False
) -> uuid.UUID:
    """A mensagem e a linha PENDENTE que a ingestao teria gravado."""
    mensagem = Message(
        channel="whatsapp",
        conversation_key="5511911112222",
        sender_external_id="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.IMAGEM,
        status=MessageStatus.RECEIVED,
    )
    session.add(mensagem)
    await session.commit()
    session.add(
        MidiaRecebida(
            message_id=mensagem.id,
            media_id_da_meta="media-1",
            mime_type=mime,
            sha256=None if sem_sha else (sha256 or hashlib.sha256(DADOS).hexdigest()),
            status=StatusDaMidia.PENDENTE,
        )
    )
    await session.commit()
    return mensagem.id


def _meta(
    *,
    mime: str = "image/png",
    tamanho: int | None = len(DADOS),
    corpo: bytes = DADOS,
    status_resolucao: int = 200,
    status_download: int = 200,
    chamadas: list[str] | None = None,
) -> httpx.AsyncClient:
    """Um cliente que responde como a Graph API, e afirma o bearer nos dois GET."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if chamadas is not None:
            chamadas.append(str(request.url))
        if str(request.url) == URL_DA_META:
            return httpx.Response(status_download, content=corpo)
        assert str(request.url) == f"{get_settings().whatsapp_api_base}/media-1"
        corpo_json: dict[str, Any] = {"url": URL_DA_META, "mime_type": mime}
        if tamanho is not None:
            corpo_json["file_size"] = tamanho
        return httpx.Response(status_resolucao, json=corpo_json)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _ctx(cliente: httpx.AsyncClient, armazem: Any, settings: Any, job_try: int = 1) -> dict:
    return {
        "session_factory": get_sessionmaker(),
        "settings": settings,
        "armazem": armazem,
        "cliente_http_da_meta": cliente,
        "job_try": job_try,
    }


def _arquivos(raiz: Path) -> list[Path]:
    return [p for p in raiz.rglob("*") if p.is_file()]


async def _linha(session, message_id: uuid.UUID) -> MidiaRecebida:
    session.expire_all()
    linha = await ler_midia(session, message_id)
    assert linha is not None
    return linha


async def test_sucesso_armazena_cifrado(session, configuracao, tmp_path: Path) -> None:
    message_id = await _gravar_midia(session)

    resultado = await baixar_midia(
        _ctx(_meta(), ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "armazenada"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.ARMAZENADA
    assert linha.chave_no_armazem == f"midias/{message_id}"
    assert linha.bytes == len(DADOS)
    arquivo = (tmp_path / "midias" / str(message_id)).read_bytes()
    assert arquivo != DADOS
    assert decrypt_bytes(arquivo, aad_de(message_id, "midia")) == DADOS


async def test_sha256_em_base64_tambem_confere(session, configuracao, tmp_path: Path) -> None:
    """O envelope da Meta pode trazer o digest em base64 e nao em hex."""
    em_base64 = base64.b64encode(hashlib.sha256(DADOS).digest()).decode()
    message_id = await _gravar_midia(session, sha256=em_base64)

    resultado = await baixar_midia(
        _ctx(_meta(), ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "armazenada"


async def test_sem_sha256_no_envelope_nao_confere(session, configuracao, tmp_path: Path) -> None:
    message_id = await _gravar_midia(session, sem_sha=True)

    resultado = await baixar_midia(
        _ctx(_meta(), ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "armazenada"


async def test_tipo_fora_da_allowlist_recusa_sem_baixar(
    session, configuracao, tmp_path: Path
) -> None:
    message_id = await _gravar_midia(session)
    chamadas: list[str] = []

    resultado = await baixar_midia(
        _ctx(
            _meta(mime="application/zip", chamadas=chamadas), ArmazemLocal(tmp_path), configuracao
        ),
        str(message_id),
    )

    assert resultado == "recusada"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.RECUSADA
    assert linha.motivo == MotivoDaMidia.TIPO_NAO_PERMITIDO
    assert URL_DA_META not in chamadas
    assert _arquivos(tmp_path) == []


async def test_file_size_acima_do_teto_recusa_sem_baixar(
    session, configuracao, tmp_path: Path
) -> None:
    message_id = await _gravar_midia(session)
    chamadas: list[str] = []

    resultado = await baixar_midia(
        _ctx(_meta(tamanho=TETO + 1, chamadas=chamadas), ArmazemLocal(tmp_path), configuracao),
        str(message_id),
    )

    assert resultado == "recusada"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.RECUSADA
    assert linha.motivo == MotivoDaMidia.ACIMA_DO_TETO
    assert URL_DA_META not in chamadas


async def test_estouro_do_teto_no_streaming_recusa(session, configuracao, tmp_path: Path) -> None:
    """O `file_size` mente: diz 10 bytes, e o corpo passa do teto."""
    message_id = await _gravar_midia(session)

    resultado = await baixar_midia(
        _ctx(_meta(tamanho=10, corpo=b"x" * (TETO + 1)), ArmazemLocal(tmp_path), configuracao),
        str(message_id),
    )

    assert resultado == "recusada"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.RECUSADA
    assert linha.motivo == MotivoDaMidia.ACIMA_DO_TETO
    assert _arquivos(tmp_path) == []


async def test_sha256_divergente_falha(session, configuracao, tmp_path: Path) -> None:
    message_id = await _gravar_midia(session, sha256="00" * 32)

    resultado = await baixar_midia(
        _ctx(_meta(), ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "falhou"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.FALHOU
    assert linha.motivo == MotivoDaMidia.SHA256_DIVERGENTE
    assert _arquivos(tmp_path) == []


@pytest.mark.parametrize("onde", ["resolucao", "download"])
async def test_4xx_marca_falhou_sem_retentar(
    session, configuracao, tmp_path: Path, onde: str
) -> None:
    message_id = await _gravar_midia(session)
    cliente = _meta(status_resolucao=404) if onde == "resolucao" else _meta(status_download=403)

    resultado = await baixar_midia(
        _ctx(cliente, ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "falhou"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.FALHOU
    assert linha.motivo == MotivoDaMidia.RECUSADA_PELA_META


async def test_429_retenta_e_nao_recusa(session, configuracao, tmp_path: Path) -> None:
    """429 e 4xx na faixa, mas e a Meta pedindo para tentar depois -- mesmo
    carve-out de `CODIGOS_4XX_RETENTAVEIS` em `domain/outbound/whatsapp.py`."""
    message_id = await _gravar_midia(session)

    with pytest.raises(Retry):
        await baixar_midia(
            _ctx(_meta(status_resolucao=429), ArmazemLocal(tmp_path), configuracao),
            str(message_id),
        )

    assert (await _linha(session, message_id)).status == StatusDaMidia.PENDENTE


async def test_5xx_pede_retry(session, configuracao, tmp_path: Path) -> None:
    message_id = await _gravar_midia(session)

    with pytest.raises(Retry):
        await baixar_midia(
            _ctx(_meta(status_download=503), ArmazemLocal(tmp_path), configuracao, job_try=1),
            str(message_id),
        )
    assert (await _linha(session, message_id)).status == StatusDaMidia.PENDENTE

    resultado = await baixar_midia(
        _ctx(
            _meta(status_download=503),
            ArmazemLocal(tmp_path),
            configuracao,
            job_try=MAXIMO_DE_TENTATIVAS,
        ),
        str(message_id),
    )

    assert resultado == "falhou"
    linha = await _linha(session, message_id)
    assert linha.status == StatusDaMidia.FALHOU
    assert linha.motivo == MotivoDaMidia.TENTATIVAS_ESGOTADAS


async def test_erro_de_rede_pede_retry(session, configuracao, tmp_path: Path) -> None:
    message_id = await _gravar_midia(session)

    def _levanta(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rota")

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_levanta))

    with pytest.raises(Retry):
        await baixar_midia(_ctx(cliente, ArmazemLocal(tmp_path), configuracao), str(message_id))


class _ArmazemQueLevanta:
    async def guardar(self, chave: str, dados: bytes) -> None:
        raise OSError("disco cheio")

    async def ler(self, chave: str) -> bytes:
        raise AssertionError("o job nao le")


async def test_falha_do_armazem_retenta(session, configuracao) -> None:
    message_id = await _gravar_midia(session)

    with pytest.raises(Retry):
        await baixar_midia(_ctx(_meta(), _ArmazemQueLevanta(), configuracao), str(message_id))
    assert (await _linha(session, message_id)).status == StatusDaMidia.PENDENTE

    resultado = await baixar_midia(
        _ctx(_meta(), _ArmazemQueLevanta(), configuracao, job_try=MAXIMO_DE_TENTATIVAS),
        str(message_id),
    )
    assert resultado == "falhou"
    assert (await _linha(session, message_id)).motivo == MotivoDaMidia.TENTATIVAS_ESGOTADAS


async def test_midia_ja_armazenada_nao_baixa_de_novo(session, configuracao, tmp_path: Path) -> None:
    message_id = await _gravar_midia(session)
    assert (
        await baixar_midia(_ctx(_meta(), ArmazemLocal(tmp_path), configuracao), str(message_id))
        == "armazenada"
    )
    chamadas: list[str] = []

    resultado = await baixar_midia(
        _ctx(_meta(chamadas=chamadas), ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "nada_a_fazer"
    assert chamadas == []


async def test_mensagem_sem_linha_de_midia_nao_faz_nada(
    session, configuracao, tmp_path: Path
) -> None:
    chamadas: list[str] = []

    resultado = await baixar_midia(
        _ctx(_meta(chamadas=chamadas), ArmazemLocal(tmp_path), configuracao), str(uuid.uuid4())
    )

    assert resultado == "nada_a_fazer"
    assert chamadas == []


async def test_log_nao_leva_a_url(session, configuracao, tmp_path: Path, caplog: Any) -> None:
    """A URL da Meta e credencial de curta duracao: nenhum desfecho a loga."""
    cenarios: list[Callable[[], httpx.AsyncClient]] = [
        _meta,
        lambda: _meta(status_download=403),
        lambda: _meta(status_download=503),
        lambda: _meta(tamanho=10, corpo=b"x" * (TETO + 1)),
    ]
    with caplog.at_level("DEBUG"):
        for fabrica in cenarios:
            message_id = await _gravar_midia(session)
            try:
                await baixar_midia(
                    _ctx(fabrica(), ArmazemLocal(tmp_path), configuracao), str(message_id)
                )
            except Retry:
                pass

    # Os desfechos de fato logaram -- sem isto, um caplog cego passaria.
    assert eventos_de_log(caplog, "midia.armazenada")
    assert eventos_de_log(caplog, "midia.retentar")
    assert all("lookaside" not in registro.getMessage() for registro in caplog.records)


def test_baixar_midia_registrado_sem_reter_resultado() -> None:
    """Amarra BAIXAR_MIDIA_JOB ao nome registrado, com `keep_result=0` (o
    `_job_id` e fixo, ver `enqueue_baixar_midia`) e o teto de tentativas que o
    job usa para decidir quando parar de pedir `Retry`."""
    registrada = next(
        f for f in WorkerSettings.functions if getattr(f, "name", None) == BAIXAR_MIDIA_JOB
    )
    assert registrada.keep_result_s == 0
    assert registrada.max_tries == MAXIMO_DE_TENTATIVAS


async def test_url_malformada_da_meta_e_recusa_e_nao_retentativa(
    session, configuracao, tmp_path: Path
) -> None:
    """`httpx.InvalidURL` nao e `RequestError`: sem tratamento proprio, ela
    escapava dos dois `except` do job, a linha ficava PENDENTE e voltava pela
    varredura. URL malformada nao melhora com retentativa -- e recusa."""
    message_id = await _gravar_midia(session)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"url": "http://a:porta-invalida/", "mime_type": "image/png"}
        )

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    resultado = await baixar_midia(
        _ctx(cliente, ArmazemLocal(tmp_path), configuracao), str(message_id)
    )

    assert resultado == "falhou"
    linha = await _linha(session, message_id)
    assert (linha.status, linha.motivo) == (StatusDaMidia.FALHOU, MotivoDaMidia.RECUSADA_PELA_META)


async def test_falhou_loga_em_warning_e_os_outros_desfechos_em_info(
    session, configuracao, tmp_path: Path, caplog: Any
) -> None:
    """M4 da revisao final: FALHOU e midia que o sistema desistiu de guardar,
    e precisa poder alimentar alerta. RECUSADA e ARMAZENADA sao o caminho
    previsto, e ficam em INFO."""
    cenarios: list[Callable[[], httpx.AsyncClient]] = [
        _meta,
        lambda: _meta(mime="application/zip"),
        lambda: _meta(status_download=403),
    ]
    with caplog.at_level("INFO"):
        for fabrica in cenarios:
            message_id = await _gravar_midia(session)
            await baixar_midia(
                _ctx(fabrica(), ArmazemLocal(tmp_path), configuracao), str(message_id)
            )
        esgotada = await _gravar_midia(session)
        await baixar_midia(
            _ctx(
                _meta(status_download=503),
                ArmazemLocal(tmp_path),
                configuracao,
                job_try=MAXIMO_DE_TENTATIVAS,
            ),
            str(esgotada),
        )
        divergente = await _gravar_midia(session, sha256="00" * 32)
        await baixar_midia(_ctx(_meta(), ArmazemLocal(tmp_path), configuracao), str(divergente))

    assert [e.nivel for e in eventos_de_log(caplog, "midia.armazenada")] == ["INFO"]
    assert [e.nivel for e in eventos_de_log(caplog, "midia.recusada")] == ["INFO"]
    falhas = eventos_de_log(caplog, "midia.falhou")
    assert sorted(e.corpo["motivo"] for e in falhas) == sorted(
        [
            MotivoDaMidia.RECUSADA_PELA_META,
            MotivoDaMidia.TENTATIVAS_ESGOTADAS,
            MotivoDaMidia.SHA256_DIVERGENTE,
        ]
    )
    assert {e.nivel for e in falhas} == {"WARNING"}

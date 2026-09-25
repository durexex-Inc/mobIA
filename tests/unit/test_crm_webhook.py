"""O adaptador de webhook: cabecalhos, assinatura e o que vira falha. TEC-180."""

import json
import uuid
from typing import Any

import httpx
import pytest

from mobia.app.config import get_settings
from mobia.domain.crm.port import FalhaDeExportacao
from mobia.domain.crm.webhook import (
    CABECALHO_DE_ASSINATURA,
    CABECALHO_DE_IDEMPOTENCIA,
    CrmWebhook,
)
from mobia.infra.signature import compute_signature
from mobia.workers.jobs.exportar_crm import espera_de

HANDOFF = uuid.UUID("11111111-2222-3333-4444-555555555555")
PAYLOAD = {"versao": 1, "handoff_id": str(HANDOFF)}


@pytest.fixture(autouse=True)
def _limpar_settings() -> Any:
    """`get_settings` e cacheada -- sem isto um teste herdaria o env do outro."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _cliente(capturadas: list[httpx.Request], status: int = 200) -> httpx.AsyncClient:
    def responder(request: httpx.Request) -> httpx.Response:
        capturadas.append(request)
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


def _configurar(monkeypatch: pytest.MonkeyPatch, **valores: str) -> None:
    padroes = {"CRM_WEBHOOK_URL": "https://crm.exemplo/hook"}
    for chave, valor in (padroes | valores).items():
        monkeypatch.setenv(chave, valor)
    get_settings.cache_clear()


async def test_o_post_vai_para_a_url_configurada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quarto cenario do Gherkin: trocar de destino e trocar configuracao."""
    _configurar(monkeypatch, CRM_WEBHOOK_URL="https://outro.crm/entrada")
    capturadas: list[httpx.Request] = []

    await CrmWebhook(_cliente(capturadas)).exportar(handoff_id=HANDOFF, payload=PAYLOAD)

    assert str(capturadas[0].url) == "https://outro.crm/entrada"
    assert json.loads(capturadas[0].content) == PAYLOAD


async def test_a_chave_de_idempotencia_e_o_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """D6: a camada que so o consumidor consegue fechar.

    A guarda por `crm_sincronizado_em` nao cobre a resposta perdida depois de o
    CRM ja ter gravado. A chave e o que permite ao outro lado dedupar.
    """
    _configurar(monkeypatch)
    capturadas: list[httpx.Request] = []

    await CrmWebhook(_cliente(capturadas)).exportar(handoff_id=HANDOFF, payload=PAYLOAD)

    assert capturadas[0].headers[CABECALHO_DE_IDEMPOTENCIA] == str(HANDOFF)


async def test_com_segredo_a_assinatura_cobre_os_bytes_enviados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A assinatura tem de bater com o corpo EXATO, nao com uma re-serializacao.

    E por isso que o adaptador serializa uma vez so e manda `content=`: dois
    `json.dumps` do mesmo dicionario podem diferir, e o sintoma apareceria so
    do outro lado do fio, como assinatura recusada.
    """
    _configurar(monkeypatch, CRM_WEBHOOK_SECRET="segredo-do-crm")
    capturadas: list[httpx.Request] = []

    await CrmWebhook(_cliente(capturadas)).exportar(handoff_id=HANDOFF, payload=PAYLOAD)

    enviada = capturadas[0].headers[CABECALHO_DE_ASSINATURA]
    assert enviada == compute_signature("segredo-do-crm", capturadas[0].content)


async def test_sem_segredo_nao_vai_assinatura(monkeypatch: pytest.MonkeyPatch) -> None:
    _configurar(monkeypatch, CRM_WEBHOOK_SECRET="")
    capturadas: list[httpx.Request] = []

    await CrmWebhook(_cliente(capturadas)).exportar(handoff_id=HANDOFF, payload=PAYLOAD)

    assert CABECALHO_DE_ASSINATURA not in capturadas[0].headers


@pytest.mark.parametrize("status", [400, 401, 404, 422, 500, 503])
async def test_qualquer_coisa_que_nao_seja_2xx_vira_falha(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Inclusive 4xx, ao contrario de `WhatsAppOutbound`.

    La a recusa permanente evita retentar um turno que ja custou uma chamada
    paga ao modelo. Aqui o consumidor e desconhecido: um 400 pode ser um proxy
    mal configurado e um 401 quase sempre e segredo desatualizado, que alguem
    conserta. Desistir na primeira seria a perda silenciosa da RN-16.5.
    """
    _configurar(monkeypatch)

    with pytest.raises(FalhaDeExportacao) as capturada:
        await CrmWebhook(_cliente([], status=status)).exportar(handoff_id=HANDOFF, payload=PAYLOAD)

    assert capturada.value.motivo == f"HTTP {status}"


async def test_erro_de_rede_vira_falha_com_o_nome_da_classe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A garantia sobre `motivo` e deste sitio -- ver o docstring da excecao.

    `str(falha)` de uma excecao do httpx carrega a URL, e ela e segredo de
    configuracao. `crm_ultimo_erro` e coluna duravel e em claro (TEC-222).
    """
    _configurar(monkeypatch)

    def estourar(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out conectando em https://crm.exemplo/hook")

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(estourar))

    with pytest.raises(FalhaDeExportacao) as capturada:
        await CrmWebhook(cliente).exportar(handoff_id=HANDOFF, payload=PAYLOAD)

    assert capturada.value.motivo == "ConnectTimeout"
    assert "crm.exemplo" not in capturada.value.motivo


def test_o_backoff_e_exponencial_a_partir_da_base() -> None:
    """RN-16.5: tres tentativas com backoff exponencial.

    `tentativas` e quantas JA falharam, entao a primeira espera usa expoente
    zero. Nao ha terceira espera: a terceira falha e terminal.
    """
    assert espera_de(1, 30.0) == 30.0
    assert espera_de(2, 30.0) == 60.0
